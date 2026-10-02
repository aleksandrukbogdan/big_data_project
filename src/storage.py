from __future__ import annotations

import sqlite3
from pathlib import Path


class SeenStorage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS seen_tenders (
                tender_id TEXT PRIMARY KEY,
                seen_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        self._conn.commit()

    def is_seen(self, tender_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen_tenders WHERE tender_id = ?",
            (tender_id,),
        ).fetchone()
        return row is not None

    def mark_seen(self, tender_id: str) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen_tenders (tender_id) VALUES (?)",
            (tender_id,),
        )
        self._conn.commit()

    def filter_new(self, tender_ids: list[str]) -> list[str]:
        return [tender_id for tender_id in tender_ids if not self.is_seen(tender_id)]

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> SeenStorage:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
