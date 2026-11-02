# IT-тендеры

С rostender.info забираем открытые IT-тендеры и проводим их через три слоя. Оркестрация — Apache Airflow 2.10.5 в Docker.

Источник: [категория IT](https://rostender.info/category/tendery-v-oblasti-it) и её [RSS](https://rostender.info/rss-category-1504.xml).

## Слои

- **ODS, лабораторная 1.** Сырые XML и HTML — в MinIO, карточка — в MongoDB, город, цена, статус и отрасль — в PostgreSQL, схема `ods`.
- **DDS и качество, лабораторная 2.** DAG `dds_it_tenders` чистит данные и собирает снежинку в схеме `dds`: измерения, факт, мост отраслей, история тендера (SCD Type 2). DAG `dq_it_tenders` сверяет объёмы и пишет результат в `dds.dq_result`.
- **Витрины, лабораторная 3.** DAG `dm_it_tenders` пересобирает пять таблиц в схеме `dm`. Superset рисует дашборд «IT-тендеры». OpenMetadata показывает линию от сырых таблиц к факту и витринам.

Подробное описание второй и третьей лаб: `report/LAB2_LAB3.md`. Сравнение хранилищ первой лабы: `report/REPORT.md`.

## Что куда кладётся

С одного сайта берутся три разные вещи:

- сырой XML ленты и HTML страницы — в MinIO, файлами как скачали;
- карточка тендера (заголовок, текст, ссылка, дата, а после разбора страницы ещё статус, отрасль и сроки) — в MongoDB;
- город, регион, начальная цена (НМЦ), статус, способ размещения, окно подачи, дата контракта и отрасль — в PostgreSQL.

MinIO выбран, потому что сырой файл не нужно разбирать, его достаточно положить и потом перечитать. MongoDB — потому что у карточки поля плавают: с HTML часто нет даты. PostgreSQL — потому что по цене и региону удобно делать обычные SQL-запросы.

Отдельно есть маленький скрипт-монитор: он оставляет только тендеры с нужными словами и пишет их в `output/matches.jsonl`. Основные процессы Airflow этот фильтр не используют и сохраняют всё, что скачали.

## Запуск

Нужен Docker.

```bash
docker compose up --build airflow-init
docker compose up -d
```

- Airflow: http://localhost:8080 — `airflow` / `airflow`. Если список пустой, обнови страницу.
- Файлы MinIO: http://localhost:9002. Порт 9001 в этой сборке не открывается, 9000 — это API.
- Карточки: http://localhost:8081 — `admin` / `admin`
- Таблицы: http://localhost:8082, сервер `postgres-ods`, пользователь `ods`, пароль `ods`, база `ods`. В браузере `localhost:5433` не откроется.

В Airflow процессы сначала на паузе:

- `ods_raw_to_minio`
- `ods_tenders_to_mongo`
- `ods_geo_prices_to_postgres` — дополнительно открывает карточки IT-тендеров (лимит в `config.yaml`)
- `dds_it_tenders` — очистка, справочники, история статуса, факт и агрегаты в схеме `dds`
- `dq_it_tenders` — проверки качества после факта
- `dm_it_tenders` — витрины в схеме `dm`, стартует после детального слоя

Паузу снять и нажать Trigger у `ods_geo_prices_to_postgres`. Следующие процессы подхватятся сами. Каждый сырой процесс ходит на сайт раз в час.

- Superset: http://localhost:8088 — `admin` / `admin`, дашборд «IT-тендеры». Образ собирается из `superset/`: в официальном нет драйвера PostgreSQL. Первый старт минуту обновляет свою базу, потом открывается страница.
- OpenMetadata: http://localhost:8585 — `admin@open-metadata.org` / `admin`. Линия данных открывается на таблице `dds.fact_tender`, вкладка Lineage.

Дашборд и линия уже собраны. Если том пустой, их можно создать заново:

```bash
python scripts/bootstrap_superset.py
python scripts/publish_lineage.py
```

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
