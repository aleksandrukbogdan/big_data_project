CREATE SCHEMA IF NOT EXISTS dds;

CREATE TABLE IF NOT EXISTS dds.dim_date (
    date_key INTEGER PRIMARY KEY,
    full_date DATE NOT NULL UNIQUE,
    year SMALLINT NOT NULL,
    quarter SMALLINT NOT NULL,
    month SMALLINT NOT NULL,
    day SMALLINT NOT NULL,
    month_name TEXT NOT NULL,
    week_start DATE
);

ALTER TABLE dds.dim_date ADD COLUMN IF NOT EXISTS week_start DATE;

CREATE TABLE IF NOT EXISTS dds.dim_region (
    region_key SERIAL PRIMARY KEY,
    region_name TEXT NOT NULL UNIQUE,
    region_title TEXT
);

ALTER TABLE dds.dim_region ADD COLUMN IF NOT EXISTS region_title TEXT;

CREATE TABLE IF NOT EXISTS dds.dim_city (
    city_key SERIAL PRIMARY KEY,
    region_key INTEGER NOT NULL REFERENCES dds.dim_region (region_key),
    city_name TEXT NOT NULL,
    city_title TEXT,
    UNIQUE (region_key, city_name)
);

ALTER TABLE dds.dim_city ADD COLUMN IF NOT EXISTS city_title TEXT;

CREATE TABLE IF NOT EXISTS dds.dim_procedure (
    procedure_key SERIAL PRIMARY KEY,
    procedure_group TEXT NOT NULL,
    procedure_name TEXT NOT NULL DEFAULT '',
    UNIQUE (procedure_group, procedure_name)
);

CREATE TABLE IF NOT EXISTS dds.dim_industry (
    industry_key SERIAL PRIMARY KEY,
    industry_name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS dds.dim_tender (
    tender_sk SERIAL PRIMARY KEY,
    tender_id TEXT NOT NULL,
    url TEXT,
    status TEXT,
    procedure_group TEXT,
    procedure_name TEXT,
    valid_from TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    valid_to TIMESTAMPTZ,
    is_current BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_dim_tender_current
    ON dds.dim_tender (tender_id) WHERE is_current;

CREATE TABLE IF NOT EXISTS dds.fact_tender (
    tender_id TEXT PRIMARY KEY,
    tender_sk INTEGER NOT NULL REFERENCES dds.dim_tender (tender_sk),
    region_key INTEGER NOT NULL REFERENCES dds.dim_region (region_key),
    city_key INTEGER NOT NULL REFERENCES dds.dim_city (city_key),
    procedure_key INTEGER NOT NULL REFERENCES dds.dim_procedure (procedure_key),
    application_start_date_key INTEGER REFERENCES dds.dim_date (date_key),
    application_end_date_key INTEGER REFERENCES dds.dim_date (date_key),
    contract_date_key INTEGER REFERENCES dds.dim_date (date_key),
    nmck_rub NUMERIC(18, 2),
    application_hours NUMERIC(10, 2),
    days_to_contract INTEGER,
    industry_count INTEGER NOT NULL DEFAULT 0,
    has_card BOOLEAN NOT NULL DEFAULT FALSE,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE dds.fact_tender ADD COLUMN IF NOT EXISTS has_card BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS dds.bridge_tender_industry (
    tender_sk INTEGER NOT NULL REFERENCES dds.dim_tender (tender_sk),
    industry_key INTEGER NOT NULL REFERENCES dds.dim_industry (industry_key),
    PRIMARY KEY (tender_sk, industry_key)
);

CREATE TABLE IF NOT EXISTS dds.agg_region_procedure (
    region_key INTEGER NOT NULL REFERENCES dds.dim_region (region_key),
    procedure_key INTEGER NOT NULL REFERENCES dds.dim_procedure (procedure_key),
    tender_count INTEGER NOT NULL,
    with_nmck_count INTEGER NOT NULL,
    nmck_sum NUMERIC(18, 2) NOT NULL,
    nmck_avg NUMERIC(18, 2),
    PRIMARY KEY (region_key, procedure_key)
);

CREATE TABLE IF NOT EXISTS dds.agg_deadline_week (
    week_start DATE PRIMARY KEY,
    tender_count INTEGER NOT NULL,
    with_nmck_count INTEGER NOT NULL,
    nmck_sum NUMERIC(18, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS dds.dq_result (
    id SERIAL PRIMARY KEY,
    check_name TEXT NOT NULL,
    severity TEXT NOT NULL,
    passed BOOLEAN NOT NULL,
    observed TEXT,
    expected TEXT,
    details TEXT,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP VIEW IF EXISTS dds.v_tender_industry;
DROP VIEW IF EXISTS dds.v_tender;

CREATE VIEW dds.v_tender AS
SELECT
    f.tender_id,
    d.status,
    f.has_card,
    r.region_name,
    r.region_title,
    c.city_name,
    c.city_title,
    p.procedure_group,
    NULLIF(p.procedure_name, '') AS procedure_name,
    f.nmck_rub,
    f.application_hours,
    f.days_to_contract,
    f.industry_count,
    dstart.full_date AS application_start_date,
    dend.full_date AS application_end_date,
    dend.week_start AS application_end_week,
    dcon.full_date AS contract_date
FROM dds.fact_tender f
JOIN dds.dim_tender d ON d.tender_sk = f.tender_sk
JOIN dds.dim_region r ON r.region_key = f.region_key
JOIN dds.dim_city c ON c.city_key = f.city_key
JOIN dds.dim_procedure p ON p.procedure_key = f.procedure_key
LEFT JOIN dds.dim_date dstart ON dstart.date_key = f.application_start_date_key
LEFT JOIN dds.dim_date dend ON dend.date_key = f.application_end_date_key
LEFT JOIN dds.dim_date dcon ON dcon.date_key = f.contract_date_key;

CREATE VIEW dds.v_tender_industry AS
SELECT
    f.tender_id,
    d.status,
    r.region_title,
    i.industry_name,
    f.nmck_rub,
    f.has_card
FROM dds.fact_tender f
JOIN dds.dim_tender d ON d.tender_sk = f.tender_sk AND d.is_current
JOIN dds.dim_region r ON r.region_key = f.region_key
JOIN dds.bridge_tender_industry b ON b.tender_sk = f.tender_sk
JOIN dds.dim_industry i ON i.industry_key = b.industry_key;
