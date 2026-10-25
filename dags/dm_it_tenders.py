from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.datasets import Dataset
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor

from src.dm_load import load_marts

DDS_IT_TENDERS = Dataset("postgres://postgres-ods:5432/ods/dds/fact_tender")
DM_IT_TENDERS = Dataset("postgres://postgres-ods:5432/ods/dm/mart_region")

DEFAULT_ARGS = {
    "owner": "tender_screening",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
}


def _dds_ready() -> bool:
    from airflow.models.dagrun import DagRun
    from airflow.utils.session import create_session
    from airflow.utils.state import DagRunState

    with create_session() as session:
        run = (
            session.query(DagRun)
            .filter(
                DagRun.dag_id == "dds_it_tenders",
                DagRun.state == DagRunState.SUCCESS,
            )
            .order_by(DagRun.end_date.desc())
            .first()
        )
        return run is not None


with DAG(
    dag_id="dm_it_tenders",
    description="Витрины IT-тендеров для Superset: регион, процедура, недели, отрасли, покрытие цены",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule=[DDS_IT_TENDERS],
    catchup=False,
    max_active_runs=1,
    tags=["dm", "postgres", "tenders"],
) as dag:
    wait_dds = PythonSensor(
        task_id="wait_dds",
        python_callable=_dds_ready,
        mode="reschedule",
        poke_interval=30,
        timeout=60 * 60,
    )
    load = PythonOperator(
        task_id="load",
        python_callable=load_marts,
        outlets=[DM_IT_TENDERS],
    )
    wait_dds >> load
