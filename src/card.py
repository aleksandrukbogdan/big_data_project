from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import unescape

from bs4 import BeautifulSoup

from src.fetcher import create_http_client
from src.models import Tender

logger = logging.getLogger(__name__)

MSK = timezone(timedelta(hours=3))
PRICE_KIND_NMCK = "nmck"

DATE_RE = re.compile(r"(\d{2}\.\d{2}\.\d{4})(?:\s+(\d{2}:\d{2}))?")
MONEY_RE = re.compile(r"(\d[\d\s\u00a0]*)(?:[.,](\d{1,2}))?")

STATUSES = (
    "приём заявок",
    "прием заявок",
    "завершён",
    "завершен",
    "отменён",
    "отменен",
    "работа комиссии",
    "подведение итогов",
    "опубликовано",
    "планируется",
    "подача заявок",
)

MARKERS = (
    "Начальная цена",
    "Место поставки",
    "Организатор закупки",
    "Окончание (МСК)",
    "Документация",
    "Участие",
    "Способ размещения",
    "Ссылки на источники",
    "Подача заявок (МСК)",
    "Заключение контракта (МСК)",
    "Подведение итогов (МСК)",
    "Срок исполнения контракта (МСК)",
    "Срок поставки (МСК)",
    "Заказчики",
    "Заказчик",
    "Отрасль",
    "Участники и контракты",
    "Потенциальные участники",
    "Анализ заказчика",
    "Обеспечение исполнения",
    "Требования к гарантии",
    "Возможно Вас",
)


@dataclass(frozen=True)
class TenderCard:
    tender_id: str
    url: str
    status: str | None
    procedure_group: str | None
    procedure_name: str | None
    nmck_rub: float | None
    nmck_raw: str | None
    application_start: datetime | None
    application_end: datetime | None
    contract_date: date | None
    industries: tuple[str, ...]
    price_kind: str = PRICE_KIND_NMCK

    def to_record(self) -> dict:
        return {
            "tender_id": self.tender_id,
            "url": self.url,
            "status": self.status,
            "procedure_group": self.procedure_group,
            "procedure_name": self.procedure_name,
            "nmck_rub": self.nmck_rub,
            "nmck_raw": self.nmck_raw,
            "price_kind": self.price_kind,
            "application_start": _iso(self.application_start),
            "application_end": _iso(self.application_end),
            "contract_date": self.contract_date.isoformat() if self.contract_date else None,
            "industries": list(self.industries),
        }

    def usable(self) -> bool:
        return any(
            (
                self.status,
                self.nmck_raw,
                self.procedure_group,
                self.application_start,
                self.application_end,
                self.contract_date,
                self.industries,
            )
        )


def parse_tender_card(html: str, *, tender_id: str, url: str) -> TenderCard:
    lines = _html_lines(html)
    status = _status(lines)
    price_lines = _section(lines, "Начальная цена")
    nmck_raw = " ".join(price_lines).strip() or None
    nmck_rub = _money(nmck_raw) if nmck_raw else None

    procedure_lines = [
        line
        for line in _section(lines, "Способ размещения")
        if not _skip_value(line)
    ]
    procedure_group = procedure_lines[0] if procedure_lines else None
    procedure_name = procedure_lines[1] if len(procedure_lines) > 1 else None

    window = " ".join(_section(lines, "Подача заявок (МСК)"))
    application_start, application_end = _window(window)
    if application_end is None:
        ending = " ".join(_section(lines, "Окончание (МСК)"))
        _, application_end = _window(ending)

    contract_raw = " ".join(_section(lines, "Заключение контракта (МСК)"))
    contract_dates = _datetimes(contract_raw)
    contract_date = contract_dates[0].date() if contract_dates else None

    industries = tuple(_industries(_section(lines, "Отрасль")))
    return TenderCard(
        tender_id=tender_id,
        url=url,
        status=status,
        procedure_group=procedure_group,
        procedure_name=procedure_name,
        nmck_rub=nmck_rub,
        nmck_raw=nmck_raw,
        application_start=application_start,
        application_end=application_end,
        contract_date=contract_date,
        industries=industries,
    )


