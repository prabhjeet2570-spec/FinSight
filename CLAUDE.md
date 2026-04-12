# FinSight

## What This Is

A financial intelligence assistant for SEC filings. Users ask natural language questions about any US public company ("How is Apple doing?", "What are NVIDIA's risk factors?", "Compare Microsoft and Google margins") and the system:

1. Detects the company (or companies) from the question
2. Fetches the relevant filings from SEC EDGAR on demand (HTML + XBRL)
3. Runs domain-aware RAG over the fetched filings
4. Returns grounded answers with section + filing citations

**No file uploads. No "drop a PDF here" UX.** Just ask.

**This is NOT a generic document Q&A tool.** It has domain-specific financial intelligence: dual-path filing extraction (HTML narrative + tables + XBRL structured facts), FinBERT embeddings, financial jargon understanding, and computed financial ratios. That's what differentiates it from the dozens of "ask ChatGPT about a 10-K" demos.

**This is a portfolio project for Prabhjeet Singh** (NYU MS CS student). It should demonstrate strong backend/ML engineering skills, domain-specific intelligence design, and end-to-end system design (entity resolution → external API fetch → ingestion pipeline → RAG → grounded generation).

---

## Core Requirements (Non-Negotiable)

1. **Strictly grounded answers** — answers come ONLY from fetched SEC filings. If the answer isn't available, say "I don't have this information." Never hallucinate.
2. **Self-serve, no uploads** — users never upload anything. The system fetches filings from SEC EDGAR based on the company detected in the question.
3. **Dual-path extraction** — narrative text + tables from HTML, plus structured facts from XBRL. Not just text-only RAG.
4. **Caching by accession number** — fetched filings are processed once and reused. Second query for the same company hits cache.
5. **Multi-company queries** — entity extraction supports >1 company per question for comparison queries.
6. **Financial sentiment analysis** grounded in within-filing YoY comparisons and FinBERT on MD&A text.
7. **Free deployment** — $0 cost using free tiers only.
8. **Open-source models** for embedding and sentiment (no paid API for these).
9. **SEC EDGAR compliance** — User-Agent header with contact info on every request, rate-limited to 10 req/sec per SEC guidelines.

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
- "margins" → gross profit / revenue (special concept; expands to multiple metrics + triggers ratio computation)
- "leverage" → total debt / total equity (special concept)

**3. Computable Ratio Definitions (~15-20 formulas)**
Standard financial ratios computed from extracted metrics:
- Gross margin = gross_profit / revenue
- Operating margin = operating_income / revenue
- Net margin = net_income / revenue
- YoY growth = (current - prior) / prior
- Debt-to-equity = total_debt / stockholders_equity

When a user asks "what's the gross margin?" — we don't ask the LLM to figure it out. We look up gross_profit and revenue from the extracted metrics table, compute the ratio ourselves in `app/finance/ratios.py`, and present it as a `ComputedRatio` in the response.

**4. FinBERT for Domain-Specific Understanding**
Finance-trained model instead of generic embeddings (see Tech Stack section). FinBERT understands that "profitability concerns" and "operating margin compression" are related — generic models miss this.

---

## Tech Stack (Decided)

| Layer | Choice | Why |
|-------|--------|-----|
| **Backend** | FastAPI (Python) | Best ML/NLP ecosystem, async, auto-docs |
| **Frontend** | React + Vite + TypeScript | Simple SPA, no SSR needed, deploys as static files on Vercel |
| **Database** | PostgreSQL + pgvector on Neon | One DB for both relational data AND vector search. Free 512MB. |
| **SEC EDGAR Client** | `edgartools` (Python) | Wraps EDGAR's submissions, filing fetch, and XBRL endpoints. Handles ticker → CIK lookup, filing listings, and document download. Saves us from re-implementing the EDGAR HTTP layer. |
| **HTML Extraction** | BeautifulSoup4 + lxml | EDGAR filings are HTML. `<table>` tags are explicit (no detection needed), section headers are `<h1>`/`<h2>` (better section tagging than PDF), no layout issues. |
| **XBRL Parsing** | `edgartools` built-in XBRL | Pulls structured numerical facts (revenue, net income, etc.) directly by concept tag — no table parsing needed for the metrics path. |
| **Entity Extraction** | LLM-based (Groq Llama 3.3 70B) — combined with classifier call | One LLM call extracts both query type AND target companies from the question. No second model needed. Cached against a static company name → ticker map for repeat queries. |
| **Embeddings** | ProsusAI/finbert | Finance-specific embeddings — understands that "bearish" and "declining revenue" are related. Generic models miss this. |
| **Sentiment** | ProsusAI/finbert (sentiment variant) | Trained on 10,000+ financial texts. Knows "restructuring charges" is negative, "strategic investment" is positive. |
| **Generation LLM** | Groq Llama 3.3 70B (free tier) | Free tier with real quota. Fast (~500 tokens/sec). OpenAI-compatible API so the SDK is reusable if we ever swap. |
| **Orchestration** | Roll our own (no LangChain/LlamaIndex framework) | Full control, less abstraction to debug. Use utilities selectively. |
| **Chunking** | LangChain RecursiveCharacterTextSplitter | Just this one utility, not the whole framework |
| **Financial Intelligence** | Hand-built synonym dict + jargon map + ratio definitions | ~60 synonyms, ~30 jargon mappings, ~20 ratio formulas. Domain knowledge encoded as data. |

### Why These Choices

