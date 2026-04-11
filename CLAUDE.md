# FinSight

## What This Is

A financial intelligence tool that combines document RAG with SEC EDGAR structured data to analyze any US public company's finances. Users can upload SEC filings (10-Q, 10-K, press releases) for deep narrative analysis, search any company by ticker for instant financial metrics, or do both for verified cross-referenced analysis.

**This is NOT a generic document Q&A tool.** It has domain-specific financial intelligence: FinBERT embeddings, financial jargon understanding, computed ratios, XBRL-verified metrics, and grounded sentiment analysis. That's what differentiates it from the dozens of "upload PDF and ask questions" RAG demos.

**This is a portfolio project for Prabhjeet Singh** (NYU MS CS student). It should demonstrate strong backend/ML engineering skills and domain-specific intelligence design.

---

## Core Requirements (Non-Negotiable)

1. **Strictly grounded answers** — answers come ONLY from uploaded documents and/or SEC EDGAR structured data. If the answer isn't available, say "I don't have this information." Never hallucinate.
2. **Dual-path extraction** — both structured table extraction AND unstructured text extraction from PDFs. Not just text-only RAG.
3. **Three input modes** — upload a filing, search a company by ticker, or both combined.
4. **Up to 4 documents** at once for cross-document analysis.
5. **10MB per file max**, 40MB total across all uploads.
6. **Financial sentiment analysis** grounded in within-document comparisons and XBRL historical data.
7. **Free deployment** — $0 cost using free tiers only.
8. **Open-source models** for embedding and sentiment (no paid API for these).

---

## What Makes This Finance-Specific (Not Generic RAG)

### Financial Intelligence Layer

This is encoded domain knowledge that ships with the app — not "learned" at runtime:

**1. Metric Synonym Dictionary (~60 entries)**
Maps financial terms across different companies' reporting styles:
- "revenue" = "net sales" = "total net sales" = "total revenue" = "net revenue" = "top line"
- "net_income" = "net earnings" = "bottom line" = "profit after tax"
- "cost_of_revenue" = "cost of sales" = "cost of goods sold" = "COGS"
- etc.

SEC filings use predictable vocabulary — there are only so many ways to say "revenue." ~60 core concepts with 3-4 synonyms each covers 90%+ of queries.

**2. Financial Jargon Map (~30 entries)**
Maps analyst shorthand to actual metrics:
- "top line" → revenue
- "bottom line" → net income
- "burn rate" → net cash used in operations
- "margins" → gross profit / revenue
- "leverage" → total debt / total equity

**3. Computable Ratio Definitions (~15-20 formulas)**
Standard financial ratios computed from extracted/XBRL metrics:
- Gross margin = gross_profit / revenue
- Operating margin = operating_income / revenue
- Net margin = net_income / revenue
- YoY growth = (current - prior) / prior
- Revenue mix = segment_revenue / total_revenue

When a user asks "what's Apple's gross margin?" — we don't ask the LLM to figure it out. We look up gross_profit and revenue from structured data, compute the ratio ourselves, and present it.

**4. FinBERT for Domain-Specific Understanding**
Finance-trained models instead of generic ones (see Tech Stack section).

**5. XBRL Integration for Verified Structured Data**
Direct access to SEC's machine-readable financial data via EdgarTools (see XBRL section).

---

## Three Input Modes

The UI doesn't expose "modes" — the user just gives us what they have and we provide the best analysis possible.

### Mode 1: Ticker Search (no upload needed)
User types "Apple" or "AAPL" → we pull structured data from SEC EDGAR XBRL → instant financial analysis.

Available: revenue trends, computed ratios, cross-company comparisons, historical metrics — all from XBRL.
Not available: narrative analysis (MD&A, risk factors, management commentary) — that requires the actual document.

### Mode 2: Document Upload
User uploads a 10-Q PDF → extract text + tables → full narrative and numerical analysis.
We auto-detect the company from the document and also pull XBRL data to cross-reference.

### Mode 3: Combined (most powerful)
Ticker search + document upload. Verified metrics from XBRL + narrative analysis from the document.
Cross-verification: check if pdfplumber-extracted numbers match XBRL — if they don't, trust XBRL.

### What each mode can answer

