from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class Tender:
    id: str
    title: str
    description: str
    url: str
    published: datetime | None
    matched_keywords: tuple[str, ...] = ()
    source: str = "rss"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["published"] = self.published.isoformat() if self.published else None
        data["matched_keywords"] = list(self.matched_keywords)
        return data

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.description}"
