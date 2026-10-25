from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg2

from src.loaders.settings import postgres_dsn

DDL_PATH = Path(__file__).resolve().parents[1] / "sql" / "init_dm.sql"


def load_marts(dsn: str | None = None) -> dict[str, Any]:
    conn = psycopg2.connect(dsn or postgres_dsn())
    try:
        with conn.cursor() as cur:
            cur.execute(DDL_PATH.read_text(encoding="utf-8"))
            counts = {
                "regions": _reload(cur, "dm.mart_region", _SQL_REGION),
                "procedures": _reload(cur, "dm.mart_procedure", _SQL_PROCEDURE),
                "weeks": _reload(cur, "dm.mart_week", _SQL_WEEK),
                "industries": _reload(cur, "dm.mart_industry", _SQL_INDUSTRY),
                "price_states": _reload(cur, "dm.mart_price_coverage", _SQL_PRICE),
            }
        conn.commit()
        return counts
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _reload(cur, table: str, select_sql: str) -> int:
    cur.execute(f"TRUNCATE {table}")
    cur.execute(f"INSERT INTO {table} {select_sql}")
    return cur.rowcount


_SQL_REGION = """
SELECT
    region_title,
    COUNT(*)::integer,
    COUNT(nmck_rub)::integer,
    COALESCE(SUM(nmck_rub), 0),
    AVG(nmck_rub)
FROM dds.v_tender
GROUP BY region_title
"""

_SQL_PROCEDURE = """
SELECT
    procedure_group,
    COUNT(*)::integer,
    COUNT(nmck_rub)::integer,
    COALESCE(SUM(nmck_rub), 0),
    AVG(nmck_rub)
FROM dds.v_tender
GROUP BY procedure_group
"""

_SQL_WEEK = """
SELECT
    application_end_week,
    COUNT(*)::integer,
    COALESCE(SUM(nmck_rub), 0)
FROM dds.v_tender
WHERE application_end_week IS NOT NULL
GROUP BY application_end_week
"""

_SQL_INDUSTRY = """
SELECT industry_name, COUNT(*)::integer
FROM dds.v_tender_industry
GROUP BY industry_name
"""

_SQL_PRICE = """
SELECT
    CASE
        WHEN nmck_rub IS NULL THEN 'Нет начальной цены'
        ELSE 'Начальная цена указана'
    END,
    COUNT(*)::integer
FROM dds.v_tender
WHERE has_card
GROUP BY 1
"""
