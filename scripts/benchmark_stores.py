from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import matplotlib.pyplot as plt

from src.etl import attributes_from_tenders, fetch_raw_sources, load_etl_config, parse_tenders_from_raw
from src.loaders.minio_loader import MinioLoader, raw_object_prefix
from src.loaders.mongo_loader import MongoLoader
from src.loaders.postgres_loader import PostgresLoader
from src.models import Tender

logger = logging.getLogger(__name__)

FIGURES = ROOT / "report" / "figures"
RESULTS_MD = ROOT / "report" / "benchmark_results.md"
RESULTS_JSON = ROOT / "report" / "benchmark_results.json"


def _timed(fn):
    started = time.perf_counter()
    result = fn()
    elapsed_ms = (time.perf_counter() - started) * 1000
    return result, elapsed_ms


def _repeat(fn, times: int = 5) -> float:
    samples = []
    for _ in range(times):
        _, elapsed_ms = _timed(fn)
        samples.append(elapsed_ms)
    return mean(samples)


def tenders_from_jsonl(path: Path) -> list[Tender]:
    tenders: list[Tender] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        published = item.get("published")
        tenders.append(
            Tender(
                id=str(item["id"]),
                title=item.get("title") or "",
                description=item.get("description") or "",
                url=item.get("url") or "",
                published=datetime.fromisoformat(published) if published else None,
                matched_keywords=tuple(item.get("matched_keywords") or ()),
                source=item.get("source") or "rss",
            )
        )
    return tenders


def raw_from_tenders(tenders: list[Tender]) -> dict[str, str]:
    items = []
    links = []
    for tender in tenders:
        items.append(
            "<item>"
            f"<title>{escape(tender.title)}</title>"
            f"<link>{escape(tender.url)}</link>"
            f"<description>{escape(tender.description)}</description>"
            "</item>"
        )
        links.append(f'<a class="tender-row" href="{escape(tender.url)}">{escape(tender.title)}</a>')
    rss = "<?xml version='1.0' encoding='utf-8'?><rss><channel>" + "".join(items) + "</channel></rss>"
    html = "<html><body>" + "".join(links) + "</body></html>"
    return {"rss.xml": rss, "category.html": html}


def load_batch(config_path: Path | None, *, snapshot_only: bool = False) -> tuple[dict[str, str], list[Tender], float, str]:
    snapshot = ROOT / "output" / "matches.jsonl"
    if snapshot_only:
        tenders = tenders_from_jsonl(snapshot)
        return raw_from_tenders(tenders), tenders, 0.0, f"snapshot {snapshot.name}"
    config = load_etl_config(config_path)
    try:
        payloads, extract_ms = _timed(lambda: fetch_raw_sources(config))
        tenders = parse_tenders_from_raw(payloads)
        if not tenders:
            raise RuntimeError("live extract returned no tenders")
        return payloads, tenders, extract_ms, "live rostender.info"
    except Exception as exc:
        snapshot = ROOT / "output" / "matches.jsonl"
        logger.warning("Live extract failed (%s). Using %s", exc, snapshot)
        tenders = tenders_from_jsonl(snapshot)
        return raw_from_tenders(tenders), tenders, 0.0, f"snapshot {snapshot.name}: {exc}"