- **pgvector over Pinecone/Qdrant/ChromaDB**: We need BOTH structured SQL queries (metrics lookup, filing cache lookup) AND vector similarity search (text retrieval). pgvector does both in one database. Separate vector DB would mean managing two services + two free tiers.
- **edgartools over raw HTTP**: EDGAR has multiple endpoints (submissions JSON, full-text indexes, archives), strict User-Agent + rate-limit rules, and quirky URL structures. `edgartools` is a maintained wrapper that handles all of this. Re-implementing it is busywork that doesn't earn portfolio points.
- **HTML over PDF for ingestion**: EDGAR's primary format is HTML, not PDF. HTML is *easier* to extract from than PDF — explicit table tags, no column layout issues, no OCR ambiguity. Dropping pdfplumber actually simplifies the extraction layer.
- **XBRL alongside HTML, not instead of**: XBRL gives clean numerical facts but has zero narrative content (no MD&A, no risk factors). We use XBRL for the metrics path and HTML for the narrative path. They feed the same `metrics` and `text_chunks` tables downstream.
- **React+Vite over Next.js**: This is an interactive tool, not a content site. No SEO needed, no SSR needed. Simpler build.
- **Roll our own over LangChain**: For a focused app with clear retrieval paths, direct code is cleaner. LangChain adds abstraction we'd fight when debugging.
- **Groq Llama 3.3 70B over Gemini/OpenAI**: Gemini Flash and OpenAI both failed with `quota=0` despite valid API keys. Groq has a real, unmetered free tier and the same OpenAI-compatible API surface, so the swap was minimal (`base_url` change).
- **FinBERT over all-MiniLM-L6-v2**: Finance-specific embeddings give better retrieval for financial queries. "Profitability concerns" matches "operating margin compression" — generic models miss this. Similar RAM footprint (~110MB vs ~90MB).

---

## Architecture

### End-to-End Flow

```
User question: "How is Apple's revenue trending?"
       |
       v
   Query Classifier + Entity Extractor (Groq Llama 3.3 70B, single call)
   Returns: {query_type, metrics, section_hint, companies: ["AAPL"], reasoning}
       |
       v
   Filing Resolution
   For each company:
     - Look up CIK from ticker (cached company_tickers.json)
     - Determine which filings are needed (latest 10-Q? 10-K? trend → multiple 10-Qs?)
     - Check filing_cache for already-processed accession numbers
       |
       +---------- cache hit ----------+
       |                               |
       v                               |
   EDGAR Fetch                         |
   (only for cache misses)             |
   - edgartools: Company(ticker)       |
   - get_filings(form="10-Q").latest() |
   - Download HTML + XBRL              |
       |                               |
       v                               |
   Ingestion Pipeline (run once per filing, cached forever)
       |                               |
       +-------------+-----------------+
                     |
                     v
   (See Filing Ingestion Pipeline below)
                     |
                     v
   Hybrid Retrieval (over the resolved filings)
   - Vector search: FinBERT embedding of question vs text_chunks (cosine)
   - Structured lookup: SELECT from metrics WHERE metric_name IN (synonyms)
   - Ratio computation: compute_all_ratios() over retrieved metrics
       |
       v
   Context Assembly (## Metrics + ## Ratios + ## Excerpts)
       |
       v
   Grounded Answer Generation (Groq Llama 3.3 70B)
   Strict system prompt: answer ONLY from context, cite [Filing/Page N] / [Metric: name]
       |
       v
   Response: {answer, citations, query_type, confidence,
              companies_resolved, filings_used, metrics_used, ratios_computed}
```

### Filing Ingestion Pipeline (per filing, runs once, cached)

```
EDGAR fetch → HTML + XBRL bytes
       |
       +-----------------+-----------------+
       |                                   |
       v                                   v
   HTML PARSE (BeautifulSoup)           XBRL PARSE (edgartools)
       |                                   |
       +---- tables ----+                  v
       |                |              Structured facts
       v                v              (revenue, net_income, etc.
   Text per section   Table to JSON    by concept tag + period)
   (header tags         |                   |
    drive section       v                   v
    tagging — no      Quality check      Map XBRL concepts to
    regex needed)     (numeric data,     canonical metric names
       |              column counts)        |
       v                |                   v
   Chunking             v              metrics table rows
   (RecursiveCharacter  extracted_tables    (XBRL is the
    TextSplitter)       table rows           preferred source —
       |                |                    HTML tables are
       v                |                    fallback only)
   Embed (FinBERT,      |                   |
    768-dim)            |                   |
       |                |                   |
       v                v                   v
   text_chunks      extracted_tables     metrics
   table            table                table
       |                |                   |
       +----------------+-------------------+
                        |
                        v
                Mark filing as 'ready'
                in filing_cache table
```

**Why two paths to `metrics`:** XBRL gives clean tagged numbers but doesn't cover everything (some non-GAAP figures only appear in HTML tables). HTML table extraction is the fallback when XBRL doesn't have a concept.

### HTML Extraction Quality Notes

HTML extraction is more reliable than PDF, but not perfect:
- EDGAR HTML is often legacy/inline-styled — strip with BeautifulSoup
- Some filings embed images for tables (rare for 10-K/10-Q, common for older 8-Ks) — these will fail extraction; flag and skip
- Section detection is much cleaner: SEC filings use consistent `<h1>`/`<h2>`/`<b>` patterns for "Item 1A. Risk Factors", "Item 2. Management's Discussion and Analysis", etc.
- The MD&A regex bug from the upload-flow era goes away — header tags give us section boundaries directly

### Filing Resolution Heuristics

The classifier returns the question's `query_type` and any company tickers. Filing selection uses simple rules:

| Query intent | Filings to fetch |
|---|---|
| Latest snapshot ("how is X doing?", "what was revenue?") | Latest 10-Q (or 10-K if no 10-Q in last 100 days) |
| Annual / risks / business overview ("what are X's risks?", "what does X do?") | Latest 10-K |
| Trend ("how is X trending?", "growth rate?", "YoY") | Latest 10-K + last 4 10-Qs |
| Recent events ("any recent news?", "what's new with X?") | Latest 5-10 8-Ks |
| Comparison ("compare X and Y") | Latest 10-Q for each company |

Default if uncertain: latest 10-Q (cheapest, covers most questions).

### Query Pipeline (Question → Answer)

