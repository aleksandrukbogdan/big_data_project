from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.datasets import Dataset
from airflow.operators.python import PythonOperator
from airflow.sensors.python import PythonSensor

from src.dq_load import run_dq

DDS_IT_TENDERS = Dataset("postgres://postgres-ods:5432/ods/dds/fact_tender")

DEFAULT_ARGS = {
    "owner": "tender_screening",
    "retries": 0,
    "retry_delay": timedelta(minutes=1),
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
    dag_id="dq_it_tenders",
    description="Проверки качества: объёмы ODS и DDS, пустая и нулевая НМЦ",
    default_args=DEFAULT_ARGS,
    start_date=datetime(2026, 1, 1),
    schedule=[DDS_IT_TENDERS],
    catchup=False,
    max_active_runs=1,
    tags=["dq", "postgres", "tenders"],
) as dag:
    wait_dds = PythonSensor(
        task_id="wait_dds",
        python_callable=_dds_ready,
        mode="reschedule",
        poke_interval=30,
        timeout=60 * 60,
    )
    check = PythonOperator(task_id="check", python_callable=run_dq)
    wait_dds >> check
