"""Кладёт в OpenMetadata таблицы слоёв ods, dds и dm и связи между ними."""

from __future__ import annotations

import base64
import os

import httpx

BASE = os.environ.get("OPENMETADATA_URL", "http://localhost:8585")
SERVICE = "tender-postgres"
DATABASE = "ods"

TABLES = {
    "ods": {
        "tender_locations": ["tender_id", "city", "region"],
        "tender_prices": ["tender_id", "price_rub", "price_kind"],
        "tender_cards": ["tender_id", "status", "procedure_group", "nmck_rub"],
        "tender_industries": ["tender_id", "industry"],
    },
    "dds": {
        "dim_tender": ["tender_sk", "tender_id", "status"],
        "dim_region": ["region_key", "region_title"],
        "fact_tender": ["tender_id", "nmck_rub", "application_hours"],
        "bridge_tender_industry": ["tender_sk", "industry_key"],
    },
    "dm": {
        "mart_region": ["region_title", "tender_count", "nmck_sum"],
        "mart_procedure": ["procedure_group", "tender_count", "nmck_sum"],
        "mart_week": ["week_start", "tender_count", "nmck_sum"],
        "mart_industry": ["industry_name", "tender_count"],
        "mart_price_coverage": ["price_state", "tender_count"],
    },
}

EDGES = [
    ("ods", "tender_locations", "dds", "fact_tender", "Город и регион из сырого слоя"),
    ("ods", "tender_prices", "dds", "fact_tender", "Начальная цена, нули отброшены"),
    ("ods", "tender_cards", "dds", "fact_tender", "Статус, процедура и сроки карточки"),
    ("ods", "tender_cards", "dds", "dim_tender", "Медленно меняющееся измерение тендера"),
    ("ods", "tender_industries", "dds", "bridge_tender_industry", "Отрасли карточки"),
    ("dds", "dim_region", "dds", "fact_tender", "Регион факта"),
    ("dds", "fact_tender", "dm", "mart_region", "Срез по регионам"),
    ("dds", "fact_tender", "dm", "mart_procedure", "Срез по процедурам"),
    ("dds", "fact_tender", "dm", "mart_week", "Срез по неделям окончания приёма"),
    ("dds", "fact_tender", "dm", "mart_price_coverage", "Доля карточек с начальной ценой"),
    ("dds", "bridge_tender_industry", "dm", "mart_industry", "Срез по отраслям"),
]


def main() -> None:
    headers = login()
    with httpx.Client(base_url=BASE, timeout=60, headers=headers) as client:
        ensure_service(client)
        ensure_database(client)
        ids: dict[tuple[str, str], str] = {}
        for schema, tables in TABLES.items():
            ensure_schema(client, schema)
            for name, columns in tables.items():
                ids[(schema, name)] = ensure_table(client, schema, name, columns)
        for source_schema, source, target_schema, target, description in EDGES:
            add_lineage(
                client,
                ids[(source_schema, source)],
                ids[(target_schema, target)],
                description,
            )
    print(f"Линия данных: {BASE}/lineage")


def login() -> dict[str, str]:
    password = base64.b64encode(b"admin").decode()
    response = httpx.post(
        f"{BASE}/api/v1/users/login",
        json={"email": "admin@open-metadata.org", "password": password},
        timeout=30,
    )
    response.raise_for_status()
    token = response.json()["accessToken"]
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def ensure_service(client: httpx.Client) -> None:
    found = client.get(f"/api/v1/services/databaseServices/name/{SERVICE}")
    if found.status_code == 200:
        return
    response = client.put(
        "/api/v1/services/databaseServices",
        json={
            "name": SERVICE,
            "serviceType": "Postgres",
            "connection": {
                "config": {
                    "type": "Postgres",
                    "username": "ods",
                    "authType": {"password": "ods"},
                    "hostPort": "postgres-ods:5432",
                    "database": DATABASE,
                }
            },
        },
    )
    response.raise_for_status()


def ensure_database(client: httpx.Client) -> None:
    name = f"{SERVICE}.{DATABASE}"
    if client.get(f"/api/v1/databases/name/{name}").status_code == 200:
        return
    response = client.put(
        "/api/v1/databases",
        json={"name": DATABASE, "service": SERVICE},
    )
    response.raise_for_status()


def ensure_schema(client: httpx.Client, schema: str) -> None:
    name = f"{SERVICE}.{DATABASE}.{schema}"
    if client.get(f"/api/v1/databaseSchemas/name/{name}").status_code == 200:
        return
    response = client.put(
        "/api/v1/databaseSchemas",
        json={"name": schema, "database": f"{SERVICE}.{DATABASE}"},
    )
    response.raise_for_status()


def ensure_table(client: httpx.Client, schema: str, table: str, columns: list[str]) -> str:
    name = f"{SERVICE}.{DATABASE}.{schema}.{table}"
    found = client.get(f"/api/v1/tables/name/{name}")
    if found.status_code == 200:
        return found.json()["id"]
    response = client.put(
        "/api/v1/tables",
        json={
            "name": table,
            "databaseSchema": f"{SERVICE}.{DATABASE}.{schema}",
            "columns": [{"name": column, "dataType": "VARCHAR", "dataLength": 1} for column in columns],
        },
    )
    response.raise_for_status()
    return response.json()["id"]


def add_lineage(client: httpx.Client, source_id: str, target_id: str, description: str) -> None:
    response = client.put(
        "/api/v1/lineage",
        json={
            "edge": {
                "fromEntity": {"id": source_id, "type": "table"},
                "toEntity": {"id": target_id, "type": "table"},
                "lineageDetails": {"description": description, "source": "Manual"},
            }
        },
    )
    response.raise_for_status()


if __name__ == "__main__":
    main()