```
User question: "How's the top line looking for Apple?"
       |
       v
   Classify + extract (single Groq call)
   {query_type: "NUMERICAL", metrics: ["revenue"], companies: ["AAPL"]}
       |
       v
   Financial Jargon Resolution
   "top line" → adds "revenue" to metrics list
   "margins" → adds gross_profit + revenue + operating_income + net_income
              + ratios_needed: [gross_margin, operating_margin, net_margin]
       |
       v
   Filing Resolution → resolve_filings(["AAPL"], query_type, intent)
   Returns: filing_ids to retrieve over (cached or freshly ingested)
       |
       v
   Route by Query Type:
   - NUMERICAL  → metrics SQL lookup (synonym-expanded) + 2 chunks for context
   - NARRATIVE  → 8 chunks via vector search, skip metrics lookup
   - SENTIMENT  → 8 chunks (default to MD&A section) + metrics
   - MIXED      → 5 chunks + metrics + ratios
       |
       v
   Hybrid Retrieval (scoped to resolved filing_ids)
   - Vector search: FinBERT embedding of question vs text_chunks (cosine)
   - Structured lookup: SELECT from metrics WHERE metric_name IN (synonyms)
   - Ratio computation: compute_all_ratios() over retrieved metrics
       |
       v
   Context Assembly
   (## Extracted Metrics + ## Computed Ratios + ## Relevant Filing Excerpts)
       |
       v
   Grounded Answer Generation (Groq Llama 3.3 70B)
   Strict system prompt: answer ONLY from context, cite [Filing/Page N] / [Metric: name],
   say "I don't have enough information" if context is insufficient.
       |
       v
   Confidence Assessment (heuristic on retrieval quality + query type)
       |
       v
   Response: {answer, citations, query_type, confidence,
              companies_resolved, filings_used, metrics_used, ratios_computed}
```

### SEC Filing Sections (used for retrieval boosting)

- Item 1: Financial Statements (tables)
- Item 1A: Risk Factors
- Item 2: MD&A (narrative — gold mine for analysis questions)
- Item 3: Quantitative Disclosures
- Item 4: Controls
- Part II Item 1: Legal Proceedings

A question about "risk" should prefer chunks from Risk Factors over random mentions elsewhere. SENTIMENT queries default `section_hint` to MD&A. With HTML ingestion, section tagging comes from explicit header tags rather than first-500-char regex matching.

### Sentiment Analysis Approach

Two signal sources, both grounded in the fetched filing:

**Quantitative (from extracted metrics):**
- Within-filing YoY changes (Revenue +9.6%, Net Income +9.3%, etc.) — sourced from XBRL or HTML tables
- Trend detection across multiple fetched periods (latest 10-K + last 4 10-Qs)
- All numbers sourced from filing data, never external market data

**Qualitative (from filing text + FinBERT):**
- Run FinBERT sentiment on MD&A chunks
- FinBERT was trained on 10,000+ financial texts — knows "restructuring charges" is negative, "strategic investment in growth" is positive
- Extract qualitative signals: "increased primarily due to...", "decline was driven by..."

Combined sentiment is always grounded in the filing — never speculate beyond what's there. No external market data, no analyst reports, no news APIs.

---

## Database Schema

```sql
CREATE EXTENSION vector;
CREATE EXTENSION pgcrypto;

-- Companies table (cached ticker → CIK lookup, populated on demand from
-- EDGAR's company_tickers.json)
CREATE TABLE companies (
    cik         TEXT PRIMARY KEY,         -- 10-digit zero-padded CIK
    ticker      TEXT NOT NULL,
    name        TEXT NOT NULL,
    sic         TEXT,                     -- industry code
    last_synced TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_companies_ticker ON companies(ticker);
CREATE INDEX idx_companies_name ON companies(lower(name));

-- Filings table (one row per fetched SEC filing — replaces the old `documents` table)
CREATE TABLE filings (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    cik              TEXT NOT NULL REFERENCES companies(cik),
    ticker           TEXT NOT NULL,           -- denormalized for fast lookup
    accession_number TEXT NOT NULL UNIQUE,    -- EDGAR's unique filing ID, e.g. '0000320193-25-000123'
    filing_type      TEXT NOT NULL,           -- '10-K', '10-Q', '8-K', etc.
    filing_date      DATE NOT NULL,
    period_of_report DATE,                    -- reporting period end date
    period_label     TEXT,                    -- 'Q3 2025', 'FY 2024'
    primary_doc_url  TEXT NOT NULL,           -- URL to the HTML filing on EDGAR
    fetched_at       TIMESTAMPTZ DEFAULT now(),
    status           TEXT DEFAULT 'processing', -- 'processing', 'ready', 'failed'
    error_message    TEXT,                    -- populated on 'failed'
    page_count       INT,
    chunk_count      INT,
    metric_count     INT
);
CREATE INDEX idx_filings_cik_type ON filings(cik, filing_type, filing_date DESC);
CREATE INDEX idx_filings_ticker_type ON filings(ticker, filing_type, filing_date DESC);
CREATE INDEX idx_filings_status ON filings(status);

-- Text chunks (for narrative/unstructured retrieval)
CREATE TABLE text_chunks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filing_id   UUID NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    chunk_text  TEXT NOT NULL,
    page_num    INT,                        -- best-effort from HTML structure
    section     TEXT,                       -- 'MD&A', 'Risk Factors', 'Notes', etc.
    chunk_index INT,
    embedding   vector(768),                -- FinBERT output (768-dim)
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Extracted tables (HTML tables parsed to structured JSON)
CREATE TABLE extracted_tables (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filing_id  UUID NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    page_num   INT,
    table_type TEXT,                        -- 'income_statement', 'balance_sheet', etc.
    headers    JSONB,
    rows       JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Extracted metrics (flattened key numbers — XBRL-sourced first, HTML-sourced fallback)
CREATE TABLE metrics (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filing_id     UUID NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    metric_name   TEXT NOT NULL,
    value         NUMERIC,
    prior_value   NUMERIC,
    change_pct    NUMERIC,
    unit          TEXT DEFAULT 'USD',
    period        TEXT,
    prior_period  TEXT,
    source        TEXT NOT NULL,             -- 'xbrl' or 'html_table'
    xbrl_concept  TEXT,                      -- e.g. 'us-gaap:Revenues' (when source = 'xbrl')
    page_num      INT,                       -- when source = 'html_table'
    table_type    TEXT,
    created_at    TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX idx_chunks_embedding ON text_chunks
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX idx_chunks_filing ON text_chunks(filing_id);
CREATE INDEX idx_chunks_section ON text_chunks(section);
CREATE INDEX idx_tables_filing ON extracted_tables(filing_id);
CREATE INDEX idx_metrics_filing ON metrics(filing_id);
CREATE INDEX idx_metrics_name ON metrics(metric_name);
```

