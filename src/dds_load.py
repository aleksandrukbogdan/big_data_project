from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg2

from src.geo_titles import CITY_TITLES, REGION_TITLES
from src.loaders.settings import postgres_dsn

DDL_PATH = Path(__file__).resolve().parents[1] / "sql" / "init_dds.sql"

MONTHS = (
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
)


def load_dds(dsn: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    result.update(clean_stage(dsn))
    result.update(conform_dimensions(dsn))
    result.update(apply_scd(dsn))
    result.update(load_facts(dsn))
    result.update(load_aggregates(dsn))
    return result


def clean_stage(dsn: str | None = None) -> dict[str, Any]:
    def work(cur) -> dict[str, Any]:
        _stage(cur)
        cur.execute("SELECT COUNT(*) FROM dds.stg_tender")
        staged = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM dds.stg_industry")
        industries = int(cur.fetchone()[0])
        return {"staged": staged, "staged_industries": industries}

    return _transaction(work, dsn)


def conform_dimensions(dsn: str | None = None) -> dict[str, Any]:
    def work(cur) -> dict[str, Any]:
        _dimensions(cur)
        cur.execute("SELECT COUNT(*) FROM dds.dim_region WHERE region_title IS NOT NULL")
        titled = int(cur.fetchone()[0])
        return {"regions_with_title": titled}

    return _transaction(work, dsn)


def apply_scd(dsn: str | None = None) -> dict[str, Any]:
    def work(cur) -> dict[str, Any]:
        return {
            "versions_closed": _close_changed_tenders(cur),
            "versions_opened": _open_tender_versions(cur),
        }

    return _transaction(work, dsn)


def load_facts(dsn: str | None = None) -> dict[str, Any]:
    def work(cur) -> dict[str, Any]:
        return {
            "facts": _upsert_facts(cur),
            "industries": _refresh_bridge(cur),
        }

    return _transaction(work, dsn)


def load_aggregates(dsn: str | None = None) -> dict[str, Any]:
    def work(cur) -> dict[str, Any]:
        return {"agg_rows": _refresh_aggregate(cur)}

    return _transaction(work, dsn)


def _transaction(work, dsn: str | None) -> dict[str, Any]:
    conn = psycopg2.connect(dsn or postgres_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(DDL_PATH.read_text(encoding="utf-8"))
            result = work(cur)
        conn.commit()
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _stage(cur) -> None:
    cur.execute(
        r"""
        DROP TABLE IF EXISTS dds.stg_industry;
        DROP TABLE IF EXISTS dds.stg_tender;
        CREATE TABLE dds.stg_tender AS
        SELECT DISTINCT ON (l.tender_id)
            l.tender_id,
            COALESCE(
                NULLIF(regexp_replace(btrim(l.region), '\s+', ' ', 'g'), ''),
                'Не указан'
            ) AS region_name,
            COALESCE(
                NULLIF(
                    regexp_replace(
                        regexp_replace(btrim(l.city), '^(г\.|город)\s*', '', 'i'),
                        '\s+',
                        ' ',
                        'g'
                    ),
                    ''
                ),
                'Не указан'
            ) AS city_name,
            COALESCE(c.url, l.url) AS url,
            NULLIF(btrim(c.status), '') AS status,
            (c.tender_id IS NOT NULL) AS has_card,
            COALESCE(NULLIF(btrim(c.procedure_group), ''), 'Не указано') AS procedure_group,
            COALESCE(NULLIF(btrim(c.procedure_name), ''), '') AS procedure_name,
            CASE
                WHEN c.nmck_rub IS NOT NULL AND c.nmck_rub > 0 THEN c.nmck_rub
                WHEN p.price_rub IS NOT NULL AND p.price_rub > 0 THEN p.price_rub
                ELSE NULL
            END AS nmck_rub,
            c.application_start,
            c.application_end,
            c.contract_date,
            CASE
                WHEN c.application_start IS NOT NULL
                 AND c.application_end IS NOT NULL
                 AND c.application_end >= c.application_start
                THEN ROUND(
                    (EXTRACT(EPOCH FROM (c.application_end - c.application_start)) / 3600.0)::numeric,
                    2
                )
                ELSE NULL
            END AS application_hours,
            CASE
                WHEN c.contract_date IS NOT NULL AND c.application_end IS NOT NULL
                THEN c.contract_date - (c.application_end AT TIME ZONE 'Europe/Moscow')::date
                ELSE NULL
            END AS days_to_contract,
            (c.application_start AT TIME ZONE 'Europe/Moscow')::date AS application_start_date,
            (c.application_end AT TIME ZONE 'Europe/Moscow')::date AS application_end_date
        FROM ods.tender_locations l
        LEFT JOIN ods.tender_cards c USING (tender_id)
        LEFT JOIN ods.tender_prices p USING (tender_id)
        ORDER BY l.tender_id
        """
    )
    cur.execute(
        """
        CREATE TABLE dds.stg_industry AS
        SELECT DISTINCT i.tender_id, btrim(i.industry) AS industry_name
        FROM ods.tender_industries i
        JOIN dds.stg_tender s USING (tender_id)
        WHERE btrim(i.industry) <> ''
        """
    )


def _dimensions(cur) -> None:
    cur.execute(
        """
        INSERT INTO dds.dim_date (
            date_key, full_date, year, quarter, month, day, month_name, week_start
        )
        SELECT DISTINCT
            to_char(d, 'YYYYMMDD')::integer,
            d,
            EXTRACT(YEAR FROM d)::smallint,
            EXTRACT(QUARTER FROM d)::smallint,
            EXTRACT(MONTH FROM d)::smallint,
            EXTRACT(DAY FROM d)::smallint,
            (%s::text[])[EXTRACT(MONTH FROM d)::integer],
            d - (EXTRACT(ISODOW FROM d)::integer - 1)
        FROM (
            SELECT application_start_date AS d FROM dds.stg_tender
            UNION
            SELECT application_end_date FROM dds.stg_tender
            UNION
            SELECT contract_date FROM dds.stg_tender
        ) days
        WHERE d IS NOT NULL
        ON CONFLICT (date_key) DO NOTHING
        """,
        (list(MONTHS),),
    )
    cur.execute(
        """
        INSERT INTO dds.dim_region (region_name)
        SELECT DISTINCT region_name FROM dds.stg_tender
        ON CONFLICT (region_name) DO NOTHING
        """
    )
    cur.execute(
        """
        INSERT INTO dds.dim_city (region_key, city_name)
        SELECT DISTINCT r.region_key, s.city_name
        FROM dds.stg_tender s
        JOIN dds.dim_region r ON r.region_name = s.region_name
        ON CONFLICT (region_key, city_name) DO NOTHING
        """
    )
    cur.execute(
        """
        INSERT INTO dds.dim_procedure (procedure_group, procedure_name)
        SELECT DISTINCT procedure_group, procedure_name FROM dds.stg_tender
        ON CONFLICT (procedure_group, procedure_name) DO NOTHING
        """
    )
    cur.execute(
        """
        INSERT INTO dds.dim_industry (industry_name)
        SELECT DISTINCT industry_name FROM dds.stg_industry
        ON CONFLICT (industry_name) DO NOTHING
        """
    )
    _fill_calendar(cur)
    _apply_titles(cur)


def _close_changed_tenders(cur) -> int:
    cur.execute(
        """
        UPDATE dds.dim_tender d
        SET is_current = FALSE,
            valid_to = NOW()
        FROM dds.stg_tender s
        WHERE d.tender_id = s.tender_id
          AND d.is_current
          AND (
                d.status IS DISTINCT FROM s.status
             OR d.procedure_group IS DISTINCT FROM s.procedure_group
             OR d.procedure_name IS DISTINCT FROM s.procedure_name
             OR d.url IS DISTINCT FROM s.url
          )
        """
    )
    return cur.rowcount


def _open_tender_versions(cur) -> int:
    cur.execute(
        """
        INSERT INTO dds.dim_tender (
            tender_id, url, status, procedure_group, procedure_name, valid_from, is_current
        )
        SELECT s.tender_id, s.url, s.status, s.procedure_group, s.procedure_name, NOW(), TRUE
        FROM dds.stg_tender s
        WHERE NOT EXISTS (
            SELECT 1
            FROM dds.dim_tender d
            WHERE d.tender_id = s.tender_id
              AND d.is_current
        )
        """
    )
    return cur.rowcount


def _upsert_facts(cur) -> int:
    cur.execute(
        """
        INSERT INTO dds.fact_tender (
            tender_id, tender_sk, region_key, city_key, procedure_key,
            application_start_date_key, application_end_date_key, contract_date_key,
            nmck_rub, application_hours, days_to_contract, industry_count, has_card, loaded_at
        )
        SELECT
            s.tender_id,
            d.tender_sk,
            r.region_key,
            city.city_key,
            proc.procedure_key,
            dstart.date_key,
            dend.date_key,
            dcon.date_key,
            s.nmck_rub,
            s.application_hours,
            s.days_to_contract,
            COALESCE(ind.industry_count, 0),
            s.has_card,
            NOW()
        FROM dds.stg_tender s
        JOIN dds.dim_tender d
          ON d.tender_id = s.tender_id AND d.is_current
        JOIN dds.dim_region r ON r.region_name = s.region_name
        JOIN dds.dim_city city
          ON city.region_key = r.region_key AND city.city_name = s.city_name
        JOIN dds.dim_procedure proc
          ON proc.procedure_group = s.procedure_group
         AND proc.procedure_name = s.procedure_name
        LEFT JOIN dds.dim_date dstart ON dstart.full_date = s.application_start_date
        LEFT JOIN dds.dim_date dend ON dend.full_date = s.application_end_date
        LEFT JOIN dds.dim_date dcon ON dcon.full_date = s.contract_date
        LEFT JOIN (
            SELECT tender_id, COUNT(*)::integer AS industry_count
            FROM dds.stg_industry
            GROUP BY tender_id
        ) ind ON ind.tender_id = s.tender_id
        ON CONFLICT (tender_id) DO UPDATE SET
            tender_sk = EXCLUDED.tender_sk,
            region_key = EXCLUDED.region_key,
            city_key = EXCLUDED.city_key,
            procedure_key = EXCLUDED.procedure_key,
            application_start_date_key = EXCLUDED.application_start_date_key,
            application_end_date_key = EXCLUDED.application_end_date_key,
            contract_date_key = EXCLUDED.contract_date_key,
            nmck_rub = EXCLUDED.nmck_rub,
            application_hours = EXCLUDED.application_hours,
            days_to_contract = EXCLUDED.days_to_contract,
            industry_count = EXCLUDED.industry_count,
            has_card = EXCLUDED.has_card,
            loaded_at = NOW()
        """
    )
    return cur.rowcount


def _refresh_bridge(cur) -> int:
    cur.execute(
        """
        DELETE FROM dds.bridge_tender_industry b
        USING dds.dim_tender d
        WHERE b.tender_sk = d.tender_sk
          AND d.is_current
          AND d.tender_id IN (SELECT tender_id FROM dds.stg_tender)
        """
    )
    cur.execute(
        """
        INSERT INTO dds.bridge_tender_industry (tender_sk, industry_key)
        SELECT d.tender_sk, i.industry_key
        FROM dds.stg_industry s
        JOIN dds.dim_tender d
          ON d.tender_id = s.tender_id AND d.is_current
        JOIN dds.dim_industry i ON i.industry_name = s.industry_name
        """
    )
    return cur.rowcount


def _refresh_aggregate(cur) -> int:
    cur.execute("TRUNCATE dds.agg_region_procedure")
    cur.execute(
        """
        INSERT INTO dds.agg_region_procedure (
            region_key, procedure_key, tender_count, with_nmck_count, nmck_sum, nmck_avg
        )
        SELECT
            region_key,
            procedure_key,
            COUNT(*)::integer,
            COUNT(nmck_rub)::integer,
            COALESCE(SUM(nmck_rub), 0),
            AVG(nmck_rub)
        FROM dds.fact_tender
        GROUP BY region_key, procedure_key
        """
    )
    region_rows = cur.rowcount
    cur.execute("TRUNCATE dds.agg_deadline_week")
    cur.execute(
        """
        INSERT INTO dds.agg_deadline_week (week_start, tender_count, with_nmck_count, nmck_sum)
        SELECT
            d.week_start,
            COUNT(*)::integer,
            COUNT(f.nmck_rub)::integer,
            COALESCE(SUM(f.nmck_rub), 0)
        FROM dds.fact_tender f
        JOIN dds.dim_date d ON d.date_key = f.application_end_date_key
        WHERE d.week_start IS NOT NULL
        GROUP BY d.week_start
        """
    )
    return region_rows + cur.rowcount


def _fill_calendar(cur) -> None:
    cur.execute(
        """
        INSERT INTO dds.dim_date (
            date_key, full_date, year, quarter, month, day, month_name, week_start
        )
        SELECT
            to_char(day::date, 'YYYYMMDD')::integer,
            day::date,
            EXTRACT(YEAR FROM day)::smallint,
            EXTRACT(QUARTER FROM day)::smallint,
            EXTRACT(MONTH FROM day)::smallint,
            EXTRACT(DAY FROM day)::smallint,
            (%s::text[])[EXTRACT(MONTH FROM day)::integer],
            day::date - (EXTRACT(ISODOW FROM day)::integer - 1)
        FROM generate_series(
            (SELECT MIN(full_date) FROM dds.dim_date),
            (SELECT MAX(full_date) FROM dds.dim_date),
            INTERVAL '1 day'
        ) AS day
        ON CONFLICT (date_key) DO NOTHING
        """,
        (list(MONTHS),),
    )
    cur.execute(
        """
        UPDATE dds.dim_date
        SET week_start = full_date - (EXTRACT(ISODOW FROM full_date)::integer - 1)
        WHERE week_start IS NULL
        """
    )


def _apply_titles(cur) -> None:
    cur.execute("UPDATE dds.dim_region SET region_title = region_name")
    cur.execute(
        """
        UPDATE dds.dim_region AS region
        SET region_title = src.title
        FROM unnest(%s::text[], %s::text[]) AS src(name, title)
        WHERE region.region_name = src.name
        """,
        (list(REGION_TITLES), list(REGION_TITLES.values())),
    )
    cur.execute("UPDATE dds.dim_city SET city_title = city_name")
    cur.execute(
        """
        UPDATE dds.dim_city AS city
        SET city_title = src.title
        FROM unnest(%s::text[], %s::text[]) AS src(name, title)
        WHERE lower(city.city_name) = src.name
        """,
        (list(CITY_TITLES), list(CITY_TITLES.values())),
    )
