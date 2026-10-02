from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from minio import Minio
from minio.commonconfig import ENABLED
from minio.versioningconfig import VersioningConfig

from src.loaders.settings import MinioSettings, minio_settings


class MinioLoader:
    def __init__(self, settings: MinioSettings | None = None) -> None:
        self.settings = settings or minio_settings()
        self.client = Minio(
            self.settings.endpoint,
            access_key=self.settings.access_key,
            secret_key=self.settings.secret_key,
            secure=self.settings.secure,
        )

    def ensure_bucket(self) -> None:
        if not self.client.bucket_exists(self.settings.bucket):
            self.client.make_bucket(self.settings.bucket)
        try:
            self.client.set_bucket_versioning(
                self.settings.bucket,
                VersioningConfig(ENABLED),
            )
        except Exception:
            pass

    def put_text(
        self,
        object_name: str,
        content: str,
        content_type: str = "text/plain; charset=utf-8",
    ) -> str:
        self.ensure_bucket()
        payload = content.encode("utf-8")
        self.client.put_object(
            self.settings.bucket,
            object_name,
            BytesIO(payload),
            length=len(payload),
            content_type=content_type,
        )
        return f"s3://{self.settings.bucket}/{object_name}"

    def object_size(self, object_name: str) -> int:
        stat = self.client.stat_object(self.settings.bucket, object_name)
        return int(stat.size)

    def get_text(self, object_name: str) -> str:
        response = self.client.get_object(self.settings.bucket, object_name)
        try:
            return response.read().decode("utf-8")
        finally:
            response.close()
            response.release_conn()

    def list_prefix(self, prefix: str) -> list[str]:
        return [
            obj.object_name
            for obj in self.client.list_objects(
                self.settings.bucket,
                prefix=prefix,
                recursive=True,
            )
        ]


def raw_object_prefix(logical_date: datetime, run_id: str) -> str:
    ds = logical_date.astimezone(timezone.utc).strftime("%Y-%m-%d")
    return f"raw/dt={ds}/run_id={run_id}/"
