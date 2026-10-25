CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.tender_locations (
    id SERIAL PRIMARY KEY,
    tender_id TEXT NOT NULL UNIQUE,
    city TEXT,
    region TEXT,
    location_raw TEXT,
    url TEXT,
    source TEXT,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ods.tender_prices (
    id SERIAL PRIMARY KEY,
    tender_id TEXT NOT NULL UNIQUE,
    price_rub NUMERIC(18, 2),
    price_raw TEXT,
    currency TEXT NOT NULL DEFAULT 'RUB',
    price_kind TEXT NOT NULL DEFAULT 'nmck',
    url TEXT,
    source TEXT,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE ods.tender_prices
    ADD COLUMN IF NOT EXISTS price_kind TEXT NOT NULL DEFAULT 'nmck';

CREATE TABLE IF NOT EXISTS ods.tender_cards (
    id SERIAL PRIMARY KEY,
    tender_id TEXT NOT NULL UNIQUE,
    url TEXT,
    status TEXT,
    procedure_group TEXT,
    procedure_name TEXT,
    nmck_rub NUMERIC(18, 2),
    nmck_raw TEXT,
    price_kind TEXT NOT NULL DEFAULT 'nmck',
    application_start TIMESTAMPTZ,
    application_end TIMESTAMPTZ,
    contract_date DATE,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ods.tender_industries (
    id SERIAL PRIMARY KEY,
    tender_id TEXT NOT NULL,
    industry TEXT NOT NULL,
    UNIQUE (tender_id, industry)
);

CREATE INDEX IF NOT EXISTS idx_tender_locations_region
    ON ods.tender_locations (region);

CREATE INDEX IF NOT EXISTS idx_tender_prices_amount
    ON ods.tender_prices (price_rub);

CREATE INDEX IF NOT EXISTS idx_tender_cards_status
    ON ods.tender_cards (status);

CREATE INDEX IF NOT EXISTS idx_tender_industries_name
    ON ods.tender_industries (industry);
