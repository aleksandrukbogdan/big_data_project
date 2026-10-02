from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from src.etl_tasks import extract_raw, load_tenders_to_mongo, transform_tenders

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
    records = transform_tenders(payloads)
    context["ti"].xcom_push(key="tenders", value=records)
    return {"tenders": len(records)}


def _load(**context) -> dict:
    records = context["ti"].xcom_pull(task_ids="transform", key="tenders")
    return load_tenders_to_mongo(records or [])


with DAG(
    dag_id="ods_tenders_to_mongo",
    description="ODS: карточки тендеров rostender.info в MongoDB",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule="@hourly",
    catchup=False,
    max_active_runs=1,
    tags=["ods", "mongodb", "tenders"],
) as dag:
    extract = PythonOperator(task_id="extract", python_callable=_extract)
    transform = PythonOperator(task_id="transform", python_callable=_transform)
    load = PythonOperator(task_id="load", python_callable=_load)
    extract >> transform >> load
