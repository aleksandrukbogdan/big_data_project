# Лабораторные работы №2 и №3

Источник данных: открытые IT-тендеры с [rostender.info](https://rostender.info/category/tendery-v-oblasti-it) (категория IT и RSS). Сырой слой ODS заполняется процессами ЛР1 и хранится в PostgreSQL (`postgres-ods`, схема `ods`). Ниже описано, что сделано поверх этого слоя в ЛР2 и ЛР3.

Общая цепочка:

```
rostender.info
    → ODS (ЛР1): MinIO / MongoDB / PostgreSQL
    → DDS (ЛР2): схема dds — очистка, измерения, SCD, факт, агрегаты
    → DQ  (ЛР2): проверки качества → dds.dq_result
    → DM  (ЛР3): схема dm — пять витрин
    → Superset (ЛР3): дашборд «IT-тендеры»
    → OpenMetadata (ЛР3): Data Lineage
```

Оркестрация — Apache Airflow 2.10.5 в Docker. Код: `dags/`, логика загрузки: `src/`, DDL: `sql/`.

---

# Лабораторная работа №2  
## Нормализация данных. Data Quality

### Цель

Построить базовое аналитическое хранилище (слой DDS) на основе сырых данных ODS из ЛР1: очистка, трансформация, нормализация до 3НФ, медленно изменяющиеся измерения (SCD), зависимости между ETL-процессами и проверки качества данных.

### 1. Структура хранилища

Выбрана схема **«снежинка»** (snowflake) в **третьей нормальной форме**.

Почему снежинка, а не звезда:

- город логически зависит от региона; регион вынесен в отдельное измерение `dim_region`, а `dim_city` ссылается на него через `region_key`;
- отрасли у одной закупки бывают несколькими — связь M:N оформлена через мост `bridge_tender_industry`, а не дублированием строк факта;
- в факте хранятся только суррогатные/натуральные ключи и меры, без повторяющихся текстовых атрибутов измерений.

DDL: `sql/init_dds.sql`. Схема создаётся и поддерживается при каждом прогоне `dds_it_tenders`.

#### Факт

| Таблица | Смысл |
|---|---|
| `dds.fact_tender` | Одна строка на тендер. Меры: `nmck_rub` (НМЦ), `application_hours` (длительность приёма заявок), `days_to_contract`, `industry_count`. Признаки: `has_card`. Даты через ключи календаря. |

#### Измерения

| Таблица | Смысл |
|---|---|
| `dds.dim_date` | Календарь: `date_key`, год, квартал, месяц, день, `week_start` |
| `dds.dim_region` | Регион: код/имя и русское `region_title` |
| `dds.dim_city` | Город внутри региона (`region_key` + `city_name`) |
| `dds.dim_procedure` | Способ размещения: группа и название процедуры |
| `dds.dim_industry` | Отрасль |
| `dds.dim_tender` | Карточка тендера с историей (SCD Type 2) |

#### Мост и агрегаты DDS

| Таблица | Смысл |
|---|---|
| `dds.bridge_tender_industry` | Связь текущей версии тендера с отраслями |
| `dds.agg_region_procedure` | Число закупок и суммы НМЦ по региону × процедуре |
| `dds.agg_deadline_week` | Число закупок и суммы НМЦ по неделе окончания приёма |

#### Представления для чтения

| View | Назначение |
|---|---|
| `dds.v_tender` | Денормализованный срез факта с русскими именами региона/города, процедурой, датами и неделей окончания приёма |
| `dds.v_tender_industry` | Факт × отрасли (для срезов по отраслям) |

### 2. ETL-процесс детального слоя

**DAG:** `dds_it_tenders` (`dags/dds_it_tenders.py`)  
**Код шагов:** `src/dds_load.py`

Расписание: Dataset `postgres://postgres-ods:5432/ods/ods/tender_cards` (публикуется ODS-процессом `ods_geo_prices_to_postgres`).  
Дополнительно: `PythonSensor wait_ods` проверяет успешный `DagRun` ODS.

Цепочка задач:

```
wait_ods → clean → conform → scd → fact → aggregate
```

#### Шаг `clean` — очистка и обогащение

Из `ods.tender_locations` (+ cards, prices) формируется стейдж `dds.stg_tender`:

- удаление дублей по `tender_id` (`DISTINCT ON`);
- нормализация пробелов в регионе;
- срез префиксов «г.» / «город» у названия города;
- пустые регион/город → «Не указан»;
- нулевая и пустая цена не попадают в меру (`nmck_rub = NULL`); приоритет у НМЦ с карточки, иначе цена из ленты;
- обогащение: `application_hours`, `days_to_contract`, даты в часовом поясе `Europe/Moscow`;
- отрасли — во временную `dds.stg_industry`.

#### Шаг `conform` — справочники

Заполнение измерений из стейджа:

- `dim_date` по всем датам старта/окончания приёма и контракта, плюс дозаполнение календаря без пропусков между крайними датами;
- `dim_region`, `dim_city`, `dim_procedure`, `dim_industry`;
- русские названия регионов и городов (`region_title`, `city_title`).

#### Шаг `scd` — медленно изменяющееся измерение

Реализован **SCD Type 2** для `dds.dim_tender`.

Отслеживаемые атрибуты: `status`, `procedure_group`, `procedure_name`, `url`.

Поведение:

1. если текущая версия (`is_current = true`) отличается от стейджа — закрыть её (`is_current = false`, `valid_to = now()`);
2. если открытой версии нет — вставить новую с `valid_from = now()`, `is_current = true`;
3. уникальность одной открытой версии на тендер обеспечена частичным уникальным индексом `uq_dim_tender_current`.

Пока атрибуты не меняются, новая версия не создаётся.

#### Шаг `fact` — факт и мост

- upsert в `dds.fact_tender` по `tender_id` с привязкой к текущей версии `dim_tender` и ключам измерений;
- пересборка `bridge_tender_industry` для текущих версий изменённых тендеров.

#### Шаг `aggregate` — агрегаты DDS

Пересчёт `agg_region_procedure` и `agg_deadline_week`.  
По завершении публикуется Dataset `dds/fact_tender` — сигнал для DQ и витрин.

### 3. Зависимости между процессами

Использованы два механизма Airflow:

1. **Datasets** — ODS публикует dataset карточек → стартует DDS; DDS публикует dataset факта → стартуют DQ и DM.
2. **PythonSensor** — `wait_ods` / `wait_dds` дополнительно ждут успешного завершения соответствующего DAG (режим `reschedule`, poke 30 с).

Итог: детальный слой не считается, пока сырой PostgreSQL-ETL не завершился успешно; DQ и витрины не считаются, пока не готов факт.

### 4. Data Quality

**DAG:** `dq_it_tenders` (`dags/dq_it_tenders.py`)  
**Логика:** `src/dq_load.py`  
**Хранение результатов:** `dds.dq_result` (имя проверки, severity, passed, observed/expected, details, checked_at).

Расписание: Dataset факта DDS + сенсор `wait_dds`.

| Проверка | Severity | Смысл |
|---|---|---|
| `fact_matches_locations` | error | Число строк факта = число строк `ods.tender_locations` |
| `one_current_version` | error | У каждого тендера ровно одна открытая версия измерения; без дублей current |
| `bridge_matches_industries` | error | Объём моста отраслей совпадает с ODS |
| `no_nonpositive_nmck_in_fact` | error | В факте нет нулевой/отрицательной НМЦ |
| `no_negative_application_hours` | error | Окно подачи не заканчивается раньше начала |
| `cards_keep_status` | error | У разобранных карточек статус доезжает до факта |
| `region_title_filled` | error | У факта есть русское имя региона |
| `ods_price_missing_or_zero` | warning | В сырье есть пустая/нулевая цена (в факте обнуляется в NULL) |
| `card_without_nmck` | warning | На карточке на сайте нет начальной цены |
| `location_without_card` | info | Строки ленты без дочитанной карточки (допустимо) |

При любой проверке со severity `error` и `passed = false` задача падает (`RuntimeError`), DAG помечается failed. Warning/info не останавливают пайплайн, но пишутся в `dq_result`.

### 5. Артефакты ЛР2

| Артефакт | Путь / адрес |
|---|---|
| DAG DDS | `dags/dds_it_tenders.py` |
| DAG DQ | `dags/dq_it_tenders.py` |
| Логика DDS | `src/dds_load.py` |
| Логика DQ | `src/dq_load.py` |
| SQL DDS | `sql/init_dds.sql` |
| Airflow UI | http://localhost:8080 |
| Данные | Adminer http://localhost:8082 → сервер `postgres-ods`, БД `ods`, схемы `ods` / `dds` |

### 6. Соответствие требованиям задания (ЛР2)

| Требование | Реализация |
|---|---|
| Структура «звезда» или «снежинка», 3НФ | Снежинка: факт + нормализованные измерения, город→регион, bridge отраслей |
| DAG очистки / обогащения / агрегации | `clean` → `conform` → `scd` → `fact` → `aggregate` |
| SCD | `dim_tender` Type 2 (`valid_from` / `valid_to` / `is_current`) |
| Зависимости ETL (сенсоры и др.) | Dataset + `PythonSensor` |
| DAG Data Quality | `dq_it_tenders`, сравнение объёмов и аномалий |

---

# Лабораторная работа №3  
## Витрины данных. Superset. Data Lineage (OpenMetadata)

### Цель

На основе детального слоя DDS сформировать витрины (Data Marts) под конкретные аналитические вопросы, обернуть загрузку в ETL с зависимостью от DDS, построить дашборд (≥5 визуализаций) в Apache Superset и отразить движение данных в OpenMetadata (Data Lineage). Развёртывание Superset и OpenMetadata добавлено в общий `docker-compose.yaml`.

### 1. Развёртывание сервисов

В `docker-compose.yaml` добавлены:

- **Superset 4.1.2** — образ собирается из `superset/` (в официальном образе нет драйвера PostgreSQL); порт **8088**;
- **OpenMetadata Server 1.6.4** + миграция схемы + отдельный PostgreSQL для метаданных; UI порт **8585**.

Учётные данные:

| Сервис | URL | Логин |
|---|---|---|
| Superset | http://localhost:8088 | `admin` / `admin` |
| OpenMetadata | http://localhost:8585 | `admin@open-metadata.org` / `admin` |

### 2. Витрины данных (схема `dm`)

**DAG:** `dm_it_tenders` (`dags/dm_it_tenders.py`)  
**Логика:** `src/dm_load.py`  
**DDL:** `sql/init_dm.sql`

Зависимости: Dataset факта DDS + сенсор `wait_dds` (успешный `dds_it_tenders`).  
Задача: `load` — TRUNCATE + INSERT по SQL из представлений DDS.

Каждая витрина отвечает на отдельный аналитический вопрос:

| Витрина | Источник | Вопрос / вывод |
|---|---|---|
| `dm.mart_region` | `dds.v_tender` | Где сосредоточены IT-закупки: число тендеров, сумма и средняя НМЦ по регионам |
| `dm.mart_procedure` | `dds.v_tender` | Какой способ размещения держит наибольший объём НМЦ |
| `dm.mart_week` | `dds.v_tender` | Когда заканчивается приём заявок (динамика по неделям) |
| `dm.mart_industry` | `dds.v_tender_industry` | Какие отрасли встречаются чаще (только count) |
| `dm.mart_price_coverage` | `dds.v_tender` (только `has_card`) | Какая доля карточек содержит начальную цену |

Ограничение по отраслям: **сумма НМЦ по отраслям не считается**. Одна закупка входит в несколько отраслей; суммирование денег дало бы задвоение. Поэтому `mart_industry` хранит только число закупок.

Структура таблиц витрин денормализована под чтение BI (строковые измерения + метрики), без необходимости джойнить снежинку в Superset.

### 3. ETL формирования витрин

Процесс:

```
wait_dds → load
```

На шаге `load`:

1. применяется DDL схемы `dm`;
2. для каждой витрины выполняется `TRUNCATE` и `INSERT … SELECT` из `dds.v_tender` / `dds.v_tender_industry`;
3. публикуется Dataset `dm/mart_region` (маркер готовности витрин).

Повторный запуск полностью пересобирает витрины (идемпотентно относительно текущего состояния DDS).

### 4. Визуализация в Superset

Скрипт первичной настройки: `scripts/bootstrap_superset.py`.

Создаёт:

- подключение к PostgreSQL ODS (`postgresql+psycopg2://ods:ods@postgres-ods:5432/ods`);
- пять датасетов по таблицам `dm.mart_*`;
- дашборд **«IT-тендеры»** с пятью визуализациями.

| № | График | Витрина | Тип | Зачем такой тип |
|---|---|---|---|---|
| 1 | Закупки по регионам | `mart_region` | столбчатый (bar) | Сравнение числа закупок между категориями |
| 2 | Сумма НМЦ по процедуре | `mart_procedure` | столбчатый (bar) | Сравнение объёма денег по способам размещения |
| 3 | Динамика по неделям окончания приёма | `mart_week` | линейный (line) | Временной ряд / «волна» сроков |
| 4 | Отрасли закупок | `mart_industry` | столбчатый (bar) | Сравнение частоты отраслей |
| 5 | Покрытие начальной цены | `mart_price_coverage` | круговая (pie) | Две доли («есть цена» / «нет») читаются на круге сразу |

Аргументация выбора: столбцы — для номинальных срезов (регион, процедура, отрасль); линия — для динамики по времени; круг — для доли покрытия цены, где частей ровно две.

### 5. Data Lineage в OpenMetadata

Скрипт: `scripts/publish_lineage.py`.

Действия скрипта:

1. логин в OpenMetadata API;
2. создание database service `tender-postgres` (тип Postgres);
3. регистрация схем и таблиц слоёв `ods`, `dds`, `dm`;
4. проведение рёбер lineage с описаниями преобразований.

Основные связи:

```
ods.tender_locations  ──► dds.fact_tender
ods.tender_prices     ──► dds.fact_tender
ods.tender_cards      ──► dds.fact_tender
ods.tender_cards      ──► dds.dim_tender          (SCD)
ods.tender_industries ──► dds.bridge_tender_industry
dds.dim_region        ──► dds.fact_tender
dds.fact_tender       ──► dm.mart_region
dds.fact_tender       ──► dm.mart_procedure
dds.fact_tender       ──► dm.mart_week
dds.fact_tender       ──► dm.mart_price_coverage
dds.bridge_tender_industry ──► dm.mart_industry
```

Смотреть lineage: карточка таблицы `dds.fact_tender` → вкладка **Lineage** (центральный узел между сырьём и витринами).

Если том OpenMetadata/Superset пустой после пересоздания контейнеров:

```bash
python scripts/bootstrap_superset.py
python scripts/publish_lineage.py
```

### 6. Артефакты ЛР3

| Артефакт | Путь / адрес |
|---|---|
| DAG витрин | `dags/dm_it_tenders.py` |
| Логика витрин | `src/dm_load.py` |
| SQL витрин | `sql/init_dm.sql` |
| Compose: Superset / OM | `docker-compose.yaml` |
| Образ Superset | `superset/` |
| Bootstrap дашборда | `scripts/bootstrap_superset.py` |
| Публикация lineage | `scripts/publish_lineage.py` |
| Superset | http://localhost:8088 |
| OpenMetadata | http://localhost:8585 |
| Данные витрин | схема `dm` в БД `ods` |

### 7. Соответствие требованиям задания (ЛР3)

| Требование | Реализация |
|---|---|
| Superset и OpenMetadata в docker-compose | Сервисы `superset`, `openmetadata-server`, БД и migrate |
| Витрины на основе детального слоя | 5 таблиц в `dm`, SELECT из `dds.v_*` |
| ETL витрин + связь с DDS | DAG `dm_it_tenders`: Dataset + Sensor |
| ≥5 визуализаций с аргументацией | 3 bar + 1 line + 1 pie на дашборде «IT-тендеры» |
| Data Lineage ODS → DDS → витрины | `publish_lineage.py`, просмотр на `dds.fact_tender` |

---

# Сквозной запуск для демонстрации

```bash
cd lab1
docker compose up --build airflow-init
docker compose up -d
```

В Airflow снять паузу с DAG и сделать Trigger у `ods_geo_prices_to_postgres`. Далее автоматически:

1. `dds_it_tenders` — снежинка, SCD, факт, агрегаты;
2. `dq_it_tenders` — проверки качества;
3. `dm_it_tenders` — витрины.

Проверка данных: Adminer → `postgres-ods` / `ods` / `ods` — схемы `dds` и `dm`, таблица `dds.dq_result`.  
Проверка BI: Superset → дашборд «IT-тендеры».  
Проверка lineage: OpenMetadata → `dds.fact_tender` → Lineage.
