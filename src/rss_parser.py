from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Iterable

import feedparser

from src.models import Tender

TENDER_ID_RE = re.compile(r"/(\d{6,})-tender-")


def extract_tender_id(url: str) -> str | None:
    match = TENDER_ID_RE.search(url)
    return match.group(1) if match else None


def _parse_published(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError, IndexError):
        return None


def parse_rss(content: str, *, source: str = "rss") -> list[Tender]:
    feed = feedparser.parse(content)
    tenders: list[Tender] = []

    for entry in feed.entries:
        url = getattr(entry, "link", "") or ""
        tender_id = extract_tender_id(url)
        if not tender_id:
            continue

        title = getattr(entry, "title", "") or ""
        description = getattr(entry, "description", "") or getattr(entry, "summary", "") or ""
        published = _parse_published(getattr(entry, "published", None))

        tenders.append(
            Tender(
                id=tender_id,
                title=title.strip(),
                description=description.strip(),
                url=url,
                published=published,
                source=source,
            )
        )

    return tenders


def deduplicate_tenders(tenders: Iterable[Tender]) -> list[Tender]:
    seen: set[str] = set()
    unique: list[Tender] = []
    for tender in tenders:
        if tender.id in seen:
            continue
        seen.add(tender.id)
        unique.append(tender)
    return unique
