from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape

from src.models import Tender

PRICE_RE = re.compile(r"Цена:\s*([\d\s\u00a0]+)\s*руб", re.IGNORECASE)
LOCATION_RE = re.compile(r"Место поставки:\s*([^;<\n]+)", re.IGNORECASE)
REGION_CITY_RE = re.compile(
    r"/region/([^/]+)/(?:([^/]+)/)?(\d{6,})-tender-",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class TenderAttributes:
    tender_id: str
    url: str
    source: str
    city: str | None
    region: str | None
    location_raw: str | None
    price_rub: float | None
    price_raw: str | None
    currency: str = "RUB"

    def location_record(self) -> dict[str, str | None]:
        return {
            "tender_id": self.tender_id,
            "city": self.city,
            "region": self.region,
            "location_raw": self.location_raw,
            "url": self.url,
            "source": self.source,
        }

    def price_record(self) -> dict[str, str | float | None]:
        return {
            "tender_id": self.tender_id,
            "price_rub": self.price_rub,
            "price_raw": self.price_raw,
            "currency": self.currency,
            "url": self.url,
            "source": self.source,
        }


def _plain_text(value: str) -> str:
    text = unescape(value).replace("<br />", "\n").replace("<br/>", "\n").replace("<br>", "\n")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _parse_price(text: str) -> tuple[float | None, str | None]:
    match = PRICE_RE.search(text)
    if not match:
        return None, None
    raw = match.group(0).strip()
    digits = re.sub(r"\D", "", match.group(1))
    if not digits:
        return None, raw
    return float(digits), raw


def _humanize_slug(slug: str | None) -> str | None:
    if not slug:
        return None
    return slug.replace("-", " ").strip()


def parse_region_city_from_url(url: str) -> tuple[str | None, str | None]:
    match = REGION_CITY_RE.search(url)
    if not match:
        return None, None
    region_slug, maybe_city, _tender_id = match.groups()
    city_slug = None if not maybe_city or maybe_city.isdigit() else maybe_city
    return _humanize_slug(region_slug), _humanize_slug(city_slug)


def extract_attributes(tender: Tender) -> TenderAttributes:
    text = _plain_text(tender.description)
    location_raw_match = LOCATION_RE.search(text)
    location_raw = location_raw_match.group(1).strip() if location_raw_match else None
    price_rub, price_raw = _parse_price(text)
    region_from_url, city_from_url = parse_region_city_from_url(tender.url)

    city = location_raw
    if city and city.lower().startswith("г."):
        city = city[2:].strip()
    if not city:
        city = city_from_url

    return TenderAttributes(
        tender_id=tender.id,
        url=tender.url,
        source=tender.source,
        city=city,
        region=region_from_url,
        location_raw=location_raw or city_from_url,
        price_rub=price_rub,
        price_raw=price_raw,
    )


def extract_attributes_many(tenders: list[Tender]) -> list[TenderAttributes]:
    return [extract_attributes(tender) for tender in tenders]
