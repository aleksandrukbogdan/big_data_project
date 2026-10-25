"""Создаёт в Superset подключение, пять графиков и дашборд IT-тендеров."""

from __future__ import annotations

import json
import os
import time

import httpx

BASE = os.environ.get("SUPERSET_URL", "http://localhost:8088")
USERNAME = os.environ.get("SUPERSET_USERNAME", "admin")
PASSWORD = os.environ.get("SUPERSET_PASSWORD", "admin")
DATABASE_NAME = "IT-тендеры"
DASHBOARD_TITLE = "IT-тендеры"
URI = os.environ.get(
    "SUPERSET_DATA_URI",
    "postgresql+psycopg2://ods:ods@postgres-ods:5432/ods",
)


def main() -> None:
    wait_until_ready()
    client, headers = login()
    if dashboard_exists(client, headers):
        print(f"Дашборд «{DASHBOARD_TITLE}» уже есть: {BASE}/superset/dashboard/")
        return
    database_id = create_database(client, headers)
    datasets = {
        "mart_region": create_dataset(client, headers, database_id, "mart_region"),
        "mart_procedure": create_dataset(client, headers, database_id, "mart_procedure"),
        "mart_week": create_dataset(client, headers, database_id, "mart_week"),
        "mart_industry": create_dataset(client, headers, database_id, "mart_industry"),
        "mart_price_coverage": create_dataset(client, headers, database_id, "mart_price_coverage"),
    }
    dashboard_id = create_dashboard(client, headers)
    charts = [
        chart_bar(
            client,
            headers,
            datasets["mart_region"],
            "Закупки по регионам",
            "region_title",
            "tender_count",
            "Число закупок",
            dashboard_id,
        ),
        chart_bar(
            client,
            headers,
            datasets["mart_procedure"],
            "Сумма НМЦ по процедуре",
            "procedure_group",
            "nmck_sum",
            "Сумма НМЦ",
            dashboard_id,
        ),
        chart_line(client, headers, datasets["mart_week"], dashboard_id),
        chart_bar(
            client,
            headers,
            datasets["mart_industry"],
            "Отрасли закупок",
            "industry_name",
            "tender_count",
            "Число закупок",
            dashboard_id,
        ),
        chart_pie(client, headers, datasets["mart_price_coverage"], dashboard_id),
    ]
    place_charts(client, headers, dashboard_id, charts)
    print(f"Дашборд: {BASE}/superset/dashboard/{dashboard_id}/")


def wait_until_ready() -> None:
    deadline = time.time() + 180
    while time.time() < deadline:
        try:
            response = httpx.get(f"{BASE}/health", timeout=5)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(3)
    raise RuntimeError(f"Superset не ответил: {BASE}/health")


def login() -> tuple[httpx.Client, dict[str, str]]:
    client = httpx.Client(base_url=BASE, timeout=60)
    response = client.post(
        "/api/v1/security/login",
        json={"username": USERNAME, "password": PASSWORD, "provider": "db", "refresh": True},
    )
    response.raise_for_status()
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    csrf = client.get("/api/v1/security/csrf_token/", headers=headers)
    csrf.raise_for_status()
    headers["X-CSRFToken"] = csrf.json()["result"]
    headers["Referer"] = BASE
    return client, headers


def dashboard_exists(client: httpx.Client, headers: dict[str, str]) -> bool:
    response = client.get("/api/v1/dashboard/", headers=headers, params={"page_size": 100})
    response.raise_for_status()
    return any(item["dashboard_title"] == DASHBOARD_TITLE for item in response.json().get("result", []))


def create_database(client: httpx.Client, headers: dict[str, str]) -> int:
    response = client.post(
        "/api/v1/database/",
        headers=headers,
        json={
            "database_name": DATABASE_NAME,
            "sqlalchemy_uri": URI,
            "expose_in_sqllab": True,
            "allow_run_async": False,
        },
    )
    if response.status_code >= 400:
        raise RuntimeError(f"База Superset: {response.status_code} {response.text}")
    return int(response.json()["id"])