**Why a separate `companies` table:** lets us cache the EDGAR ticker → CIK map locally instead of hitting `company_tickers.json` (~13MB) on every request. Also lets entity extraction match against `lower(name)` for "Apple" / "Microsoft" lookups.

**Why `filings.accession_number` is `UNIQUE`:** the cache key. Re-asking about Apple → resolve to the latest 10-Q's accession number → already in the table → skip the entire ingestion pipeline.

---

## API Design

```
# Query (the main entrypoint — replaces upload + query)
POST   /api/query                    -- Ask a question about any company
       Body: {question: str}
       Response: {
           answer, citations, query_type, confidence,
           companies_resolved: [{ticker, name, cik}],
           filings_used: [{filing_id, ticker, filing_type, period_label, accession_number}],
           metrics_used, ratios_computed,
           sentiment?  // SENTIMENT queries only
       }
       Notes:
       - Long-running on cache miss (60-180s for first fetch of a new company).
         Returns 202 Accepted with a job_id and the client polls /api/query/jobs/{id}.
       - Cache hit returns 200 directly with the response body.

GET    /api/query/jobs/{job_id}      -- Poll status of a long-running query
       Response: {status: 'pending|processing|ready|failed', progress?: str, result?: QueryResponse}

# Filings (introspection / debugging)
GET    /api/filings                          -- List cached filings
       Query params: ticker?, filing_type?, limit?
GET    /api/filings/{id}                     -- Filing metadata
GET    /api/filings/{id}/metrics             -- All metrics for a filing
GET    /api/filings/{id}/tables              -- All tables for a filing

# Companies (entity resolution debugging)
GET    /api/companies/search?q={query}       -- Search companies by name or ticker
GET    /api/companies/{ticker}               -- Get CIK + metadata
POST   /api/companies/sync                   -- Re-pull company_tickers.json from EDGAR
                                                (admin / cron only)

# Health
GET    /health                               -- Health check
```

**Why `POST /api/query` is async-friendly:** A first query for an uncached ticker triggers a fetch + ingestion pipeline that takes 1-3 minutes. We can't hold an HTTP connection that long on Render's free tier (default 30s timeout). Pattern: POST returns either 200 (cache hit) or 202 with a `job_id`, and the client polls `/api/query/jobs/{id}` every 2-3s. The frontend shows "Fetching Apple's 10-Q from SEC EDGAR..." while polling.

**Removed from old API:**
- `POST /api/documents/upload` — no uploads anymore
- `DELETE /api/documents/{id}` — users don't manage filings; filings are cached automatically
- `GET /api/documents/{id}/status` — folded into job polling

---

## UI Design

### Core Principle
**One input. Ask anything about any public company.** No file uploads, no document selection, no setup. The chat IS the app.

### Layout
```
┌──────────────────────────────────────────────────────────────────┐
│  FinSight   Ask anything about any US public company             │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Try asking:                                               │  │
│  │  • "How is Apple's revenue trending?"                      │  │
│  │  • "What are NVIDIA's biggest risk factors?"               │  │
│  │  • "Compare Microsoft and Google's operating margins"      │  │
│  │  • "Is Tesla's management optimistic about next year?"     │  │
│  │  • "What did Meta say about AI in their last 10-Q?"        │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  > How is Apple's revenue trending?                              │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  ⏳ Fetching Apple's latest 10-Q from SEC EDGAR…          │  │
│  │  ⏳ Extracting tables and narrative…                       │  │
│  │  ⏳ Generating embeddings…                                 │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  [HIGH CONFIDENCE] [NUMERICAL] [AAPL · 10-Q · Q3 2025]    │  │
│  │                                                            │  │
│  │  Apple's revenue grew 9.6% year-over-year in Q3 2025,     │  │
│  │  reaching $94.0B [Metric: revenue]. This continues a      │  │
│  │  positive trend from Q2 2025 (+4.9% YoY)…                 │  │
│  │                                                            │  │
│  │  ▶ 5 sources                                              │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Ask about any public company…                       │Ask │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

### Component Behavior

- **ChatPanel** — single-column conversation view, primary interface. Suggested-question chips on first load. Auto-scrolls to newest message.
- **JobProgress** — when `/api/query` returns 202, poll `/api/query/jobs/{id}` every 2s. Show inline progress messages: "Fetching Apple's 10-Q from SEC EDGAR…", "Extracting tables…", "Generating embeddings…", "Searching filings…". This is critical UX — first-query latency is 1-3 minutes and the user needs to know what's happening.
- **AnswerBubble** — confidence + query_type tags, plus a per-company tag showing which filing(s) were used (`AAPL · 10-Q · Q3 2025`). Expandable citation list with section + page references.
- **CompanyChip** — when an answer cites multiple companies (comparison query), each company gets its own chip. Clicking a chip filters the conversation to that company.
- **Adaptive empty state** — when entity extraction fails ("How is the economy?" → no company), backend returns a clarification prompt: "I couldn't identify a specific company in your question. Try asking about a public company by name or ticker — e.g., 'How is Apple doing?'"

### What's gone from the old UI

- ❌ **UploadZone** — replaced by the chat input
- ❌ **DocumentList** — no user-managed documents; filings are cached transparently
- ❌ **Document selection checkboxes** — companies are detected from the question itself
- ❌ **File size validation** — no uploads
- ❌ **Per-document delete** — admin-only filing eviction (not in v1 UI)

---

## Deployment Architecture

```
Vercel (Frontend)              Render (Backend)              Neon (Database)
React + Vite                   FastAPI + Python               PostgreSQL + pgvector
Static files                   512MB RAM free tier            512MB storage free tier
No RAM concern                 Spins down after 15min idle    Managed, scales to zero
                     <-- API calls (HTTPS) -->     <-- SQL + pgvector queries -->
                                    |
                                    +-----> SEC EDGAR (HTTPS, free, no auth)
                                    |       https://data.sec.gov, https://www.sec.gov
                                    |       (User-Agent header required)
                                    |
                                    +-----> Groq API
                                            (free tier, OpenAI-compatible)
                                            llama-3.3-70b-versatile