def fetch_tender_cards(
    tenders: list[Tender],
    *,
    limit: int,
    delay_seconds: float,
) -> list[TenderCard]:
    if limit <= 0:
        return []

    selected: list[Tender] = []
    seen: set[str] = set()
    for tender in tenders:
        if not tender.url or tender.id in seen:
            continue
        seen.add(tender.id)
        selected.append(tender)
        if len(selected) >= limit:
            break

    cards: list[TenderCard] = []
    if not selected:
        return cards

    with create_http_client(timeout=15.0) as client:
        for index, tender in enumerate(selected, start=1):
            if index > 1 and delay_seconds > 0:
                time.sleep(delay_seconds)
            try:
                response = client.get(tender.url)
                response.raise_for_status()
                card = parse_tender_card(response.text, tender_id=tender.id, url=tender.url)
            except Exception as exc:
                logger.warning("Card %s skipped: %s", tender.id, exc)
                continue
            if not card.usable():
                logger.warning("Card %s has no open fields", tender.id)
                continue
            cards.append(card)
            logger.info(
                "Card %s/%s %s status=%s nmck=%s",
                index,
                len(selected),
                tender.id,
                card.status,
                card.nmck_rub,
            )
    return cards


def _html_lines(html: str) -> list[str]:
    soup = BeautifulSoup(unescape(html), "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    lines: list[str] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        if line:
            lines.append(line)
    return lines


def _match_label(line: str, label: str) -> str | None:
    if line.casefold() == label.casefold():
        return ""
    prefix = f"{label.casefold()} "
    if line.casefold().startswith(prefix):
        return line[len(label) :].strip(" \t:-—")
    return None


def _is_marker(line: str) -> bool:
    return any(_match_label(line, marker) is not None for marker in MARKERS)


def _section(lines: list[str], label: str) -> list[str]:
    for index, line in enumerate(lines):
        rest = _match_label(line, label)
        if rest is None:
            continue
        values = [rest] if rest else []
        for nxt in lines[index + 1 :]:
            if _is_marker(nxt):
                break
            if _skip_value(nxt):
                continue
            values.append(nxt)
        return [value for value in values if value]
    return []


def _status(lines: list[str]) -> str | None:
    for line in lines:
        if _is_marker(line):
            if _match_label(line, "Начальная цена") is not None:
                break
            continue
        folded = line.casefold().rstrip(".")
        if folded in STATUSES:
            return line.rstrip(".")
    return None


def _skip_value(line: str) -> bool:
    folded = line.casefold()
    if folded in {"анализ заказчика", "бесплатное участие на этп"}:
        return True
    if folded.startswith("все тендеры"):
        return True
    if "░" in line:
        return True
    return False


def _industries(lines: list[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for line in lines:
        if line.casefold().startswith("тендеры на "):
            continue
        if DATE_RE.search(line):
            continue
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        found.append(line)
    return found


def _money(text: str) -> float | None:
    compact = text.replace("\u00a0", " ").strip()
    if not compact or re.fullmatch(r"[-—–]+", compact):
        return None
    match = MONEY_RE.search(compact)
    if not match:
        return None
    whole = re.sub(r"\D", "", match.group(1))
    if not whole:
        return None
    fraction = match.group(2) or "0"
    return float(f"{int(whole)}.{fraction}")


def _datetimes(text: str) -> list[datetime]:
    found: list[datetime] = []
    for day, clock in DATE_RE.findall(text):
        dd, month, year = (int(part) for part in day.split("."))
        hour, minute = (0, 0)
        if clock:
            hour, minute = (int(part) for part in clock.split(":"))
        found.append(datetime(year, month, dd, hour, minute, tzinfo=MSK))
    return found


def _window(text: str) -> tuple[datetime | None, datetime | None]:
    if not text.strip():
        return None, None
    parts = re.split(r"\s+[–—-]\s+", text, maxsplit=1)
    if len(parts) == 2 and DATE_RE.search(parts[0]) and DATE_RE.search(parts[1]):
        start = _datetimes(parts[0])
        end = _datetimes(parts[1])
        return (start[0] if start else None, end[0] if end else None)
    found = _datetimes(text)
    if not found:
        return None, None
    return None, found[-1]


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
