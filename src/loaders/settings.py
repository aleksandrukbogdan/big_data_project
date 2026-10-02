from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class MinioSettings:
    endpoint: str
    access_key: str
    secret_key: str
    bucket: str
    secure: bool


@dataclass(frozen=True)
class MongoSettings:
    uri: str
    database: str
    collection: str


def env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value == "" else value


def minio_settings() -> MinioSettings:
    return MinioSettings(
        endpoint=env("MINIO_ENDPOINT", "localhost:9000"),
        access_key=env("MINIO_ACCESS_KEY", "minioadmin"),
        secret_key=env("MINIO_SECRET_KEY", "minioadmin"),
        bucket=env("MINIO_BUCKET", "ods-tenders"),
        secure=env("MINIO_SECURE", "false").lower() == "true",
    )


def mongo_settings() -> MongoSettings:
    return MongoSettings(
        uri=env("MONGO_URI", "mongodb://ods:ods@localhost:27017/ods?authSource=admin"),
        database=env("MONGO_DB", "ods"),
        collection=env("MONGO_COLLECTION", "tenders"),
    )


def postgres_dsn() -> str:
    return env("POSTGRES_ODS_DSN", "postgresql://ods:ods@localhost:5433/ods")