```

### RAM Budget (Render Free Tier = 512MB)

```
FastAPI + dependencies:        ~80MB
edgartools + httpx:            ~20MB
BeautifulSoup + lxml:          ~15MB
FinBERT model:                 ~110MB  (lazy loaded, shared between embedding + sentiment)
HTML filing in memory (1):     ~5MB    (process one filing at a time)
XBRL filing in memory (1):     ~3MB
Working overhead:              ~60MB
─────────────────────────────────────
Total:                         ~295MB  (fits in 512MB with headroom)
```

### Storage Budget (Neon Free Tier = 512MB)

Per filing roughly:
- 10-K: ~150 chunks × 768-dim embeddings + tables + ~50 metrics ≈ ~1.5MB
- 10-Q: ~50 chunks × 768-dim embeddings + tables + ~30 metrics ≈ ~0.6MB
- 8-K: ~10 chunks ≈ ~0.1MB

So one company (1×10-K + 4×10-Q + 5×8-K) ≈ ~4.5MB. **The free tier holds ~100 companies cached** before we need eviction. For v1, just LRU-evict the oldest fetched filing when the DB hits ~80% of the cap.

### Cold Starts (Two Layers)

1. **Render server cold start** — ~30s to boot after 15min idle. Show "waking up the server…" in UI.
2. **First-query cold start for a new company** — fetching + ingesting a 10-Q is ~60-90s, a 10-K is ~120-180s. Show progress steps in UI ("Fetching from EDGAR → Extracting → Embedding → Searching"). Cached companies are instant.

---

## Project Structure

```
finsight/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, lifespan, EDGAR identity setup
│   │   ├── config.py            # Environment variables (DATABASE_URL, GROQ_API_KEY, EDGAR_USER_AGENT)
│   │   ├── db/
│   │   │   ├── connection.py    # Async Postgres connection pool
│   │   │   └── schema.sql       # Table definitions (companies, filings, text_chunks, extracted_tables, metrics)
│   │   ├── models/              # Pydantic request/response schemas
│   │   │   ├── company.py
│   │   │   ├── filing.py
│   │   │   └── query.py
│   │   ├── routers/             # API route handlers
│   │   │   ├── query.py         # POST /api/query, GET /api/query/jobs/{id}
│   │   │   ├── filings.py       # GET /api/filings, /api/filings/{id}/{metrics,tables}
│   │   │   └── companies.py     # GET /api/companies/search, /api/companies/{ticker}
│   │   ├── services/            # Business logic
│   │   │   ├── edgar_client.py       # edgartools wrapper: ticker→CIK, list filings, fetch HTML+XBRL
│   │   │   ├── filing_resolver.py    # Map (companies, query_type) → which filings to fetch
│   │   │   ├── filing_ingestion.py   # Orchestrates: fetch → extract → chunk → embed → cache
│   │   │   ├── html_extraction.py    # BeautifulSoup: HTML → narrative text + tables + section tags
│   │   │   ├── xbrl_extraction.py    # edgartools XBRL → metrics rows (preferred numerical source)
│   │   │   ├── chunking.py           # Text → chunks (RecursiveCharacterTextSplitter)
│   │   │   ├── embedding.py          # Chunks → vectors (FinBERT)
│   │   │   ├── metric_flattening.py  # HTML tables → metrics rows (XBRL fallback)
│   │   │   ├── retrieval.py          # Vector search + SQL lookup + ratio compute (filing-scoped)
│   │   │   ├── classifier.py         # Groq Llama 3.3 70B: query type + entities (companies) in one call
│   │   │   ├── entity_resolution.py  # Match extracted company names → ticker via companies table
│   │   │   ├── generation.py         # Groq Llama 3.3 70B: grounded answer generation
│   │   │   ├── sentiment.py          # FinBERT sentiment on MD&A chunks
│   │   │   └── job_queue.py          # In-memory job tracking for async query polling
│   │   ├── finance/             # Financial domain knowledge
│   │   │   ├── synonyms.py      # Metric synonym dictionary (~60 entries)
│   │   │   ├── jargon.py        # Financial jargon map (~30 entries)
│   │   │   ├── ratios.py        # Computable ratio definitions (~20 formulas)
│   │   │   └── xbrl_concepts.py # us-gaap concept tag → canonical metric name map
│   │   └── utils/
│   │       └── html_section_detector.py  # Map HTML <h1>/<h2>/<b> headers → SEC section names
│   ├── scripts/                 # Standalone test/dev scripts
│   │   └── seed_companies.py    # One-time pull of EDGAR's company_tickers.json into companies table
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile               # For Render deployment
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # Single-column chat layout (no side panel)
│   │   ├── App.css              # All styling
│   │   ├── components/
│   │   │   ├── ChatPanel.tsx        # Q&A with suggested-question chips
│   │   │   ├── AnswerBubble.tsx     # Confidence + query_type + per-company tags + citations
│   │   │   ├── JobProgress.tsx      # Inline "fetching from EDGAR…" progress for async queries
│   │   │   └── CompanyChip.tsx      # Per-company filing tag (AAPL · 10-Q · Q3 2025)
│   │   ├── lib/
│   │   │   └── api.ts           # fetch wrapper + job polling helper
│   │   ├── types/
│   │   │   └── index.ts         # TS mirrors of backend Pydantic models
│   │   └── config.ts            # API_BASE_URL
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── CLAUDE.md                    # This file
├── .gitignore
└── README.md
```

**Files removed in the EDGAR pivot** (from the old upload-flow architecture):
- `backend/app/routers/documents.py` — replaced by `filings.py`
- `backend/app/services/document_processor.py` — replaced by `filing_ingestion.py`
- `backend/app/services/extraction.py` (pdfplumber) — replaced by `html_extraction.py` + `xbrl_extraction.py`
- `backend/app/services/metadata_detection.py` — EDGAR provides this metadata directly, no parsing needed
- `backend/app/utils/section_detector.py` (regex on text[:500]) — replaced by `html_section_detector.py` (uses HTML structure)
- `frontend/src/components/UploadZone.tsx`
- `frontend/src/components/DocumentList.tsx`

---

## Build Plan

### Architecture Pivot Notice

> **Phases 1-7 below built the upload-flow architecture and are now superseded by Phases 8-12 (the EDGAR pivot — see Decisions #22-#26).** The old phases are kept for context. The financial intelligence layer (Phase 3), embeddings/retrieval primitives (Phase 4), and grounded-generation prompt (Phase 5) carry over largely unchanged. The PDF upload pipeline (Phase 2), upload-flow frontend (Phase 6), and document-management API are being **deleted and replaced**.

### Phase 1: Project Setup + Database ✅ (carries over)
**Goal:** Skeleton running locally, database connected

- [x] Initialize project structure (backend + frontend dirs)
- [x] FastAPI app with `/health` endpoint
- [x] config.py loading env vars
- [x] Async Postgres connection using asyncpg
- [x] schema.sql + pgvector extension + indexes
- [x] DB initialization on startup
- [x] React + Vite + TypeScript scaffold
- [x] .gitignore, .env.example, README.md
- **Test:** `GET /health` returns 200, database connects, frontend renders

### Phase 2: PDF Upload + Extraction Pipeline ✅ → ❌ (to be deleted)
**Goal:** Upload a PDF, extract text and tables, store in database

- [x] `POST /api/documents/upload`, pdfplumber, table extraction, metadata detection, etc.
- **Status:** Built and working, but **slated for deletion** in Phase 8. Replaced by EDGAR fetch + HTML extraction.

### Phase 3: Financial Intelligence Layer ✅ (carries over)
**Goal:** Encode finance domain knowledge as data, not LLM guesses

- [x] Metric synonym dictionary — ~60 canonical metrics
- [x] Financial jargon map — ~30 shorthand → metric mappings
- [x] Ratio definitions — ~20 formulas
- **Carries over unchanged.** This is the most reusable layer in the codebase.

### Phase 4: Embeddings + Retrieval ✅ (carries over, with schema rename)
**Goal:** Chunks are searchable via finance-specific vector similarity and structured SQL

- [x] Lazy-load FinBERT
- [x] FinBERT embeddings, pgvector storage, vector search, structured metric lookup, hybrid retrieval
- **Carries over** — only change is `document_id` → `filing_id` column rename in queries.

### Phase 5: Query Pipeline + Answer Generation ✅ (carries over, classifier needs upgrade)
**Goal:** Ask a question in natural language, get a grounded answer with citations

- [x] Query classifier (Groq Llama 3.3 70B) — currently returns `{query_type, metrics, section_hint}`
- [x] Jargon resolution
- [x] Routing logic for 4 query types
- [x] Context assembly + grounded generation
- [x] Confidence assessment, empty-retrieval short-circuit
- [x] `POST /api/query` endpoint
- **Carries over with upgrades** — classifier prompt extended to also extract `companies` (entity extraction). Empty-retrieval message changes from "upload more docs" to "I couldn't identify a company."

### Phase 6: Frontend ✅ → ❌ (to be deleted, partial rewrite)
**Goal:** Usable UI — upload docs, ask questions, see answers with citations

- [x] Two-panel layout, UploadZone, DocumentList, ChatPanel
- **Status:** Built. **Two-panel layout, UploadZone, DocumentList all to be deleted** in Phase 11. ChatPanel rewrites to single-column with job-polling progress UI.

### Phase 7: Sentiment + Deploy ✅ (carries over)
**Goal:** FinBERT sentiment on MD&A, deployed live at $0

- [x] FinBERT sentiment service, integration with SENTIMENT query type, frontend display
- [x] Backend Dockerfile, CORS config, cold-start UX
- **Carries over** — sentiment runs on the same retrieved chunks regardless of where they came from.

---

## EDGAR Pivot Phases

### Phase 8: SEC EDGAR Client + Schema Migration
**Goal:** Backend can fetch any company's filings on demand and cache them

- [ ] Add `edgartools`, `beautifulsoup4`, `lxml` to `requirements.txt`
- [ ] Add `EDGAR_USER_AGENT` to config (e.g., `"FinSight prabhjeet@nyu.edu"`)
- [ ] New schema: `companies`, `filings` tables; rename `text_chunks.document_id` → `filing_id`; add `metrics.source` + `metrics.xbrl_concept`; drop old `documents` table
- [ ] Migration script: drop old upload-era tables and recreate
- [ ] `app/services/edgar_client.py` — wraps `edgartools`: `get_company(ticker)`, `list_filings(cik, form_type, limit)`, `fetch_filing(accession_number) → (html_bytes, xbrl_facts)`
- [ ] `scripts/seed_companies.py` — pull EDGAR's `company_tickers.json` (~13MB) into the `companies` table on first run
- [ ] Rate limiting: 10 req/sec cap on EDGAR calls (their published limit)
- **Test:** Run a script that fetches Apple's latest 10-Q via the client, prints the HTML byte size and the XBRL fact count.

### Phase 9: HTML + XBRL Extraction
**Goal:** Replace pdfplumber with HTML/XBRL extraction that feeds the same downstream pipeline

- [ ] `app/services/html_extraction.py` — BeautifulSoup parses EDGAR HTML into:
  - Narrative text per section (using `<h1>`/`<h2>`/`<b>` tags as section boundaries)
  - Tables as JSON (headers + rows)
  - Section names tagged from header text matching SEC item structure
- [ ] `app/services/xbrl_extraction.py` — `edgartools` XBRL → metrics rows. Map `us-gaap:Revenues`, `us-gaap:NetIncomeLoss`, etc. to canonical metric names (new file: `app/finance/xbrl_concepts.py`).
- [ ] `app/services/metric_flattening.py` — updated: XBRL metrics first, HTML table metrics as fallback (only insert if XBRL didn't already provide that metric_name for that period)
- [ ] `app/services/filing_ingestion.py` — orchestrator: fetch → extract HTML + XBRL → chunk → embed → store, marking the filing's status `processing → ready`
- [ ] Delete: `extraction.py` (pdfplumber), `metadata_detection.py`, `document_processor.py`, `utils/section_detector.py`
- [ ] New `utils/html_section_detector.py` — maps HTML headers to section names
- [ ] Drop `pdfplumber` from `requirements.txt`
- **Test:** Run filing ingestion on Apple's latest 10-Q. Verify: ~50 chunks created with section tags including MD&A; ~30 metrics created with `source='xbrl'` for the major line items.

### Phase 10: Entity Resolution + Filing Resolution + Async Query
**Goal:** A natural language question fetches the right filings and runs the existing query pipeline against them

- [ ] Extend the classifier prompt (`app/services/classifier.py`) to also extract `companies: [str]` from the question. Update the few-shot examples with company-detection cases.
- [ ] `app/services/entity_resolution.py` — match extracted company names against the `companies` table (ticker exact match → name fuzzy match → fallback). Returns `[(ticker, cik, name)]`.
- [ ] `app/services/filing_resolver.py` — given `(companies, query_type, intent)`, decide which filings are needed and return `filing_ids` (after triggering ingestion for cache misses)
- [ ] `app/services/job_queue.py` — in-memory `dict[job_id, JobState]` for tracking long-running queries (works on Render free tier; one process, no Redis needed)
- [ ] `app/routers/query.py` — rewrite:
  - Sync path (cache hit): run pipeline, return 200
  - Async path (cache miss): create job, kick off ingestion in background task, return 202 with `job_id`
- [ ] New `GET /api/query/jobs/{job_id}` endpoint
- [ ] Update `app/services/retrieval.py` to scope retrieval to a list of `filing_ids`
- [ ] Empty-retrieval short-circuit message updates: "I couldn't identify a public company in your question…"
- **Test:**
  - "How is Apple's revenue?" → cache miss → kicks off ingestion → polls to ready → returns answer with citations
  - Same question second time → cache hit → 200 immediately
  - "Compare Apple and Microsoft margins" → resolves both → fetches both → answer cites both

### Phase 11: Frontend Rewrite
**Goal:** Single-column chat UI with first-class progress UX for slow first queries

- [ ] Delete: `UploadZone.tsx`, `DocumentList.tsx`, the two-panel layout in `App.tsx`
- [ ] New `App.tsx` — single-column chat layout, full width
- [ ] Rewrite `ChatPanel.tsx` — suggested-question chips, conversation view, no document scoping
- [ ] New `JobProgress.tsx` — polls `/api/query/jobs/{id}` every 2s, shows progress steps
- [ ] New `AnswerBubble.tsx` — confidence + query_type tags, per-company tags, expandable citations
- [ ] New `CompanyChip.tsx` — `AAPL · 10-Q · Q3 2025` style filing tags
- [ ] Update `lib/api.ts` — add job polling helper that handles 200 vs 202 transparently
- [ ] Update `types/index.ts` — mirror new query response shape (`companies_resolved`, `filings_used`)
- [ ] Friendly error states for "no company detected", "EDGAR fetch failed", "filing has no MD&A section"
- **Test:** `tsc -b && vite build` clean. Manual test: ask "How is Apple doing?" with empty cache, watch progress through 90s ingestion, verify answer renders with citations.

### Phase 12: Polish + Deploy
**Goal:** Ship it

- [ ] LRU eviction for filings table when DB hits ~80% of Neon free tier (oldest `fetched_at` first)
- [ ] Pre-warm script (optional): seed cache with AAPL, MSFT, GOOGL, NVDA, TSLA, META, AMZN before first deploy
- [ ] Update Dockerfile if needed (edgartools may need extra deps)
- [ ] Update `.env.example` with `EDGAR_USER_AGENT`
- [ ] Deploy backend to Render (set `DATABASE_URL`, `GROQ_API_KEY`, `EDGAR_USER_AGENT`, `FRONTEND_URL`)
- [ ] Deploy frontend to Vercel (set `VITE_API_URL`)
- [ ] Run new schema on Neon
- [ ] End-to-end test with 5+ companies on the live URL
- [ ] Update README to reflect the new "ask anything" UX

---

## Competitive Landscape

These decisions are informed by research into existing projects (conducted 2026-04-11).

### Closest Existing Projects

| Project | What it does | What it doesn't do |
|---------|-------------|-------------------|
| [SEC Insights](https://github.com/run-llama/sec-insights) (LlamaIndex) | Most polished SEC RAG app. Next.js + FastAPI + pgvector + OpenAI. PDF viewer with citation highlighting. | No structured table extraction, no metrics computation, no computed ratios, no domain-specific embeddings. Text-only RAG. Paid (OpenAI). |
| [FinanceRAG](https://github.com/nik2401/FinanceRAG-Investment-Research-Assistant) | FastAPI + PostgreSQL + Gemini. SEC EDGAR integration. | No structured table extraction, no computed ratios, no FinBERT embeddings. |
| [FinSage](https://arxiv.org/abs/2504.14493) (research paper) | Multi-modal preprocessing, HyDE query expansion, DPO-tuned re-ranking. 92.51% recall. | Academic — not a deployable web app with UI. |
| [Finbot](https://github.com/deepakb41/Finbot) | LangChain + RAG for 10-K/10-Q. Conversational. | Text-only RAG, no structured table extraction, no computed ratios, no domain-specific intelligence layer. |

### What FinSight does that none of them do

1. **Dual-path PDF extraction** — both structured table extraction (parsed to a metrics table) AND text RAG. Other tools are text-only.
2. **Computed financial ratios** — margins, growth rates, leverage computed in code from extracted metrics. Others ask the LLM to do it (unreliable).
3. **Financial jargon + synonym resolution as data** — "top line", "margins", "leverage" map to concrete metrics before retrieval. Generic RAG asks the LLM to figure it out.
4. **FinBERT domain-specific retrieval + sentiment** — finance-trained embeddings, not generic models.
5. **Free deployment** — $0 total cost. SEC Insights requires paid OpenAI API.

### What existing projects do better (learn from them)

- **SEC Insights**: PDF viewer with citation highlighting — worth studying for a future UI enhancement
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
| 13 | Metrics table | Yes, separate flattened table | Instant SQL lookup, decoupled from raw table JSON | 2026-04-11 |
| 14 | Processing strategy | One file at a time (not parallel) | Keeps peak RAM under 512MB on Render free tier | 2026-04-11 |
| 15 | ~~XBRL integration~~ | ~~EdgarTools library~~ | **Reversed — see Decision #19** | 2026-04-11 |
| 16 | Financial intelligence | Hand-built synonyms + jargon + ratios | ~60 synonyms, ~30 jargon, ~20 ratios. Domain knowledge as data. | 2026-04-11 |
| 17 | ~~Three input modes~~ | ~~Ticker search, document upload, combined~~ | **Reversed — see Decision #19** | 2026-04-11 |
| 18 | ~~Cross-company comparison~~ | ~~Via XBRL standardized concepts~~ | **Reversed — see Decision #19** | 2026-04-11 |
| 19 | ~~Drop XBRL/EdgarTools entirely~~ | ~~RAG-only over uploaded PDFs~~ | **Reversed by Decision #22.** | 2026-04-12 |
| 20 | Query types | 4 (NUMERICAL, NARRATIVE, MIXED, SENTIMENT) | CROSS_DOC handled by retrieval scoping to multiple filings; CROSS_COMPANY now naturally handled by entity extraction returning multiple companies. UNSUPPORTED handled by empty-retrieval short-circuit. | 2026-04-12 |
| 21 | ~~Two-panel UI (docs left, chat right)~~ | ~~Static layout~~ | **Reversed by Decision #25.** | 2026-04-12 |
| 22 | **EDGAR pivot — drop uploads, fetch from SEC EDGAR** | User asks question → system fetches filings | The upload UX is generic ("yet another drop-PDF-and-ask demo"). Self-serve "ask anything about any public company" is a much stronger product story AND demonstrates more system design (entity resolution, external API integration, async job pipeline, caching, rate limiting). RAG stays — only the data source changes. **Reverses Decision #19.** | 2026-04-12 |
| 23 | EDGAR client library | `edgartools` (not raw HTTP) | Wraps ticker→CIK lookup, filing listings, HTML download, and XBRL parsing. Re-implementing it is busywork. Maintained, used by financial data scientists in production. | 2026-04-12 |
| 24 | Filing format priority | HTML primary, XBRL for metrics | EDGAR's primary format is HTML (not PDF). HTML is *easier* than PDF (explicit `<table>` tags, `<h1>`/`<h2>` section headers, no layout/OCR issues). XBRL gives clean numerical facts but has zero narrative — so XBRL feeds the metrics path while HTML feeds both narrative chunks AND fallback metrics. | 2026-04-12 |
| 25 | UI is single-column chat | Drop the two-panel layout | With uploads gone, the documents panel has nothing to show. The chat IS the app — one input, ask anything. | 2026-04-12 |
| 26 | Query API is async | 200 (cache hit) or 202 + job polling (cache miss) | First query for a new company takes 60-180s for fetch + extract + chunk + embed. Render free tier HTTP timeout is 30s. Async with job polling is the only viable pattern. Cached queries return immediately. | 2026-04-12 |
| 27 | Filing cache key | `accession_number` | Each EDGAR filing has a globally unique accession number. Use it as the dedup key — re-asking about Apple resolves to the same accession → instant cache hit. | 2026-04-12 |
| 28 | Storage policy | LRU eviction at ~80% of Neon free tier | ~100 companies fit in 512MB. When the cap is approached, evict the least-recently-fetched filing. Simple, no Redis or external state. | 2026-04-12 |
| 29 | Multi-company queries | Entity extraction returns a list | "Compare Apple and Microsoft margins" returns `companies: ["AAPL", "MSFT"]`. Filing resolver fetches both, retrieval scopes to both filings' chunks/metrics. The classifier already does this in one LLM call alongside query_type extraction — no second model needed. | 2026-04-12 |
| 30 | Generation LLM | Groq Llama 3.3 70B | Gemini Flash and OpenAI both failed with `quota=0` despite valid API keys. Groq has a real free tier and an OpenAI-compatible API surface (`base_url` swap), so the migration was minimal. | 2026-04-12 |

---

## Current Status

**Phase:** Mid-pivot. Phases 1-7 (upload-flow architecture) are complete and working locally. Phases 8-12 (EDGAR pivot) are queued and not started.

**What's working right now (upload-flow architecture, soon to be partially deleted):**
- PDF upload + dual-path extraction (pdfplumber)
- Financial intelligence layer (synonyms, jargon, ratios) — **carries over to new architecture**
- FinBERT embeddings + hybrid retrieval — **carries over**
- Query classification + grounded generation (Groq Llama 3.3 70B) — **carries over with classifier upgrade for entity extraction**
- FinBERT sentiment on MD&A — **carries over**
- React frontend with two-panel upload UI — **to be replaced in Phase 11**

**Known bug in current code:** SENTIMENT queries return empty for the Apple 10-Q because zero chunks were tagged with `section='MD&A'` (the regex section detector missed the header in this filing). This bug **goes away naturally in Phase 9** when HTML extraction tags sections from `<h1>`/`<h2>` headers instead of regex on text[:500]. No need to fix it in the upload-flow code that's about to be deleted.

**What's next (EDGAR pivot, Phases 8-12):**
1. **Phase 8** — Add edgartools, BeautifulSoup, lxml. New schema (companies, filings tables). EDGAR client wrapper. Seed companies table.
2. **Phase 9** — Replace pdfplumber with HTML + XBRL extraction. Delete old extraction modules.
3. **Phase 10** — Extend classifier to extract companies. Filing resolver. Async query endpoint with job polling.
4. **Phase 11** — Frontend rewrite to single-column chat. Delete UploadZone + DocumentList.
5. **Phase 12** — LRU eviction, deploy to Render/Vercel/Neon, end-to-end test on live URL.

**Open questions to settle before starting Phase 8:**
- Pre-warm the cache with popular tickers (AAPL, MSFT, GOOGL, NVDA, TSLA, META, AMZN) before first deploy, or let it warm on demand? *Current default: pre-warm in Phase 12.*
- Render free-tier background-task lifetime — does it survive long enough to complete a 3-minute ingestion? May need a separate worker dyno or to switch hosts. *To validate empirically in Phase 10.*
