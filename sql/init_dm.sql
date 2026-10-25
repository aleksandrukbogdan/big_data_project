CREATE SCHEMA IF NOT EXISTS dm;

CREATE TABLE IF NOT EXISTS dm.mart_region (
    region_title TEXT PRIMARY KEY,
    tender_count INTEGER NOT NULL,
    with_nmck_count INTEGER NOT NULL,
    nmck_sum NUMERIC(18, 2) NOT NULL,
    nmck_avg NUMERIC(18, 2)
);

CREATE TABLE IF NOT EXISTS dm.mart_procedure (
    procedure_group TEXT PRIMARY KEY,
    tender_count INTEGER NOT NULL,
    with_nmck_count INTEGER NOT NULL,
    nmck_sum NUMERIC(18, 2) NOT NULL,
    nmck_avg NUMERIC(18, 2)
);

CREATE TABLE IF NOT EXISTS dm.mart_week (
    week_start DATE PRIMARY KEY,
    tender_count INTEGER NOT NULL,
    nmck_sum NUMERIC(18, 2) NOT NULL
);

CREATE TABLE IF NOT EXISTS dm.mart_industry (
    industry_name TEXT PRIMARY KEY,
    tender_count INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS dm.mart_price_coverage (
    price_state TEXT PRIMARY KEY,
    tender_count INTEGER NOT NULL
);
