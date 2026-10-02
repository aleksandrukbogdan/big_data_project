from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import PythonOperator

from src.etl_tasks import extract_raw, load_raw_to_minio, transform_raw_metadata

DEFAULT_ARGS = {
    "owner": "tender_screening",
    "retries": 2,
    "retry_delay": timedelta(minutes=3),
}


def _extract(**context) -> dict[str, str]:
    payloads = extract_raw()
    context["ti"].xcom_push(key="payloads", value=payloads)
    return {"files": list(payloads)}


def _transform(**context) -> dict:
    payloads = context["ti"].xcom_pull(task_ids="extract", key="payloads")
    return transform_raw_metadata(payloads)


def _load(**context) -> dict:
    payloads = context["ti"].xcom_pull(task_ids="extract", key="payloads")
    logical_date = context.get("logical_date") or context["data_interval_start"]
    return load_raw_to_minio(
        payloads,
        logical_date=logical_date,
        run_id=context["run_id"],
    )


with DAG(
    dag_id="ods_raw_to_minio",
    description="ODS: сырой RSS XML и HTML категории rostender.info в MinIO",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule="@hourly",
    catchup=False,
    max_active_runs=1,
    tags=["ods", "minio", "tenders"],
) as dag:
    extract = PythonOperator(task_id="extract", python_callable=_extract)
    transform = PythonOperator(task_id="transform", python_callable=_transform)
    load = PythonOperator(task_id="load", python_callable=_load)
    extract >> transform >> load
