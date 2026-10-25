from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone

from src.card import parse_tender_card

MSK = timezone(timedelta(hours=3))


def _page(body: str) -> str:
    return f"<html><body>{body}</body></html>"


class CardParserTest(unittest.TestCase):
    def test_completed_small_purchase(self) -> None:
        html = _page(
            """
            <h1>Тендер: Закупка лицензий</h1>
            <div>Завершён</div>
            <div>Начальная цена</div>
            <div>300 000 ₽</div>
            <div>Место поставки</div>
            <div>г. Коломна</div>
            <div>Окончание (МСК)</div>
            <div>16.07.2026 16:06</div>
            <div>Участие</div>
            <div>Способ размещения</div>
            <div>Закупки малого объема</div>
            <div>Подача заявок (МСК)</div>
            <div>14.07.2026 16:06 - 16.07.2026 16:06</div>
            <div>Заключение контракта (МСК)</div>
            <div>23.07.2026</div>
            <div>Отрасль</div>
            <ul>
              <li>Создание баз данных и информационных ресурсов, обработка данных</li>
              <li>Тендеры на создание баз данных и информационных ресурсов в Московской области</li>
              <li>Прочие услуги в области информационных технологий</li>
            </ul>
            <div>Участники и контракты</div>
            <div>8-800-555-69-56</div>
            """
        )
        card = parse_tender_card(html, tender_id="93722966", url="https://example.test/t")
        self.assertEqual(card.status, "Завершён")
        self.assertEqual(card.price_kind, "nmck")
        self.assertEqual(card.nmck_rub, 300000)
        self.assertEqual(card.procedure_group, "Закупки малого объема")
        self.assertIsNone(card.procedure_name)
        self.assertEqual(card.application_start, datetime(2026, 7, 14, 16, 6, tzinfo=MSK))
        self.assertEqual(card.application_end, datetime(2026, 7, 16, 16, 6, tzinfo=MSK))
        self.assertEqual(card.contract_date, date(2026, 7, 23))
        self.assertEqual(
            card.industries,
            (
                "Создание баз данных и информационных ресурсов, обработка данных",
                "Прочие услуги в области информационных технологий",
            ),
        )

    def test_contest_and_same_line_price(self) -> None:
        html = _page(
            """
            <h1>Тендер: Сопровождение сайта</h1>
            <div>Завершён</div>
            <div>Начальная цена 1 000 000 ₽</div>
            <div>Способ размещения</div>
            <div>Конкурсы</div>
            <div>Открытый конкурс в электронной форме</div>
            <div>Подача заявок (МСК)</div>
            <div>02.03.2026 10:35 - 20.03.2026 05:00</div>
            <div>Отрасль</div>
            <div>Прочие услуги в области информационных технологий</div>
            """
        )
        card = parse_tender_card(html, tender_id="90365065", url="https://example.test/c")
        self.assertEqual(card.nmck_rub, 1000000)
        self.assertEqual(card.procedure_group, "Конкурсы")
        self.assertEqual(card.procedure_name, "Открытый конкурс в электронной форме")
        self.assertEqual(card.industries, ("Прочие услуги в области информационных технологий",))

    def test_cancelled_without_price(self) -> None:
        html = _page(
            """
            <div>Отменён</div>
            <div>Начальная цена</div>
            <div>—</div>
            <div>Способ размещения Прочее</div>
            <div>Торги заданного объема</div>
            <div>Подача заявок (МСК)</div>
            <div>по 12.08.2026 11:40</div>
            <div>Отрасль</div>
            <div>░░░░░░░░</div>
            <div>Строительные железобетонные изделия</div>
            """
        )
        card = parse_tender_card(html, tender_id="94184643", url="https://example.test/x")
        self.assertEqual(card.status, "Отменён")
        self.assertIsNone(card.nmck_rub)
        self.assertEqual(card.nmck_raw, "—")
        self.assertEqual(card.procedure_group, "Прочее")
        self.assertEqual(card.procedure_name, "Торги заданного объема")
        self.assertIsNone(card.application_start)
        self.assertEqual(card.application_end, datetime(2026, 8, 12, 11, 40, tzinfo=MSK))
        self.assertEqual(card.industries, ("Строительные железобетонные изделия",))
        self.assertIsNone(card.contract_date)


if __name__ == "__main__":
    unittest.main()
