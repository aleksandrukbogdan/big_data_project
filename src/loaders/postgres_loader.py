from __future__ import annotations

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
    tender_id, price_rub, price_raw, currency, url, source, loaded_at
)
VALUES %s
ON CONFLICT (tender_id) DO UPDATE SET
    price_rub = EXCLUDED.price_rub,
    price_raw = EXCLUDED.price_raw,
    currency = EXCLUDED.currency,
    url = EXCLUDED.url,
    source = EXCLUDED.source,
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
                    template="(%s, %s, %s, %s, %s, %s, NOW())",
                )
        self.conn.commit()
        return len(location_rows), len(price_rows)

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
                """
            )
            return int(cur.fetchone()[0])


def _default_ddl() -> str:
    return """
    CREATE SCHEMA IF NOT EXISTS ods;

    CREATE TABLE IF NOT EXISTS ods.tender_locations (
        id SERIAL PRIMARY KEY,
        tender_id TEXT NOT NULL UNIQUE,
        city TEXT,
        region TEXT,
        location_raw TEXT,
        url TEXT,
        source TEXT,
        loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );

    CREATE TABLE IF NOT EXISTS ods.tender_prices (
        id SERIAL PRIMARY KEY,
        tender_id TEXT NOT NULL UNIQUE,
        price_rub NUMERIC(18, 2),
        price_raw TEXT,
        currency TEXT NOT NULL DEFAULT 'RUB',
        url TEXT,
        source TEXT,
        loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    );
    """
