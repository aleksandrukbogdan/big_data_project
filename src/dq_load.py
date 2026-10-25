from __future__ import annotations

from typing import Any

import psycopg2

from src.loaders.settings import postgres_dsn


def run_dq(dsn: str | None = None) -> dict[str, Any]:
    conn = psycopg2.connect(dsn or postgres_dsn())
    try:
        checks = _collect(conn)
        _store(conn, checks)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    failed = [item for item in checks if item["severity"] == "error" and not item["passed"]]
    if failed:
        names = ", ".join(item["check_name"] for item in failed)
        raise RuntimeError(f"Data quality failed: {names}")
    return {
        "checks": len(checks),
        "warnings": sum(1 for item in checks if item["severity"] == "warning" and not item["passed"]),
        "errors": len(failed),
    }


def _collect(conn) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM ods.tender_locations),
                (SELECT COUNT(*) FROM dds.fact_tender),
                (SELECT COUNT(*) FROM dds.dim_tender WHERE is_current),
                (SELECT COUNT(*) FROM (
                    SELECT tender_id FROM dds.dim_tender WHERE is_current GROUP BY tender_id HAVING COUNT(*) > 1
                ) dup),
                (SELECT COUNT(*) FROM ods.tender_industries),
                (SELECT COUNT(*) FROM dds.bridge_tender_industry b
                    JOIN dds.dim_tender d ON d.tender_sk = b.tender_sk AND d.is_current),
                (SELECT COUNT(*) FROM dds.fact_tender WHERE nmck_rub IS NOT NULL AND nmck_rub <= 0),
                (SELECT COUNT(*) FROM dds.fact_tender WHERE application_hours IS NOT NULL AND application_hours < 0),
                (SELECT COUNT(*) FROM ods.tender_cards),
                (SELECT COUNT(*) FROM dds.fact_tender f
                    JOIN dds.dim_tender d ON d.tender_sk = f.tender_sk
                    WHERE d.status IS NOT NULL),
                (SELECT COUNT(*) FROM ods.tender_prices WHERE price_rub IS NULL OR price_rub <= 0),
                (SELECT COUNT(*) FROM ods.tender_cards WHERE nmck_rub IS NULL),
                (SELECT COUNT(*) FROM ods.tender_locations l
                    LEFT JOIN ods.tender_cards c USING (tender_id)
                    WHERE c.tender_id IS NULL),
                (SELECT COUNT(*) FROM dds.fact_tender f
                    JOIN dds.dim_region r USING (region_key)
                    WHERE r.region_title IS NULL OR btrim(r.region_title) = '')
            """
        )
        row = cur.fetchone()
    (
        locations,
        facts,
        current_versions,
        duplicate_current,
        ods_industries,
        bridge_current,
        bad_nmck,
        bad_hours,
        cards,
        facts_with_status,
        weak_prices,
        cards_without_nmck,
        locations_without_card,
        missing_region_title,
    ) = row
    return [
        _check(
            "fact_matches_locations",
            "error",
            facts == locations,
            str(facts),
            str(locations),
            "В факте одна строка на тендер из ods.tender_locations.",
        ),
        _check(
            "one_current_version",
            "error",
            duplicate_current == 0 and current_versions == facts,
            f"versions={current_versions}, duplicates={duplicate_current}",
            f"versions={facts}, duplicates=0",
            "У тендера одна открытая версия измерения.",
        ),
        _check(
            "bridge_matches_industries",
            "error",
            bridge_current == ods_industries,
            str(bridge_current),
            str(ods_industries),
            "Мост отраслей совпадает с ODS.",
        ),
        _check(
            "no_nonpositive_nmck_in_fact",
            "error",
            bad_nmck == 0,
            str(bad_nmck),
            "0",
            "Нулевая и отрицательная НМЦ в факт не попадает.",
        ),
        _check(
            "no_negative_application_hours",
            "error",
            bad_hours == 0,
            str(bad_hours),
            "0",
            "Окно подачи не заканчивается раньше начала.",
        ),
        _check(
            "cards_keep_status",
            "error",
            facts_with_status == cards,
            str(facts_with_status),
            str(cards),
            "У каждой разобранной карточки статус доезжает до факта.",
        ),
        _check(
            "ods_price_missing_or_zero",
            "warning",
            weak_prices == 0,
            str(weak_prices),
            "0",
            "В сыром слое есть пустая или нулевая цена. В факте такие суммы обнуляются.",
        ),
        _check(
            "card_without_nmck",
            "warning",
            cards_without_nmck == 0,
            str(cards_without_nmck),
            "0",
            "На части карточек начальная цена не указана, на сайте стоит прочерк.",
        ),
        _check(
            "location_without_card",
            "info",
            True,
            str(locations_without_card),
            "допустимо",
            "Старые строки ленты без повторного чтения карточки остаются в факте с пустым статусом.",
        ),
        _check(
            "region_title_filled",
            "error",
            missing_region_title == 0,
            str(missing_region_title),
            "0",
            "У каждого факта есть русское имя региона для витрин.",
        ),
    ]


def _check(
    name: str,
    severity: str,
    passed: bool,
    observed: str,
    expected: str,
    details: str,
) -> dict[str, Any]:
    return {
        "check_name": name,
        "severity": severity,
        "passed": passed,
        "observed": observed,
        "expected": expected,
        "details": details,
    }


def _store(conn, checks: list[dict[str, Any]]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO dds.dq_result (check_name, severity, passed, observed, expected, details)
            VALUES (%(check_name)s, %(severity)s, %(passed)s, %(observed)s, %(expected)s, %(details)s)
            """,
            checks,
        )
