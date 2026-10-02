from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.models import Tender
from src.rss_parser import extract_tender_id

logger = logging.getLogger(__name__)

BASE_URL = "https://rostender.info"


def parse_category_page(html: str, *, source: str = "category") -> list[Tender]:
    soup = BeautifulSoup(html, "html.parser")
    tenders: list[Tender] = []

    for row in soup.select(".tender-row"):
        link = row.select_one("a[href*='-tender-']")
        if link is None:
            continue

        href = link.get("href", "")
        url = urljoin(BASE_URL, href)
        tender_id = extract_tender_id(url)
        if not tender_id:
            continue

        title_el = row.select_one(".tender__info a, .tender-info-column a")
        title = title_el.get_text(strip=True) if title_el else link.get_text(strip=True)

        description = ""
        desc_el = row.select_one(".tender__description, .description")
        if desc_el is not None:
            description = desc_el.get_text(strip=True)

        tenders.append(
            Tender(
                id=tender_id,
                title=title,
                description=description,
                url=url,
                published=None,
                source=source,
            )
        )

    if tenders:
        return tenders

    return _parse_category_from_links(soup, source=source)


def _parse_category_from_links(soup: BeautifulSoup, *, source: str) -> list[Tender]:
    tenders: list[Tender] = []
    seen: set[str] = set()

    for link in soup.find_all("a", href=re.compile(r"/\d{6,}-tender-")):
        href = link.get("href", "")
        url = urljoin(BASE_URL, href)
        tender_id = extract_tender_id(url)
        if not tender_id or tender_id in seen:
            continue

        seen.add(tender_id)
        title = link.get("title") or link.get_text(strip=True)
        tenders.append(
            Tender(
                id=tender_id,
                title=title,
                description="",
                url=url,
                published=None,
                source=source,
            )
        )

    return tenders
