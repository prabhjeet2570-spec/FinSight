CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Documents table
CREATE TABLE IF NOT EXISTS documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename    TEXT,
    company     TEXT NOT NULL,
    filing_type TEXT,
    period      TEXT,
    uploaded_at TIMESTAMPTZ DEFAULT now(),
    page_count  INT,
    status      TEXT DEFAULT 'processing'
);

-- Text chunks (for narrative/unstructured retrieval)
CREATE TABLE IF NOT EXISTS text_chunks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    chunk_text  TEXT NOT NULL,
    page_num    INT,
    section     TEXT,
    chunk_index INT,
    embedding   vector(768),
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Extracted tables (structured data as JSON)
CREATE TABLE IF NOT EXISTS extracted_tables (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    page_num    INT,
    table_type  TEXT,
    headers     JSONB,
    rows        JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Extracted metrics (flattened key numbers for fast lookup)
CREATE TABLE IF NOT EXISTS metrics (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id   UUID REFERENCES documents(id) ON DELETE CASCADE,
    metric_name   TEXT NOT NULL,
    value         NUMERIC,
    prior_value   NUMERIC,
    change_pct    NUMERIC,
    unit          TEXT DEFAULT 'millions USD',
    period        TEXT,
    prior_period  TEXT,
    page_num      INT,
    table_type    TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON text_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON text_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_section ON text_chunks(section);
CREATE INDEX IF NOT EXISTS idx_tables_document ON extracted_tables(document_id);
CREATE INDEX IF NOT EXISTS idx_metrics_document ON metrics(document_id);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(metric_name);
