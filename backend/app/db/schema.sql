-- Idempotent schema migration. Runs on every app startup; must NEVER drop or
-- truncate data. Use CREATE ... IF NOT EXISTS for everything so existing
-- caches (companies, filings, text_chunks, etc.) survive a restart.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Companies (cached ticker -> CIK lookup, populated from EDGAR's company_tickers.json)
CREATE TABLE IF NOT EXISTS companies (
    cik         TEXT PRIMARY KEY,           -- 10-digit zero-padded CIK
    ticker      TEXT NOT NULL,
    name        TEXT NOT NULL,
    sic         TEXT,
    last_synced TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_companies_ticker ON companies(ticker);
CREATE INDEX IF NOT EXISTS idx_companies_name ON companies(lower(name));

-- Filings (one row per fetched SEC filing, cached by accession_number)
CREATE TABLE IF NOT EXISTS filings (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cik              TEXT NOT NULL REFERENCES companies(cik),
    ticker           TEXT NOT NULL,
    accession_number TEXT NOT NULL UNIQUE,    -- EDGAR's unique filing ID, e.g. '0000320193-25-000123'
    filing_type      TEXT NOT NULL,           -- '10-K', '10-Q', '8-K', etc.
    filing_date      DATE NOT NULL,
    period_of_report DATE,
    period_label     TEXT,                    -- 'Q3 2025', 'FY 2024'
    primary_doc_url  TEXT NOT NULL,
    fetched_at       TIMESTAMPTZ DEFAULT now(),
    status           TEXT DEFAULT 'processing',  -- 'processing', 'ready', 'failed'
    error_message    TEXT,
    page_count       INT,
    chunk_count      INT,
    metric_count     INT
);
CREATE INDEX IF NOT EXISTS idx_filings_cik_type ON filings(cik, filing_type, filing_date DESC);
CREATE INDEX IF NOT EXISTS idx_filings_ticker_type ON filings(ticker, filing_type, filing_date DESC);
CREATE INDEX IF NOT EXISTS idx_filings_status ON filings(status);

-- Text chunks (for narrative/unstructured retrieval)
CREATE TABLE IF NOT EXISTS text_chunks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filing_id   UUID NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    chunk_text  TEXT NOT NULL,
    page_num    INT,
    section     TEXT,
    chunk_index INT,
    embedding   vector(768),                  -- FinBERT output
    created_at  TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON text_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_chunks_filing ON text_chunks(filing_id);
CREATE INDEX IF NOT EXISTS idx_chunks_section ON text_chunks(section);

-- Extracted tables (HTML tables parsed to structured JSON)
CREATE TABLE IF NOT EXISTS extracted_tables (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filing_id  UUID NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    page_num   INT,
    table_type TEXT,
    headers    JSONB,
    rows       JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tables_filing ON extracted_tables(filing_id);

-- Extracted metrics (XBRL-sourced first, HTML-table fallback)
CREATE TABLE IF NOT EXISTS metrics (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filing_id     UUID NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    metric_name   TEXT NOT NULL,
    value         NUMERIC,
    prior_value   NUMERIC,
    change_pct    NUMERIC,
    unit          TEXT DEFAULT 'USD',
    period        TEXT,
    prior_period  TEXT,
    source        TEXT NOT NULL,              -- 'xbrl' or 'html_table'
    xbrl_concept  TEXT,                       -- e.g. 'us-gaap:Revenues' (when source = 'xbrl')
    page_num      INT,                        -- when source = 'html_table'
    table_type    TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_metrics_filing ON metrics(filing_id);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(metric_name);

-- Query logs (analytics — one row per query, never deleted)
CREATE TABLE IF NOT EXISTS query_logs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question         TEXT NOT NULL,
    companies        TEXT[],
    query_type       TEXT,
    filings_used     TEXT[],
    confidence       TEXT,
    cache_hit        BOOLEAN,
    response_time_ms INT,
    created_at       TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_query_logs_created ON query_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_query_logs_companies ON query_logs USING GIN(companies);
