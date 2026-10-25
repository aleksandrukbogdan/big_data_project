from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.datasets import Dataset
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor

from src.dds_load import (
    apply_scd,
    clean_stage,
    conform_dimensions,
    load_aggregates,
    load_facts,
)

ODS_IT_TENDERS = Dataset("postgres://postgres-ods:5432/ods/ods/tender_cards")
DDS_IT_TENDERS = Dataset("postgres://postgres-ods:5432/ods/dds/fact_tender")

DEFAULT_ARGS = {
    "owner": "tender_screening",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}


def _ods_ready() -> bool:
    from airflow.models.dagrun import DagRun
    from airflow.utils.session import create_session
    from airflow.utils.state import DagRunState

    with create_session() as session:
        run = (
            session.query(DagRun)
            .filter(
                DagRun.dag_id == "ods_geo_prices_to_postgres",
                DagRun.state == DagRunState.SUCCESS,
            )
            .order_by(DagRun.end_date.desc())
            .first()
        )
        return run is not None


with DAG(
    dag_id="dds_it_tenders",
    description="DDS: снежинка IT-тендеров из PostgreSQL ODS",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule=[ODS_IT_TENDERS],
    catchup=False,
    max_active_runs=1,
    tags=["dds", "postgres", "tenders"],
) as dag:
    wait_ods = PythonSensor(
        task_id="wait_ods",
        python_callable=_ods_ready,
        mode="reschedule",
        poke_interval=30,
        timeout=60 * 60,
    )
    clean = PythonOperator(task_id="clean", python_callable=clean_stage)
    conform = PythonOperator(task_id="conform", python_callable=conform_dimensions)
    scd = PythonOperator(task_id="scd", python_callable=apply_scd)
    fact = PythonOperator(task_id="fact", python_callable=load_facts)
    aggregate = PythonOperator(
        task_id="aggregate",
        python_callable=load_aggregates,
        outlets=[DDS_IT_TENDERS],
    )
    wait_ods >> clean >> conform >> scd >> fact >> aggregate
