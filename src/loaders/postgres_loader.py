from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import psycopg2
from psycopg2.extras import execute_values

from src.attributes import TenderAttributes
from src.loaders.settings import postgres_dsn

UPSERT_LOCATIONS = """
INSERT INTO ods.tender_locations (
    tender_id, city, region, location_raw, url, source, loaded_at
)
VALUES %s
ON CONFLICT (tender_id) DO UPDATE SET
    city = EXCLUDED.city,
    region = EXCLUDED.region,
    location_raw = EXCLUDED.location_raw,
    url = EXCLUDED.url,
    source = EXCLUDED.source,
    loaded_at = NOW()
"""

UPSERT_PRICES = """
INSERT INTO ods.tender_prices (
    tender_id, price_rub, price_raw, currency, price_kind, url, source, loaded_at
)
VALUES %s
ON CONFLICT (tender_id) DO UPDATE SET
    price_rub = EXCLUDED.price_rub,
    price_raw = EXCLUDED.price_raw,
    currency = EXCLUDED.currency,
    price_kind = EXCLUDED.price_kind,
    url = EXCLUDED.url,
    source = EXCLUDED.source,
    loaded_at = NOW()
"""

UPSERT_CARDS = """
INSERT INTO ods.tender_cards (
    tender_id, url, status, procedure_group, procedure_name,
    nmck_rub, nmck_raw, price_kind,
    application_start, application_end, contract_date, loaded_at
)
VALUES %s
ON CONFLICT (tender_id) DO UPDATE SET
    url = EXCLUDED.url,
    status = EXCLUDED.status,
    procedure_group = EXCLUDED.procedure_group,
    procedure_name = EXCLUDED.procedure_name,
    nmck_rub = EXCLUDED.nmck_rub,
    nmck_raw = EXCLUDED.nmck_raw,
    price_kind = EXCLUDED.price_kind,
    application_start = EXCLUDED.application_start,
    application_end = EXCLUDED.application_end,
    contract_date = EXCLUDED.contract_date,
    loaded_at = NOW()
"""


class PostgresLoader:
    def __init__(self, dsn: str | None = None) -> None:
        self.dsn = dsn or postgres_dsn()
        self.conn = psycopg2.connect(self.dsn)
        self.conn.autocommit = False

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> PostgresLoader:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.close()

    def ensure_schema(self, ddl_sql: str | None = None) -> None:
        sql = ddl_sql or _default_ddl()
        with self.conn.cursor() as cur:
            cur.execute(sql)
        self.conn.commit()

    def upsert_attributes(self, items: Iterable[TenderAttributes]) -> tuple[int, int]:
        return self.upsert_records(
            [item.location_record() for item in items],
            [item.price_record() for item in items],
        )

    def upsert_records(
        self,
        locations: list[dict],
        prices: list[dict],
    ) -> tuple[int, int]:
        location_rows = [
            (
                loc["tender_id"],
                loc.get("city"),
                loc.get("region"),
                loc.get("location_raw"),
                loc.get("url"),
                loc.get("source"),
            )
            for loc in locations
        ]
        price_rows = [
            (
                price["tender_id"],
                price.get("price_rub"),
                price.get("price_raw"),
                price.get("currency") or "RUB",
                price.get("price_kind") or "nmck",
                price.get("url"),
                price.get("source"),
            )
            for price in prices
        ]
        with self.conn.cursor() as cur:
            if location_rows:
                execute_values(
                    cur,
                    UPSERT_LOCATIONS,
                    location_rows,
                    template="(%s, %s, %s, %s, %s, %s, NOW())",
                )
            if price_rows:
                execute_values(
                    cur,
                    UPSERT_PRICES,
                    price_rows,
                    template="(%s, %s, %s, %s, %s, %s, %s, NOW())",
                )
        self.conn.commit()
        return len(location_rows), len(price_rows)

    def upsert_cards(self, cards: list[dict]) -> int:
        if not cards:
            return 0
        rows = [
            (
                card["tender_id"],
                card.get("url"),
                card.get("status"),
                card.get("procedure_group"),
                card.get("procedure_name"),
                card.get("nmck_rub"),
                card.get("nmck_raw"),
                card.get("price_kind") or "nmck",
                _as_datetime(card.get("application_start")),
                _as_datetime(card.get("application_end")),
                _as_date(card.get("contract_date")),
            )
            for card in cards
        ]
        tender_ids = [card["tender_id"] for card in cards]
        industry_rows = [
            (card["tender_id"], industry)
            for card in cards
            for industry in (card.get("industries") or [])
        ]
        with self.conn.cursor() as cur:
            execute_values(
                cur,
                UPSERT_CARDS,
                rows,
                template="(%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
            )
            cur.execute(
                "DELETE FROM ods.tender_industries WHERE tender_id = ANY(%s)",
                (tender_ids,),
            )
            if industry_rows:
                execute_values(
                    cur,
                    """
                    INSERT INTO ods.tender_industries (tender_id, industry)
                    VALUES %s
                    ON CONFLICT (tender_id, industry) DO NOTHING
                    """,
                    industry_rows,
                )
        self.conn.commit()
        return len(rows)

    def fetch_location(self, tender_id: str) -> tuple | None:
        with self.conn.cursor() as cur:
            cur.execute(
                "SELECT tender_id, city, region FROM ods.tender_locations WHERE tender_id = %s",
                (tender_id,),
            )
            return cur.fetchone()

    def count_locations(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ods.tender_locations")
            return int(cur.fetchone()[0])

    def count_prices(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM ods.tender_prices")
            return int(cur.fetchone()[0])

    def storage_size_bytes(self) -> int:
        with self.conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    pg_total_relation_size('ods.tender_locations')
                    + pg_total_relation_size('ods.tender_prices')
                    + pg_total_relation_size('ods.tender_cards')
                    + pg_total_relation_size('ods.tender_industries')
                """
            )
            return int(cur.fetchone()[0])


def _as_datetime(value: datetime | str | None) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _as_date(value: date | datetime | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _default_ddl() -> str:
    sql_path = Path(__file__).resolve().parents[2] / "sql" / "init_ods.sql"
    return sql_path.read_text(encoding="utf-8")
