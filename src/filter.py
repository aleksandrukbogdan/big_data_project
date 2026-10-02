from __future__ import annotations

from src.models import Tender


def find_matched_keywords(text: str, keywords: list[str]) -> list[str]:
    normalized = text.casefold()
    return [keyword for keyword in keywords if keyword.casefold() in normalized]


def filter_by_keywords(tender: Tender, keywords: list[str]) -> Tender | None:
    if not keywords:
        return tender

    matched = find_matched_keywords(tender.text, keywords)
    if not matched:
        return None

    return Tender(
        id=tender.id,
        title=tender.title,
        description=tender.description,
        url=tender.url,
        published=tender.published,
        matched_keywords=tuple(matched),
        source=tender.source,
    )


def filter_tenders(tenders: list[Tender], keywords: list[str]) -> list[Tender]:
    results: list[Tender] = []
    for tender in tenders:
        matched = filter_by_keywords(tender, keywords)
        if matched is not None:
            results.append(matched)
    return results