def benchmark(config_path: Path | None = None, *, snapshot_only: bool = False) -> dict:
    payloads, tenders, extract_ms, data_source = load_batch(config_path, snapshot_only=snapshot_only)
    attrs = attributes_from_tenders(tenders)
    sample_id = tenders[0].id if tenders else None

    minio = MinioLoader()
    prefix = raw_object_prefix(datetime.now(timezone.utc), "benchmark")

    def write_minio():
        for name, content in payloads.items():
            content_type = (
                "application/xml; charset=utf-8"
                if name.endswith(".xml")
                else "text/html; charset=utf-8"
            )
            minio.put_text(f"{prefix}{name}", content, content_type)

    _, minio_write_ms = _timed(write_minio)
    minio_size = sum(minio.object_size(f"{prefix}{name}") for name in payloads)

    def query_minio():
        xml = minio.get_text(f"{prefix}rss.xml")
        if sample_id:
            return sample_id in xml
        return bool(xml)

    minio_query_ms = _repeat(query_minio)

    with MongoLoader() as mongo:
        _, mongo_write_ms = _timed(lambda: mongo.upsert_tenders(tenders))
        mongo_size = mongo.storage_size_bytes()

        def query_mongo():
            if not sample_id:
                return mongo.count()
            return mongo.find_by_id(sample_id)

        mongo_query_ms = _repeat(query_mongo)
        mongo_count = mongo.count()

    with PostgresLoader() as postgres:
        postgres.ensure_schema()
        _, pg_write_ms = _timed(lambda: postgres.upsert_attributes(attrs))
        pg_size = postgres.storage_size_bytes()

        def query_postgres():
            if not sample_id:
                return postgres.count_prices()
            return postgres.fetch_location(sample_id)

        pg_query_ms = _repeat(query_postgres)
        pg_rows = postgres.count_locations()

    return {
        "data_source": data_source,
        "extracted_files": list(payloads),
        "tenders": len(tenders),
        "extract_ms": round(extract_ms, 2),
        "sample_id": sample_id,
        "stores": {
            "MinIO": {
                "write_ms": round(minio_write_ms, 2),
                "query_ms": round(minio_query_ms, 2),
                "size_bytes": minio_size,
                "rows": len(payloads),
            },
            "MongoDB": {
                "write_ms": round(mongo_write_ms, 2),
                "query_ms": round(mongo_query_ms, 2),
                "size_bytes": mongo_size,
                "rows": mongo_count,
            },
            "PostgreSQL": {
                "write_ms": round(pg_write_ms, 2),
                "query_ms": round(pg_query_ms, 2),
                "size_bytes": pg_size,
                "rows": pg_rows,
            },
        },
    }


def save_charts(results: dict) -> list[Path]:
    FIGURES.mkdir(parents=True, exist_ok=True)
    plt.rcParams["font.family"] = "DejaVu Sans"
    names = list(results["stores"])
    write_ms = [results["stores"][name]["write_ms"] for name in names]
    query_ms = [results["stores"][name]["query_ms"] for name in names]
    size_kb = [results["stores"][name]["size_bytes"] / 1024 for name in names]

    paths = []
    for title, ylabel, values, filename in [
        ("Время записи батча в ODS", "мс", write_ms, "write_time.png"),
        ("Время точечного запроса", "мс", query_ms, "query_time.png"),
        ("Объём данных после загрузки", "КиБ", size_kb, "storage_size.png"),
    ]:
        fig, ax = plt.subplots(figsize=(7.2, 4.2))
        bars = ax.bar(names, values, color=["#4C78A8", "#F58518", "#54A24B"])
        ax.set_title(title)
        ax.set_ylabel(ylabel)
        ax.bar_label(bars, fmt="%.1f")
        fig.tight_layout()
        path = FIGURES / filename
        fig.savefig(path, dpi=140)
        plt.close(fig)
        paths.append(path)
    return paths


def save_markdown(results: dict) -> Path:
    stores = results["stores"]
    lines = [
        "# Сравнение хранилищ",
        "",
        f"- Дата: {datetime.now().isoformat(timespec='seconds')}",
        f"- Откуда батч: {results['data_source']}",
        f"- Тендеров: **{results['tenders']}**",
        f"- Проверочный id: `{results['sample_id']}`",
        "",
        "| Хранилище | Запись, мс | Запрос по id, мс | Объём, КиБ | Объектов/строк |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, row in stores.items():
        lines.append(
            f"| {name} | {row['write_ms']:.2f} | {row['query_ms']:.2f} | "
            f"{row['size_bytes'] / 1024:.1f} | {row['rows']} |"
        )
    lines.extend(
        [
            "",
            "128 КиБ у PostgreSQL — размер таблиц вместе с пустыми страницами, не размер самих строк. У MinIO и MongoDB цифра ближе к объёму данных.",
            "",
            "Если батч взят из snapshot, сайт в момент прогона не открылся. Процессы Airflow ходят на сайт сами. Файл `output/matches.jsonl` нужен, чтобы сравнить хранилища без сети.",
            "",
            "## Графики",
            "",
            "![Время записи](figures/write_time.png)",
            "",
            "![Время запроса](figures/query_time.png)",
            "",
            "![Объём](figures/storage_size.png)",
            "",
        ]
    )
    RESULTS_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return RESULTS_MD


def main() -> int:
    parser = argparse.ArgumentParser(description="Сравнение MinIO, MongoDB и PostgreSQL на одном батче тендеров")
    parser.add_argument("-c", "--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Skip live HTTP and use output/matches.jsonl",
    )
    args = parser.parse_args()

    results = benchmark(args.config, snapshot_only=args.snapshot)
    RESULTS_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    save_charts(results)
    save_markdown(results)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(f"Wrote {RESULTS_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
