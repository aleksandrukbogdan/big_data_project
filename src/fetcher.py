from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; TenderScreening/0.1; +https://github.com/local/tender-screening)"
)
DEFAULT_TIMEOUT = 30.0
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2.0


def create_http_client() -> httpx.Client:
    return httpx.Client(
        timeout=DEFAULT_TIMEOUT,
        headers={"User-Agent": DEFAULT_USER_AGENT},
        follow_redirects=True,
    )


def fetch_url(url: str, *, client: httpx.Client | None = None) -> str:
    last_error: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            if client is not None:
                response = client.get(url)
            else:
                with create_http_client() as own_client:
                    response = own_client.get(url)
            response.raise_for_status()
            return response.text
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            last_error = exc
            logger.warning(
                "Fetch attempt %s/%s failed for %s: %s",
                attempt,
                MAX_RETRIES,
                url,
                exc,
            )
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY_SECONDS * attempt)

    raise RuntimeError(f"Failed to fetch {url}") from last_error
