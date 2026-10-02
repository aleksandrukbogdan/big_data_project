from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from pymongo import MongoClient, ReplaceOne

from src.loaders.settings import MongoSettings, mongo_settings
from src.models import Tender


class MongoLoader:
    def __init__(self, settings: MongoSettings | None = None) -> None:
        self.settings = settings or mongo_settings()
        self.client = MongoClient(self.settings.uri)
        self.collection = self.client[self.settings.database][self.settings.collection]

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> MongoLoader:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def upsert_tenders(self, tenders: Iterable[Tender]) -> int:
        documents = [self._to_document(tender) for tender in tenders]
        if not documents:
            return 0
        operations = [
            ReplaceOne({"_id": doc["_id"]}, doc, upsert=True) for doc in documents
        ]
        result = self.collection.bulk_write(operations, ordered=False)
        return int(result.upserted_count + result.modified_count + result.matched_count)

    def find_by_id(self, tender_id: str) -> dict[str, Any] | None:
        return self.collection.find_one({"_id": tender_id})

    def count(self) -> int:
        return int(self.collection.estimated_document_count())

    def storage_size_bytes(self) -> int:
        stats = self.client[self.settings.database].command(
            "collStats",
            self.settings.collection,
        )
        return int(stats.get("size") or 0)

    @staticmethod
    def _to_document(tender: Tender) -> dict[str, Any]:
        payload = tender.to_dict()
        payload["_id"] = tender.id
        payload["loaded_at"] = datetime.now(timezone.utc).isoformat()
        return payload
