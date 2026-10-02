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
    url TEXT,
    source TEXT,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tender_locations_region
    ON ods.tender_locations (region);

CREATE INDEX IF NOT EXISTS idx_tender_prices_amount
    ON ods.tender_prices (price_rub);
