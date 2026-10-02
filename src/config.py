from __future__ import annotations

from pathlib import Path

import yaml

from src.fetcher import create_http_client, fetch_url


class Config:
    def __init__(
        self,
        rss_url: str,
        category_url: str,
        keywords: list[str],
        interval_minutes: int,
        storage_path: Path,
        output_path: Path,
        use_category_fallback: bool,
    ) -> None:
        self.rss_url = rss_url
        self.category_url = category_url
        self.keywords = keywords
        self.interval_minutes = interval_minutes
        self.storage_path = storage_path
        self.output_path = output_path
        self.use_category_fallback = use_category_fallback

    @property
    def interval_seconds(self) -> int:
        return self.interval_minutes * 60


def load_config(path: Path | None = None) -> Config:
    config_path = path or Path("config.yaml")
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")

    with config_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    return Config(
        rss_url=raw["rss_url"],
        category_url=raw.get(
            "category_url", "https://rostender.info/category/tendery-v-oblasti-it"
        ),
        keywords=[str(k) for k in raw.get("keywords", [])],
        interval_minutes=int(raw.get("interval_minutes", 10)),
        storage_path=Path(raw.get("storage_path", "data/seen.db")),
        output_path=Path(raw.get("output_path", "output/matches.jsonl")),
        use_category_fallback=bool(raw.get("use_category_fallback", True)),
    )


__all__ = ["Config", "load_config", "create_http_client", "fetch_url"]
