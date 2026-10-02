# IT-тендеры: сбор в три хранилища

С rostender.info забираем открытые IT-тендеры и раскладываем их по трём хранилищам. Запуском занимается Airflow в Docker.

Источник: [категория IT](https://rostender.info/category/tendery-v-oblasti-it) и её [RSS](https://rostender.info/rss-category-1504.xml).

## Что куда кладётся

С одного сайта берутся три разные вещи:

- сырой XML ленты и HTML страницы — в MinIO, файлами как скачали;
- карточка тендера (заголовок, текст, ссылка, дата) — в MongoDB;
- город, регион и цена — в PostgreSQL.

MinIO выбран, потому что сырой файл не нужно разбирать, его достаточно положить и потом перечитать. MongoDB — потому что у карточки поля плавают: с HTML часто нет даты. PostgreSQL — потому что по цене и региону удобно делать обычные SQL-запросы.

Отдельно есть маленький скрипт-монитор: он оставляет только тендеры с нужными словами и пишет их в `output/matches.jsonl`. Основные процессы Airflow этот фильтр не используют и сохраняют всё, что скачали.

## Запуск

Нужен Docker.

```bash
docker compose up --build airflow-init
docker compose up -d
```

- Airflow: http://localhost:8080 — `airflow` / `airflow`
- MinIO: http://localhost:9001 — `minioadmin` / `minioadmin`
- Mongo Express: http://localhost:8081 — `admin` / `admin`
- PostgreSQL: `localhost:5433`, база и пользователь `ods`, пароль `ods`

В Airflow три процесса, сначала они на паузе:

- `ods_raw_to_minio`
- `ods_tenders_to_mongo`
- `ods_geo_prices_to_postgres`

Паузу снять и нажать Trigger. Каждый ходит на сайт раз в час.

Образ MinIO в compose — `bitnamilegacy/minio:2025.7.23`. Обычный `minio/minio` с Docker Hub больше не скачивается.

## Сравнение хранилищ

Когда контейнеры запущены:

```bash
pip install -e ".[etl]"
python scripts/benchmark_stores.py
```

Скрипт пишет таблицу и графики в `report/`. Если сайт не отвечает, можно прогнать уже сохранённый файл:

```bash
python scripts/benchmark_stores.py --snapshot
```

Текст с выводом: `report/REPORT.md`.

## Монитор по ключевым словам

```bash
pip install -e .
python -m src.main run-once
```

Слова и адреса лежат в `config.yaml`. Заказчики на сайте скрыты без подписки. Лента отдаёт только последние тендеры, не всю историю.