def create_dataset(client: httpx.Client, headers: dict[str, str], database_id: int, table: str) -> int:
    response = client.post(
        "/api/v1/dataset/",
        headers=headers,
        json={"database": database_id, "schema": "dm", "table_name": table},
    )
    response.raise_for_status()
    return int(response.json()["id"])


def create_dashboard(client: httpx.Client, headers: dict[str, str]) -> int:
    response = client.post(
        "/api/v1/dashboard/",
        headers=headers,
        json={"dashboard_title": DASHBOARD_TITLE, "published": True},
    )
    response.raise_for_status()
    return int(response.json()["id"])


def metric(column: str, label: str) -> dict:
    return {
        "expressionType": "SIMPLE",
        "column": {"column_name": column},
        "aggregate": "SUM",
        "label": label,
    }


def save_chart(
    client: httpx.Client,
    headers: dict[str, str],
    name: str,
    viz_type: str,
    dataset_id: int,
    form_data: dict,
    dashboard_id: int,
) -> dict:
    form_data = {
        "datasource": f"{dataset_id}__table",
        "viz_type": viz_type,
        **form_data,
    }
    response = client.post(
        "/api/v1/chart/",
        headers=headers,
        json={
            "slice_name": name,
            "viz_type": viz_type,
            "datasource_id": dataset_id,
            "datasource_type": "table",
            "dashboards": [dashboard_id],
            "params": json.dumps(form_data, ensure_ascii=False),
        },
    )
    if response.status_code >= 400:
        raise RuntimeError(f"{name}: {response.status_code} {response.text}")
    body = response.json()
    return {"id": int(body["id"]), "name": name}


def chart_bar(client, headers, dataset_id, name, x_axis, column, label, dashboard_id) -> dict:
    return save_chart(
        client,
        headers,
        name,
        "echarts_timeseries_bar",
        dataset_id,
        {
            "x_axis": x_axis,
            "metrics": [metric(column, label)],
            "groupby": [],
            "row_limit": 12,
            "order_desc": True,
            "truncate_metric": True,
            "show_legend": False,
        },
        dashboard_id,
    )


def chart_line(client, headers, dataset_id, dashboard_id) -> dict:
    return save_chart(
        client,
        headers,
        "Окончание приёма заявок по неделям",
        "echarts_timeseries_line",
        dataset_id,
        {
            "x_axis": "week_start",
            "metrics": [metric("tender_count", "Число закупок")],
            "groupby": [],
            "row_limit": 100,
            "show_legend": False,
        },
        dashboard_id,
    )


def chart_pie(client, headers, dataset_id, dashboard_id) -> dict:
    return save_chart(
        client,
        headers,
        "Есть ли начальная цена",
        "pie",
        dataset_id,
        {
            "groupby": ["price_state"],
            "metric": metric("tender_count", "Число закупок"),
            "row_limit": 10,
            "show_labels": True,
            "show_legend": True,
        },
        dashboard_id,
    )


def place_charts(client, headers, dashboard_id: int, charts: list[dict]) -> None:
    position: dict = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": [], "parents": ["ROOT_ID"]},
    }
    rows = [charts[0:2], charts[2:4], charts[4:5]]
    for row_index, row in enumerate(rows):
        row_id = f"ROW-{row_index}"
        position["GRID_ID"]["children"].append(row_id)
        position[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
        for chart in row:
            node_id = f"CHART-{chart['id']}"
            position[row_id]["children"].append(node_id)
            position[node_id] = {
                "type": "CHART",
                "id": node_id,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {
                    "chartId": chart["id"],
                    "width": 6 if len(row) > 1 else 12,
                    "height": 50,
                    "sliceName": chart["name"],
                },
            }
    response = client.put(
        f"/api/v1/dashboard/{dashboard_id}",
        headers=headers,
        json={
            "position_json": json.dumps(position),
            "json_metadata": json.dumps({"chart_configuration": {}, "native_filter_configuration": []}),
        },
    )
    response.raise_for_status()


if __name__ == "__main__":
    main()
