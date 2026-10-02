from __future__ import annotations

import os
from pathlib import Path

import httpx

from src.attributes import TenderAttributes, extract_attributes_many
from src.category_parser import parse_category_page
from src.config import Config, load_config
from src.fetcher import create_http_client, fetch_url
from src.models import Tender
from src.rss_parser import deduplicate_tenders, parse_rss


def load_etl_config(path: str | Path | None = None) -> Config:
    resolved = path or os.environ.get("TENDER_CONFIG", "config.yaml")
    return load_config(Path(resolved))


def fetch_raw_sources(config: Config, client: httpx.Client | None = None) -> dict[str, str]:
    own_client = client is None
    http = client or create_http_client()
    try:
        payloads = {"rss.xml": fetch_url(config.rss_url, client=http)}
        if config.use_category_fallback:
            payloads["category.html"] = fetch_url(config.category_url, client=http)
        return payloads
    finally:
        if own_client:
            http.close()


def parse_tenders_from_raw(payloads: dict[str, str]) -> list[Tender]:
    tenders: list[Tender] = []
    rss = payloads.get("rss.xml")
    if rss:
        tenders.extend(parse_rss(rss, source="rss"))
    html = payloads.get("category.html")
    if html:
        tenders.extend(parse_category_page(html, source="category"))
    return deduplicate_tenders(tenders)


def fetch_tenders(config: Config, client: httpx.Client | None = None) -> list[Tender]:
    return parse_tenders_from_raw(fetch_raw_sources(config, client=client))


def attributes_from_tenders(tenders: list[Tender]) -> list[TenderAttributes]:
    return extract_attributes_many(tenders)
