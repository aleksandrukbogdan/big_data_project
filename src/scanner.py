from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from src.category_parser import parse_category_page
from src.config import Config
from src.fetcher import create_http_client, fetch_url
from src.filter import filter_tenders
from src.models import Tender
from src.rss_parser import deduplicate_tenders, parse_rss
from src.storage import SeenStorage

logger = logging.getLogger(__name__)


def fetch_all_tenders(config: Config, client: httpx.Client) -> list[Tender]:
    tenders: list[Tender] = []

    logger.info("Fetching RSS: %s", config.rss_url)
    rss_content = fetch_url(config.rss_url, client=client)
    tenders.extend(parse_rss(rss_content, source="rss"))

    if config.use_category_fallback:
        logger.info("Fetching category page: %s", config.category_url)
        category_content = fetch_url(config.category_url, client=client)
        tenders.extend(parse_category_page(category_content, source="category"))

    return deduplicate_tenders(tenders)


def process_new_matches(
    tenders: list[Tender],
    config: Config,
    storage: SeenStorage,
) -> list[Tender]:
    matched = filter_tenders(tenders, config.keywords)
    new_matches: list[Tender] = []

    for tender in matched:
        if storage.is_seen(tender.id):
            continue
        storage.mark_seen(tender.id)
        new_matches.append(tender)

    return new_matches


def append_matches(output_path: Path, matches: list[Tender]) -> None:
    if not matches:
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("a", encoding="utf-8") as f:
        for tender in matches:
            f.write(json.dumps(tender.to_dict(), ensure_ascii=False) + "\n")


def print_matches(matches: list[Tender]) -> None:
    if not matches:
        logger.info("No new matching tenders.")
        return

    for tender in matches:
        published = tender.published.isoformat() if tender.published else "unknown"
        keywords = ", ".join(tender.matched_keywords) or "-"
        print("-" * 60)
        print(f"ID:        {tender.id}")
        print(f"Title:     {tender.title}")
        print(f"Keywords:  {keywords}")
        print(f"Published: {published}")
        print(f"Source:    {tender.source}")
        print(f"URL:       {tender.url}")


def run_once(config: Config) -> list[Tender]:
    with create_http_client() as client, SeenStorage(config.storage_path) as storage:
        tenders = fetch_all_tenders(config, client)
        logger.info("Fetched %s unique tenders", len(tenders))

        matches = process_new_matches(tenders, config, storage)
        append_matches(config.output_path, matches)
        print_matches(matches)

        logger.info("New matches: %s", len(matches))
        return matches
