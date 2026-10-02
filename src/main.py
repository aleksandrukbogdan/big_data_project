from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from src.config import load_config
from src.scanner import run_once

logger = logging.getLogger(__name__)
_shutdown_requested = False


def _handle_shutdown(signum, frame) -> None:
    global _shutdown_requested
    logger.info("Shutdown requested, finishing current cycle...")
    _shutdown_requested = True


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Monitor IT tenders from rostender.info with keyword filtering",
    )
    parser.add_argument(
        "command",
        choices=["run", "run-once"],
        help="run: continuous polling; run-once: single check",
    )
    parser.add_argument(
        "-c",
        "--config",
        type=Path,
        default=Path("config.yaml"),
        help="Path to config.yaml (default: config.yaml)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    try:
        config = load_config(args.config)
    except FileNotFoundError as exc:
        logger.error("%s", exc)
        return 1

    if not config.keywords:
        logger.warning("Keyword list is empty — all tenders will be reported as matches")

    if args.command == "run-once":
        run_once(config)
        return 0

    signal.signal(signal.SIGINT, _handle_shutdown)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_shutdown)

    logger.info(
        "Starting monitor (interval=%s min, keywords=%s)",
        config.interval_minutes,
        ", ".join(config.keywords) or "(all)",
    )

    while not _shutdown_requested:
        try:
            run_once(config)
        except Exception:
            logger.exception("Error during scan cycle")

        if _shutdown_requested:
            break

        logger.info("Sleeping for %s minutes...", config.interval_minutes)
        for _ in range(config.interval_seconds):
            if _shutdown_requested:
                break
            time.sleep(1)

    logger.info("Monitor stopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