| Query type | Ticker only | Upload only | Combined |
|-----------|-------------|-------------|----------|
| "What was revenue?" | Yes (XBRL) | Yes (extracted) | Yes (verified) |
| "Revenue trend last 4 quarters?" | Yes (XBRL historical) | Only if 4 docs uploaded | Yes |
| "What did management say about AI?" | No — needs document | Yes | Yes |
| "What are the risk factors?" | No — needs document | Yes | Yes |
| "Compare Apple vs Microsoft margins" | Yes (XBRL both) | No | Yes |
| "What's the gross margin?" | Yes (computed from XBRL) | Yes (computed from extracted) | Yes (verified) |
| "Is the outlook positive?" | Partial (from metrics trend) | Yes (MD&A sentiment) | Yes (both signals) |

When a query needs data we don't have, we tell the user specifically what to add:
> "I don't have the full filing text — I only have XBRL metrics for Apple. Upload the 10-Q to analyze management commentary and narrative sections."

---

## XBRL Integration via EdgarTools

Instead of writing raw EDGAR API calls, we use [EdgarTools](https://github.com/dgunning/edgartools) — a mature Python library that:
- Handles company search by name/ticker
- Parses XBRL into structured Python objects and DataFrames
- Learned mappings from 32,000+ real SEC filings
- Handles all edge cases (different reporting styles, IFRS vs US-GAAP, etc.)
- Free, no API keys, no rate limits

**Why XBRL matters:**
- XBRL data has 0.11% scaling errors vs 8.16% for text extraction (per XBRL.org research)
- Every number in a 10-Q has a machine-readable XBRL tag — no extraction needed
- Historical data going back years — instant trend analysis
- Cross-company comparison using standardized concepts

### EDGAR API endpoints we use (via EdgarTools)

```python
# Company search
Company("AAPL")  # or Company.search("Apple")

# Get financial facts — every metric ever reported
company.get_facts()  # returns structured DataFrame

# Get specific filing
company.get_filings(form="10-Q").latest()

# Get financial statements
filing.financials  # income statement, balance sheet, cash flow — all structured
```

### New API endpoints for ticker search

```
GET  /api/companies/search?q=apple      -- Search companies by name/ticker
GET  /api/companies/{ticker}/financials  -- Structured metrics from XBRL
GET  /api/companies/{ticker}/ratios      -- Computed financial ratios
GET  /api/companies/{ticker}/compare?with=MSFT  -- Cross-company comparison
```

---

## Tech Stack (Decided)

| Layer | Choice | Why |
|-------|--------|-----|
| **Backend** | FastAPI (Python) | Best ML/NLP ecosystem, async, auto-docs |
| **Frontend** | React + Vite + TypeScript | Simple SPA, no SSR needed, deploys as static files on Vercel |
| **Database** | PostgreSQL + pgvector on Neon | One DB for both relational data AND vector search. Free 512MB. |
| **PDF Extraction** | pdfplumber | Handles all SEC filings (text-based PDFs). Free, fast, reliable. |
| **VLM Fallback** | Deferred to later phase | For scanned/graphical PDFs. Not needed for SEC filings. |
| **XBRL Data** | EdgarTools (Python library) | Structured SEC financial data. Learned mappings from 32K+ filings. Free. |
| **Embeddings** | ProsusAI/finbert or finance-tuned model | Finance-specific embeddings — understands that "bearish" and "declining revenue" are related. Generic models miss this. |
| **Sentiment** | ProsusAI/finbert (sentiment variant) | Trained on 10,000+ financial texts. Knows "restructuring charges" is negative, "strategic investment" is positive. |
| **Generation LLM** | Gemini 2.0 Flash (free tier) | 15 RPM, 1M tokens/min — most generous free tier |
| **Orchestration** | Roll our own (no LangChain/LlamaIndex framework) | Full control, less abstraction to debug. Use utilities selectively. |
| **Chunking** | LangChain RecursiveCharacterTextSplitter | Just this one utility, not the whole framework |
| **Financial Intelligence** | Hand-built synonym dict + jargon map + ratio definitions | ~60 synonyms, ~30 jargon mappings, ~20 ratio formulas. Domain knowledge encoded as data. |

### Why These Choices

- **pgvector over Pinecone/Qdrant/ChromaDB**: We need BOTH structured SQL queries (metrics lookup) AND vector similarity search (text retrieval). pgvector does both in one database. Separate vector DB would mean managing two services + two free tiers.
- **pdfplumber over Unstructured.io/LlamaParse**: SEC filings are text-based PDFs — pdfplumber handles them perfectly. No need for heavier tools. VLM fallback is for later when we support scanned/graphical docs.
- **React+Vite over Next.js**: This is an interactive tool, not a content site. No SEO needed, no SSR needed. Simpler build.
- **Roll our own over LangChain**: For a focused app with clear retrieval paths, direct code is cleaner. LangChain adds abstraction we'd fight when debugging.
- **Gemini Flash over GPT-4o/Groq**: Most generous free tier by far. Good quality for financial reasoning.
- **FinBERT over all-MiniLM-L6-v2**: Finance-specific embeddings give better retrieval for financial queries. "Profitability concerns" matches "operating margin compression" — generic models miss this. Similar RAM footprint (~110MB vs ~90MB).
- **EdgarTools over raw EDGAR API**: Mature library with 32K+ filing mappings, handles XBRL edge cases we'd spend weeks on. Free, no API key.

---

## Architecture

### Processing Pipeline (Upload -> Ready)

```
User uploads PDF (max 4 files, 10MB each)
        |
        v
   Metadata Extraction
   (company name, filing type, period from filename + first page)
        |
        v
   Auto-detect company -> also pull XBRL data from EDGAR via EdgarTools
        |
        v
   Page-by-Page Classification
   (TABLE_HEAVY or TEXT_HEAVY based on pdfplumber table detection)
        |
   +---------+---------+
   v                   v
Table Pages          Text Pages
   |                   |
   v                   v
pdfplumber          pdfplumber
extract_tables()    extract_text()
   |                   |
   v                   v
Quality Check        Section Detection
(empty cells,        (regex for "Item 2.", "RISK FACTORS", etc.)
inconsistent cols,   + Chunking (RecursiveCharacterTextSplitter)
no numeric data)        |
   |                   v
   |              Embed chunks (FinBERT)
   |              Store in text_chunks table
   v
Parse to JSON
Store in extracted_tables
Flatten key metrics -> metrics table
Cross-verify against XBRL data (trust XBRL if mismatch)
```

### Ticker Search Pipeline (no upload)

```
User types company name or ticker
        |
        v
   EdgarTools: Company search
   Returns: {name, ticker, CIK}
        |
        v
   EdgarTools: Get financial facts (XBRL)
   Returns: structured metrics for all reported periods
        |
        v
   Store in metrics table (source: 'xbrl')
   Compute ratios (margins, growth rates, revenue mix)
        |
        v
   Ready for queries — numerical and comparison only
   (narrative queries prompt user to upload a filing)
```

### pdfplumber Failure Detection

pdfplumber doesn't crash — it returns bad data silently. Detect with:
- No tables found but page has many lines/rects (>20) -> graphical table, needs VLM
- Table found but >40% empty cells -> misaligned extraction
- Table found but inconsistent column counts across rows
- Table found but no numeric data (financial tables MUST have numbers)

When quality check fails: log it, flag the page. VLM fallback is deferred to later phase.

### Query Pipeline (Question -> Answer)

```
User question: "How's the top line looking?"
        |
        v
   Financial Jargon Resolution
   "top line" -> "revenue" (from jargon map)
        |
        v
   Metric Synonym Expansion
   "revenue" -> ["revenue", "net sales", "total net sales", ...] (from synonym dict)
        |
        v
   Query Classifier (Gemini Flash, few-shot)
   Returns: {type, entities, target_docs, expanded_terms}
        |
        v
   Route by Type:
   - NUMERICAL   -> metrics table SQL lookup (using expanded synonyms)
   - NARRATIVE    -> text_chunks vector search (FinBERT embeddings)
   - COMPARISON   -> both paths merged
   - SENTIMENT    -> metrics (for numbers) + MD&A chunks (for qualitative) + FinBERT sentiment
   - CROSS_DOC    -> metrics from multiple documents
   - CROSS_COMPANY -> XBRL data from multiple companies
   - UNSUPPORTED  -> redirect with specific guidance on what data to add
        |
        v
   Context Assembly
   (combine metrics + XBRL data + table rows + text chunks, deduplicate, rank)
        |
        v
   Grounded Answer Generation (Gemini Flash)
   Strict system prompt: answer ONLY from context, cite sources (page numbers for PDF,
   "SEC EDGAR XBRL" for structured data), say "not available" if unsure.
        |
        v
   Response: {answer, citations, confidence, query_type, sentiment?, computed_ratios?}
```

### SEC Filing Section Detection

Standard sections to tag chunks with (for relevance boosting):
- Item 1: Financial Statements (tables)
- Item 2: MD&A (narrative — gold mine for analysis questions)
- Item 3: Quantitative Disclosures
- Item 4: Controls
- Part II Item 1: Legal
- Part II Item 1A: Risk Factors

A question about "risk" should prefer chunks from Risk Factors over random mentions elsewhere.

### Sentiment Analysis Approach

Two signal sources, both grounded:

**Quantitative (from metrics/XBRL):**
- Extract YoY changes (Revenue +9.6%, Net Income +9.3%, etc.)
- Trend detection across quarters if multiple periods available
- All numbers sourced from document tables or XBRL

**Qualitative (from document text + FinBERT):**
- Run FinBERT sentiment on MD&A chunks
- FinBERT was trained on 10,000+ financial texts — knows "restructuring charges" is negative, "strategic investment in growth" is positive
- Extract qualitative signals: "increased primarily due to...", "decline was driven by..."

Combined sentiment is always grounded with explicit sourcing — never speculate beyond what the data says.

---

## Database Schema

```sql
CREATE EXTENSION vector;

-- Documents table
CREATE TABLE documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename    TEXT,                -- NULL for ticker-only searches
    company     TEXT NOT NULL,
    ticker      TEXT,                -- e.g., 'AAPL'
    cik         TEXT,                -- SEC CIK number
    filing_type TEXT,                -- '10-Q', '10-K', 'press-release', 'xbrl-only'
    period      TEXT,                -- 'Q3 2025'
    fiscal_year TEXT,                -- 'FY2025'
    source      TEXT DEFAULT 'upload', -- 'upload' or 'xbrl'
    uploaded_at TIMESTAMPTZ DEFAULT now(),
    page_count  INT,
    status      TEXT DEFAULT 'processing'  -- 'processing', 'ready', 'failed'
);

-- Text chunks (for narrative/unstructured retrieval)
CREATE TABLE text_chunks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    chunk_text  TEXT NOT NULL,
    page_num    INT,
    section     TEXT,              -- 'MD&A', 'Risk Factors', 'Notes', etc.
    chunk_index INT,
    embedding   vector(768),      -- FinBERT output (768-dim)
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Extracted tables (structured data as JSON)
CREATE TABLE extracted_tables (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    page_num    INT,
    table_type  TEXT,              -- 'income_statement', 'balance_sheet', etc.
    period      TEXT,
    headers     JSONB,
    rows        JSONB NOT NULL,   -- [{label, values: {current, prior, change_pct}}]
    raw_text    TEXT,             -- searchable text version of table
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Extracted metrics (flattened key numbers for fast lookup)
CREATE TABLE metrics (
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
    source        TEXT DEFAULT 'extracted',  -- 'extracted' (from PDF) or 'xbrl' (from EDGAR)
    verified      BOOLEAN DEFAULT FALSE,     -- TRUE if extracted value matches XBRL
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX idx_chunks_embedding ON text_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_chunks_document ON text_chunks(document_id);
CREATE INDEX idx_chunks_section ON text_chunks(section);
CREATE INDEX idx_tables_document ON extracted_tables(document_id);
CREATE INDEX idx_metrics_document ON metrics(document_id);
CREATE INDEX idx_metrics_name ON metrics(metric_name);
CREATE INDEX idx_metrics_source ON metrics(source);
CREATE INDEX idx_documents_ticker ON documents(ticker);
```

Changes from earlier version:
- `documents` table now has `ticker`, `cik`, `source` fields for XBRL-only entries
- `text_chunks` embedding is now `vector(768)` for FinBERT (was 384 for MiniLM)
- `metrics` table now has `source` ('extracted' vs 'xbrl') and `verified` (cross-referenced) fields
- Added indexes for `section`, `source`, `ticker`

---

## API Design

```
# Document management
POST   /api/documents/upload        -- Upload 1-4 PDFs, returns document IDs
GET    /api/documents                -- List all uploaded documents
GET    /api/documents/{id}/status    -- Processing status
GET    /api/documents/{id}/metrics   -- All extracted metrics for a document
GET    /api/documents/{id}/tables    -- All extracted tables for a document
DELETE /api/documents/{id}           -- Remove document + all derived data (cascade)

# Company search (XBRL / EdgarTools)
GET    /api/companies/search?q=apple       -- Search companies by name/ticker
GET    /api/companies/{ticker}/financials   -- Structured metrics from XBRL
GET    /api/companies/{ticker}/ratios       -- Computed financial ratios
GET    /api/companies/{ticker}/compare?with=MSFT  -- Cross-company comparison

# Query
POST   /api/query                    -- Ask a question
       Body: {question, document_ids?: [...], ticker?: string}
       Response: {answer, citations, confidence, query_type, sentiment?, ratios?}

# Health
GET    /health                       -- Health check
```

---

## UI Design

### Core Principle
One smart input — no mode selection. The system detects what the user gave it and provides the best analysis possible.

### Landing State
```
┌────────────────────────────────��─────────────────────────┐
│  FinSight                                                │
├────────────────────────────────���────────────────────────��┤
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │  Search a company or drop a filing...            │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  One input. Type "Apple" or "AAPL" for instant analysis. │
│  Drop a PDF for deep document analysis.                  │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### After Ticker Search
```
┌───────────────────��───────────────────────────────────��──┐
│  Apple Inc. (AAPL)               │  Chat Panel           │
│  Latest: 10-Q Q3 2025            │                       │
│                                   │  Q: How has iPhone    │
│  Key Metrics (XBRL)              │  been doing?          │
│  Revenue      $94.0B   +9.6% ▲   │                       │
│  Net Income   $23.4B   +9.3% ▲   │  A: Based on XBRL    │
│  Gross Margin  46.3%   +0.3% ▲   │  data, iPhone rev...  │
│  EPS          $1.40    +12%  ▲   │  [SEC EDGAR]          │
│                                   │                       │
│  Quarterly Trend                 │                       │
│  Rev: Q1→Q2→Q3 (accelerating)   │                       │
│                                   │                       │
│  Upload a filing for deeper      │                       │
│  analysis (MD&A, risk factors)   │                       │
└──────────────────────────────────────────────────────────┘
```

### After Document Upload
Same layout but with richer capabilities (narrative questions work).
Auto-detects company → also pulls XBRL data.
Shows "verified" badge on metrics that match XBRL.

### Adaptive Chat Responses
When the user asks something that needs data we don't have:
> "I don't have the full filing text — I only have XBRL metrics for Apple. Upload the 10-Q to analyze management commentary."
> [Upload a filing]

---

## Deployment Architecture

```
Vercel (Frontend)              Render (Backend)              Neon (Database)
React + Vite                   FastAPI + Python               PostgreSQL + pgvector
Static files                   512MB RAM free tier            512MB storage free tier
No RAM concern                 Spins down after 15min idle    Managed, scales to zero
                     <-- API calls (HTTPS) -->     <-- SQL + pgvector queries -->
                                    |
                              ┌─────┴─────┐
                              v           v
                        Gemini Flash   SEC EDGAR
                        (free API)     (free, via EdgarTools)
                        15 RPM         10 req/sec
```

### RAM Budget (Render Free Tier = 512MB)

```
FastAPI + dependencies:     ~80MB
pdfplumber (on demand):     ~30MB
FinBERT model:              ~110MB  (lazy loaded, shared between embedding + sentiment)
EdgarTools:                 ~20MB
PDF in memory (1 file):     ~10MB   (process files one at a time, not all 4 at once)
Working overhead:           ~50MB
─────────────────────────────────
Total:                      ~300MB  (fits in 512MB with headroom)
```

Cold start: Render free tier takes ~30s to boot after idle. Show "waking up the server..." in the UI.

---

## Project Structure

```
finsight/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, lifespan
│   │   ├── config.py            # Environment variables
│   │   ├── db/
│   │   │   ├── connection.py    # Async Postgres connection pool
│   │   │   └── schema.sql       # Table definitions
│   │   ├── models/              # Pydantic request/response schemas
│   │   │   ├── document.py
│   │   │   ├── company.py
│   │   │   └── query.py
│   │   ├── routers/             # API route handlers
│   │   │   ├── documents.py
│   │   │   ├── companies.py
│   │   │   └── query.py
│   │   ├── services/            # Business logic
│   │   │   ├── extraction.py    # PDF -> tables + text
│   │   │   ├── chunking.py      # Text -> chunks
│   │   │   ├── embedding.py     # Chunks -> vectors (FinBERT)
│   │   │   ├── edgar.py         # EdgarTools XBRL integration
│   │   │   ├── classifier.py    # Query classification
│   │   │   ├── retrieval.py     # Vector search + SQL lookup + XBRL
│   │   │   ├── generation.py    # Gemini Flash answer generation
│   │   │   └── sentiment.py     # FinBERT sentiment analysis
│   │   ├── finance/             # Financial domain knowledge
│   │   │   ├── synonyms.py      # Metric synonym dictionary (~60 entries)
│   │   │   ├── jargon.py        # Financial jargon map (~30 entries)
│   │   │   └── ratios.py        # Computable ratio definitions (~20 formulas)
│   │   └── utils/
│   │       └── section_detector.py  # SEC filing section regex
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile               # For Render deployment
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   │   ├── SearchBar.tsx        # Unified search/upload input
│   │   │   ├── CompanyPanel.tsx     # Company info + metrics + trends
│   │   │   ├── DocumentPanel.tsx    # Uploaded docs list + status
│   │   │   ├── ChatPanel.tsx        # Q&A interface
│   │   │   ├── MetricsCard.tsx      # Key metrics display with verified badge
│   │   │   └── UploadZone.tsx       # Drag-drop file upload
│   │   ├── hooks/
│   │   │   └── useApi.ts
│   │   ├── types/
│   │   │   └── index.ts
│   │   └── config.ts
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── CLAUDE.md                    # This file
├── .gitignore
└── README.md
```

---

## Build Plan

### Phase 1: Project Setup + Database
**Goal:** Skeleton running locally, database connected

- [ ] Initialize project structure (backend + frontend dirs)
- [ ] FastAPI app with `/health` endpoint
- [ ] config.py loading env vars (DATABASE_URL, GEMINI_API_KEY, SEC_EDGAR_USER_AGENT)
- [ ] Async Postgres connection using asyncpg
- [ ] schema.sql with all 4 tables + pgvector extension + all indexes
- [ ] DB initialization on startup (run schema if tables don't exist)
- [ ] React + Vite + TypeScript scaffold
- [ ] Placeholder frontend page with FinSight branding
- [ ] .gitignore, .env.example, README.md
- **Test:** `GET /health` returns 200, database connects, frontend renders

### Phase 2: PDF Upload + Extraction Pipeline
**Goal:** Upload a PDF, extract text and tables, store in database

- [ ] `POST /api/documents/upload` — accept PDF, validate size (10MB), save metadata
- [ ] Metadata detection — parse company, filing type, period from filename + first page
- [ ] Page-by-page processing with pdfplumber
- [ ] Table extraction + quality validation (empty cells, inconsistent cols, no numbers)
- [ ] Table parsing to structured JSON
- [ ] Metric flattening — extract key numbers into metrics table
- [ ] Text extraction + section detection (regex for SEC filing sections)
- [ ] Text chunking with RecursiveCharacterTextSplitter
- [ ] Processing status tracking (processing -> ready/failed)
- [ ] `GET /api/documents/{id}/status`
- [ ] `GET /api/documents/{id}/tables`
- [ ] `GET /api/documents/{id}/metrics`
- **Test:** Upload Apple 10-Q, verify extracted tables and metrics match actual PDF data

### Phase 3: XBRL Integration + Company Search
**Goal:** Search any company by ticker, get structured financial data instantly

- [ ] EdgarTools integration — company search, financial facts, filing history
- [ ] `GET /api/companies/search?q=` — search by name/ticker
- [ ] `GET /api/companies/{ticker}/financials` — structured metrics from XBRL
- [ ] Store XBRL metrics in metrics table (source: 'xbrl')
- [ ] Cross-verification — when PDF is uploaded AND XBRL available, compare extracted vs XBRL values, mark verified
- [ ] Computed financial ratios from XBRL data (margins, growth rates, revenue mix)
- [ ] `GET /api/companies/{ticker}/ratios`
- [ ] Financial intelligence data files — synonyms.py, jargon.py, ratios.py
- **Test:** Search "AAPL", get structured financials. Upload Apple 10-Q, verify metrics match XBRL.

### Phase 4: Embeddings + Retrieval
**Goal:** Chunks are searchable via finance-specific vector similarity and structured SQL

- [ ] Lazy-load FinBERT on first request
- [ ] Generate FinBERT embeddings for all text chunks during upload processing
- [ ] Store embeddings in pgvector (768-dim)
- [ ] Vector search function — query embedding vs stored chunk embeddings, return top-K
- [ ] Structured search function — metric name lookup via SQL with synonym expansion
- [ ] Hybrid retrieval — combine vector search + SQL metrics + XBRL data, deduplicate, rank
- [ ] `DELETE /api/documents/{id}` — cascade delete
- [ ] `GET /api/documents` — list all documents
- **Test:** Upload Apple 10-Q, search "profitability concerns" -> should match "operating margin" chunks (FinBERT understands this)

### Phase 5: Query Pipeline + Answer Generation
**Goal:** Ask a question in natural language, get a grounded answer with citations

- [ ] Financial jargon resolution (jargon map)
- [ ] Metric synonym expansion (synonym dict)
- [ ] Query classifier — Gemini Flash few-shot prompt returning {type, entities, target_docs, expanded_terms}
- [ ] Routing logic (NUMERICAL/NARRATIVE/COMPARISON/SENTIMENT/CROSS_DOC/CROSS_COMPANY/UNSUPPORTED)
- [ ] Context assembly — merge metrics + XBRL data + tables + chunks, deduplicate, rank by relevance
- [ ] Grounded generation — Gemini Flash with strict system prompt
- [ ] Response formatting — {answer, citations, confidence, query_type}
- [ ] Adaptive "missing data" responses — tell user what to add for better answers
- [ ] `POST /api/query` endpoint
- **Test:** Ask varied question types. "How's the top line?" should resolve to revenue via jargon map.

### Phase 6: Frontend
**Goal:** Usable UI — search companies, upload docs, ask questions, see answers

- [ ] Unified search bar — detects ticker vs file drop
- [ ] Company panel — metrics display, trends, verified badges
- [ ] Document panel — upload (drag-drop, 10MB limit), processing status
- [ ] Chat panel — question input, answer display with citations and confidence
- [ ] Metrics card component — key numbers with YoY change arrows
- [ ] Error handling — file too large, upload failed, server cold start ("waking up...")
- [ ] Connect all components to backend APIs
- **Test:** Full browser flow — search ticker → see metrics → upload filing → ask narrative question → get cited answer

### Phase 7: Sentiment + Cross-Company + Deploy
**Goal:** Sentiment analysis, cross-company comparison, deployed live at $0

- [ ] FinBERT sentiment on MD&A chunks — quantitative + qualitative signals combined
- [ ] Cross-document queries — query across multiple uploaded documents
- [ ] Cross-company comparison — compare metrics from XBRL for different tickers
- [ ] `GET /api/companies/{ticker}/compare?with=MSFT`
- [ ] Deploy backend to Render (Dockerfile, env vars)
- [ ] Deploy frontend to Vercel
- [ ] Neon database already provisioned
- [ ] CORS configuration for production domains
- [ ] Cold-start UX handling in frontend
- **Test:** Full flow on live deployed URL. Compare Apple vs Microsoft margins. Get sentiment analysis on uploaded 10-Q.

---

## Competitive Landscape

These decisions are informed by research into existing projects (conducted 2026-04-11).

### Closest Existing Projects

| Project | What it does | What it doesn't do |
|---------|-------------|-------------------|
| [SEC Insights](https://github.com/run-llama/sec-insights) (LlamaIndex) | Most polished SEC RAG app. Next.js + FastAPI + pgvector + OpenAI. PDF viewer with citation highlighting. | No XBRL, no structured tables, no metrics computation, no sentiment, no ticker search. Text-only RAG. Paid (OpenAI). |
| [FinanceRAG](https://github.com/nik2401/FinanceRAG-Investment-Research-Assistant) | FastAPI + PostgreSQL + Gemini. SEC EDGAR integration. | No structured table extraction, no XBRL cross-referencing, no computed ratios, no FinBERT. |
| [FinSage](https://arxiv.org/abs/2504.14493) (research paper) | Multi-modal preprocessing, HyDE query expansion, DPO-tuned re-ranking. 92.51% recall. | Academic — not a deployable web app with UI. |
| [EdgarTools](https://github.com/dgunning/edgartools) | Best XBRL library. Parses all filing types. 32K+ filing mappings. | Library only — no RAG, no Q&A, no end-user UI. |
| [Finbot](https://github.com/deepakb41/Finbot) | LangChain + RAG for 10-K/10-Q. Conversational. | Text-only RAG, no structured data, no XBRL. |

### What FinSight does that none of them do

1. **RAG + XBRL in one app** — narrative analysis from documents + verified structured metrics from EDGAR. Nobody combines both.
2. **Ticker-only mode** — get financial analysis without uploading anything. Most tools require file upload.
3. **Computed financial ratios** — margins, growth rates, revenue mix computed from structured data. Others return text answers.
4. **FinBERT domain-specific retrieval + sentiment** — finance-trained embeddings and sentiment, not generic models.
5. **XBRL cross-verification** — when PDF is uploaded, verify extracted numbers against XBRL. Nobody does this.
6. **Cross-company comparison** — compare any two public companies using standardized XBRL data.
7. **Free deployment** — $0 total cost. SEC Insights requires paid OpenAI API.

### What existing projects do better (learn from them)

- **SEC Insights**: PDF viewer with citation highlighting — worth studying for Phase 2+ UI
- **FinSage**: HyDE query expansion and DPO re-ranking — worth reading the paper for retrieval improvements

---

## Design Decisions Log

These decisions have been discussed and confirmed. Don't re-debate them in future sessions.

| # | Decision | Choice | Reason | Date |
|---|----------|--------|--------|------|
| 1 | Project name | FinSight | Finance + Insight. Short, memorable, doesn't box into just "earnings" | 2026-04-11 |
| 2 | Frontend framework | React + Vite (not Next.js) | SPA tool, no SSR/SEO needed, simpler | 2026-04-11 |
| 3 | Database | PostgreSQL + pgvector on Neon (not Pinecone/Qdrant) | One DB for relational + vector, one free tier | 2026-04-11 |
| 4 | PDF extraction | pdfplumber (not Unstructured.io/LlamaParse) | SEC filings are text-based, pdfplumber handles them | 2026-04-11 |
| 5 | VLM fallback | Deferred to later phase | Blows RAM budget, not needed for SEC filings | 2026-04-11 |
| 6 | Orchestration | Roll our own (not LangChain/LlamaIndex) | Full control, less abstraction for focused app | 2026-04-11 |
| 7 | Embedding model | FinBERT (not all-MiniLM-L6-v2) | Finance-specific embeddings, better retrieval for financial queries | 2026-04-11 |
| 8 | Sentiment model | FinBERT sentiment variant | Trained on 10K+ financial texts, knows financial language nuance | 2026-04-11 |
| 9 | Generation LLM | Gemini 2.0 Flash free tier | Most generous free tier (15 RPM, 1M tokens/min) | 2026-04-11 |
| 10 | File limits | 10MB per file, 4 files max, 40MB total | Covers all SEC filings, fits in Render RAM | 2026-04-11 |
| 11 | Deployment | Vercel (frontend) + Render (backend) + Neon (DB) | All free tier, $0 total cost | 2026-04-11 |
| 12 | Sentiment approach | Within-document YoY comparisons + FinBERT on MD&A | Grounded in document data, no external market data | 2026-04-11 |
| 13 | Metrics table | Yes, separate flattened table with source tracking | Instant SQL lookup, tracks extracted vs XBRL source | 2026-04-11 |
| 14 | Processing strategy | One file at a time (not parallel) | Keeps peak RAM under 512MB on Render free tier | 2026-04-11 |
| 15 | XBRL integration | EdgarTools library (not raw EDGAR API) | Mature, 32K+ filing mappings, handles edge cases | 2026-04-11 |
| 16 | Financial intelligence | Hand-built synonyms + jargon + ratios | ~60 synonyms, ~30 jargon, ~20 ratios. Domain knowledge as data. | 2026-04-11 |
| 17 | Input modes | Three: ticker search, document upload, combined | One smart UI, no mode selection. System detects input type. | 2026-04-11 |
| 18 | Cross-company comparison | Via XBRL standardized concepts | EdgarTools handles concept normalization across companies | 2026-04-11 |

---

## Current Status

**Phase:** Not started — CLAUDE.md finalized, ready for Phase 1.

**Next step:** Start Phase 1 — project scaffold, FastAPI skeleton, database setup, React scaffold.
