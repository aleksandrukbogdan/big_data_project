from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.etl import (
    attributes_from_tenders,
    fetch_raw_sources,
    load_etl_config,
    parse_tenders_from_raw,
)
from src.loaders.minio_loader import MinioLoader, raw_object_prefix
from src.loaders.mongo_loader import MongoLoader
from src.loaders.postgres_loader import PostgresLoader
from src.models import Tender


def _config():
    return load_etl_config()


def extract_raw() -> dict[str, str]:
    return fetch_raw_sources(_config())


def transform_raw_metadata(payloads: dict[str, str]) -> dict[str, Any]:
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            name: {"bytes": len(content.encode("utf-8")), "chars": len(content)}
            for name, content in payloads.items()
        },
    }


def load_raw_to_minio(
    payloads: dict[str, str],
    *,
    logical_date: datetime,
    run_id: str,
) -> dict[str, Any]:
    loader = MinioLoader()
    prefix = raw_object_prefix(logical_date, run_id)
    content_types = {
        "rss.xml": "application/xml; charset=utf-8",
        "category.html": "text/html; charset=utf-8",
    }
    objects = {
        name: loader.put_text(
            f"{prefix}{name}",
            content,
            content_types.get(name, "text/plain; charset=utf-8"),
        )
        for name, content in payloads.items()
    }
    return {"prefix": prefix, "objects": objects}


def transform_tenders(payloads: dict[str, str]) -> list[dict[str, Any]]:
    tenders = parse_tenders_from_raw(payloads)
    return [tender.to_dict() for tender in tenders]


def load_tenders_to_mongo(records: list[dict[str, Any]]) -> dict[str, Any]:
    tenders = [
        Tender(
            id=str(item["id"]),
            title=item.get("title") or "",
            description=item.get("description") or "",
            url=item.get("url") or "",
            published=_parse_iso(item.get("published")),
            matched_keywords=tuple(item.get("matched_keywords") or ()),
            source=item.get("source") or "rss",
        )
        for item in records
    ]
    with MongoLoader() as loader:
        written = loader.upsert_tenders(tenders)
        return {"upserted": written, "count": loader.count()}


def transform_geo_prices(payloads: dict[str, str]) -> dict[str, list[dict[str, Any]]]:
    tenders = parse_tenders_from_raw(payloads)
    attrs = attributes_from_tenders(tenders)
    return {
        "locations": [item.location_record() for item in attrs],
        "prices": [item.price_record() for item in attrs],
    }


def load_geo_prices_to_postgres(payload: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    with PostgresLoader() as loader:
        loader.ensure_schema()
        n_loc, n_price = loader.upsert_records(payload["locations"], payload["prices"])
        return {
            "locations": n_loc,
            "prices": n_price,
            "location_rows": loader.count_locations(),
            "price_rows": loader.count_prices(),
        }


def _parse_iso(value: str | None):
    if not value:
        return None
    return datetime.fromisoformat(value)
