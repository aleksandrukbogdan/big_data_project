from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from src.etl_tasks import extract_raw, load_geo_prices_to_postgres, transform_geo_prices

DEFAULT_ARGS = {
    "owner": "tender_screening",
    "retries": 2,
    "retry_delay": timedelta(minutes=3),
}


def _extract(**context) -> dict:
    payloads = extract_raw()
    context["ti"].xcom_push(key="payloads", value=payloads)
    return {"files": list(payloads)}


def _transform(**context) -> dict:
    payloads = context["ti"].xcom_pull(task_ids="extract", key="payloads")
    payload = transform_geo_prices(payloads)
    context["ti"].xcom_push(key="geo_prices", value=payload)
    return {
        "locations": len(payload["locations"]),
        "prices": len(payload["prices"]),
    }


def _load(**context) -> dict:
    payload = context["ti"].xcom_pull(task_ids="transform", key="geo_prices")
    return load_geo_prices_to_postgres(payload or {"locations": [], "prices": []})


with DAG(
    dag_id="ods_geo_prices_to_postgres",
    description="ODS: места поставки и цены тендеров в PostgreSQL",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule="@hourly",
    catchup=False,
    max_active_runs=1,
    tags=["ods", "postgres", "tenders"],
) as dag:
    extract = PythonOperator(task_id="extract", python_callable=_extract)
    transform = PythonOperator(task_id="transform", python_callable=_transform)
    load = PythonOperator(task_id="load", python_callable=_load)
    extract >> transform >> load
