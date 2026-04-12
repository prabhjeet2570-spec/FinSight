# FinSight

## What This Is

A financial intelligence tool for analyzing SEC filings. Users upload 10-Q, 10-K, or press release PDFs and ask questions in natural language. Answers come back grounded in the actual document content with page citations and confidence scoring.

**This is NOT a generic document Q&A tool.** It has domain-specific financial intelligence: dual-path PDF extraction (tables + text), FinBERT embeddings, financial jargon understanding, and computed financial ratios from extracted metrics. That's what differentiates it from the dozens of "upload PDF and ask questions" RAG demos.

**This is a portfolio project for Prabhjeet Singh** (NYU MS CS student). It should demonstrate strong backend/ML engineering skills and domain-specific intelligence design.

---

## Core Requirements (Non-Negotiable)

1. **Strictly grounded answers** — answers come ONLY from uploaded documents. If the answer isn't available, say "I don't have this information." Never hallucinate.
2. **Dual-path extraction** — both structured table extraction AND unstructured text extraction from PDFs. Not just text-only RAG.
3. **Up to 4 documents** at once for cross-document analysis.
4. **10MB per file max**, 40MB total across all uploads.
5. **Financial sentiment analysis** grounded in within-document YoY comparisons and FinBERT on MD&A text.
6. **Free deployment** — $0 cost using free tiers only.
7. **Open-source models** for embedding and sentiment (no paid API for these).

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
| **PDF Extraction** | pdfplumber | Handles all SEC filings (text-based PDFs). Free, fast, reliable. |
| **VLM Fallback** | Deferred to later phase | For scanned/graphical PDFs. Not needed for SEC filings. |
| **Embeddings** | ProsusAI/finbert | Finance-specific embeddings — understands that "bearish" and "declining revenue" are related. Generic models miss this. |
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

---

## Architecture

### Processing Pipeline (Upload → Ready)

```
User uploads PDF (max 4 files, 10MB each)
        |
        v
   Metadata Extraction
   (company name, filing type, period from filename + first page)
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
   |              Embed chunks (FinBERT, 768-dim)
   |              Store in text_chunks table
   v
Parse to JSON
Store in extracted_tables
Flatten key metrics → metrics table
```

### pdfplumber Failure Detection

pdfplumber doesn't crash — it returns bad data silently. Detect with:
- No tables found but page has many lines/rects (>20) → graphical table, needs VLM
- Table found but >40% empty cells → misaligned extraction
- Table found but inconsistent column counts across rows
- Table found but no numeric data (financial tables MUST have numbers)

When quality check fails: log it, flag the page. VLM fallback is deferred to later phase.

### Query Pipeline (Question → Answer)

```
User question: "How's the top line looking?"
        |
        v
   Query Classifier (Gemini Flash, few-shot)
   Returns: {query_type, metrics, section_hint, reasoning}
        |
        v
   Financial Jargon Resolution
   "top line" → adds "revenue" to metrics list
   "margins" → adds gross_profit + revenue + operating_income + net_income
              + ratios_needed: [gross_margin, operating_margin, net_margin]
        |
        v
   Route by Query Type:
   - NUMERICAL  → metrics SQL lookup (synonym-expanded) + 2 chunks for context
   - NARRATIVE  → 8 chunks via vector search, skip metrics lookup
   - SENTIMENT  → 8 chunks (default to MD&A section) + metrics
   - MIXED      → 5 chunks + metrics + ratios
        |
        v
   Hybrid Retrieval
   - Vector search: FinBERT embedding of question vs text_chunks (cosine)
   - Structured lookup: SELECT from metrics WHERE metric_name IN (synonyms)
   - Ratio computation: compute_all_ratios() over retrieved metrics
        |
        v
   Context Assembly
   (## Extracted Metrics + ## Computed Ratios + ## Relevant Document Excerpts)
        |
        v
   Grounded Answer Generation (Gemini Flash)
   Strict system prompt: answer ONLY from context, cite [Page N] / [Metric: name],
   say "I don't have enough information" if context is insufficient.
        |
        v
   Confidence Assessment (heuristic on retrieval quality + query type)
        |
        v
   Response: {answer, citations, query_type, confidence, metrics_used, ratios_computed}
```

### SEC Filing Section Detection

Standard sections to tag chunks with (for relevance boosting):
- Item 1: Financial Statements (tables)
- Item 2: MD&A (narrative — gold mine for analysis questions)
- Item 3: Quantitative Disclosures
- Item 4: Controls
- Part II Item 1: Legal
- Part II Item 1A: Risk Factors

A question about "risk" should prefer chunks from Risk Factors over random mentions elsewhere. SENTIMENT queries default `section_hint` to MD&A.

### Sentiment Analysis Approach

Two signal sources, both grounded in the uploaded document:

**Quantitative (from extracted metrics):**
- Within-document YoY changes (Revenue +9.6%, Net Income +9.3%, etc.)
- Trend detection across multiple uploaded periods if available
- All numbers sourced from document tables

**Qualitative (from document text + FinBERT):**
- Run FinBERT sentiment on MD&A chunks
- FinBERT was trained on 10,000+ financial texts — knows "restructuring charges" is negative, "strategic investment in growth" is positive
- Extract qualitative signals: "increased primarily due to...", "decline was driven by..."

Combined sentiment is always grounded in the document — never speculate beyond what's there. No external market data.

---

## Database Schema

```sql
CREATE EXTENSION vector;
CREATE EXTENSION pgcrypto;

-- Documents table
CREATE TABLE documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename    TEXT,
    company     TEXT NOT NULL,
    filing_type TEXT,                -- '10-Q', '10-K', 'press-release'
    period      TEXT,                -- 'Q3 2025'
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
    embedding   vector(768),       -- FinBERT output (768-dim)
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- Extracted tables (structured data as JSON)
CREATE TABLE extracted_tables (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    page_num    INT,
    table_type  TEXT,              -- 'income_statement', 'balance_sheet', etc.
    headers     JSONB,
    rows        JSONB NOT NULL,
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
```

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

# Query
POST   /api/query                    -- Ask a question
       Body: {question, document_ids?: [UUID]}
       Response: {answer, citations, query_type, confidence,
                  metrics_used, ratios_computed}

# Health
GET    /health                       -- Health check
```

---

## UI Design

### Core Principle
Two panels. Documents on the left, chat on the right. No mode selection — drop a PDF, ask questions about it.

### Layout
```
┌──────────────────────────────────────────────────────────────┐
│  FinSight   Grounded financial intelligence for SEC filings  │
├────────────────────┬─────────────────────────────────────────┤
│  DOCUMENTS         │  Ask a question                         │
│                    │  Querying 1 selected document           │
│  ┌──────────────┐  │                                         │
│  │  Drop PDFs   │  │  ┌───────────────────────────────────┐  │
│  │  here…       │  │  │  Try asking:                      │  │
│  └──────────────┘  │  │  • "What was revenue?"            │  │
│                    │  │  • "How's the top line?"          │  │
│  ────────────────  │  │  • "What are the risk factors?"   │  │
│  ☑ AAPL-10Q.pdf    │  │  • "What's the gross margin?"     │  │
│    Apple · 10-Q    │  │  • "Summarize MD&A on AI."        │  │
│    [ready]    ×    │  │                                   │  │
│                    │  └───────────────────────────────────┘  │
│  ☐ MSFT-10Q.pdf    │                                         │
│    [processing] ×  │  ┌───────────────────────────────────┐  │
│                    │  │  Ask about revenue, margins…  │Ask│  │
│                    │  └───────────────────────────────────┘  │
└────────────────────┴─────────────────────────────────────────┘
```

### Component Behavior
- **UploadZone** — drag-drop, click-to-browse. Validates 10MB/file, 4-file/40MB caps client-side before POST.
- **DocumentList** — checkbox-selectable (only ready docs). Status badge polls `/status` every 2.5s while processing. Delete button per row.
- **ChatPanel** — textarea + Ask button. Scopes query to selected docs (or all ready docs if none selected). Each assistant bubble shows confidence + query_type tags and an expandable citation list.
- **Adaptive responses** — when retrieval is empty the backend short-circuits the LLM call and returns "I don't have enough information in the uploaded documents to answer this. Make sure you've uploaded relevant SEC filings…"

---

## Deployment Architecture

```
Vercel (Frontend)              Render (Backend)              Neon (Database)
React + Vite                   FastAPI + Python               PostgreSQL + pgvector
Static files                   512MB RAM free tier            512MB storage free tier
No RAM concern                 Spins down after 15min idle    Managed, scales to zero
                     <-- API calls (HTTPS) -->     <-- SQL + pgvector queries -->
                                    |
                                    v
                              Gemini Flash
                              (free API)
                              15 RPM
```

### RAM Budget (Render Free Tier = 512MB)

```
FastAPI + dependencies:     ~80MB
pdfplumber (on demand):     ~30MB
FinBERT model:              ~110MB  (lazy loaded, shared between embedding + sentiment)
PDF in memory (1 file):     ~10MB   (process files one at a time, not all 4 at once)
Working overhead:           ~50MB
─────────────────────────────────
Total:                      ~280MB  (fits in 512MB with headroom)
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
│   │   │   └── query.py
│   │   ├── routers/             # API route handlers
│   │   │   ├── documents.py
│   │   │   └── query.py
│   │   ├── services/            # Business logic
│   │   │   ├── document_processor.py # Orchestrates the upload pipeline
│   │   │   ├── extraction.py         # PDF -> tables + text via pdfplumber
│   │   │   ├── metadata_detection.py # Company / filing type / period
│   │   │   ├── chunking.py           # Text -> chunks
│   │   │   ├── embedding.py          # Chunks -> vectors (FinBERT)
│   │   │   ├── metric_flattening.py  # Tables -> metrics rows
│   │   │   ├── retrieval.py          # Vector search + SQL lookup + ratio compute
│   │   │   ├── classifier.py         # Gemini Flash query classifier
│   │   │   ├── generation.py         # Gemini Flash grounded answer generation
│   │   │   └── sentiment.py          # FinBERT sentiment on MD&A chunks
│   │   ├── finance/             # Financial domain knowledge
│   │   │   ├── synonyms.py      # Metric synonym dictionary (~60 entries)
│   │   │   ├── jargon.py        # Financial jargon map (~30 entries)
│   │   │   └── ratios.py        # Computable ratio definitions (~20 formulas)
│   │   └── utils/
│   │       └── section_detector.py  # SEC filing section regex
│   ├── scripts/                 # Standalone test/dev scripts
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile               # For Render deployment (Phase 7)
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # Two-panel layout
│   │   ├── App.css              # All styling
│   │   ├── components/
│   │   │   ├── UploadZone.tsx       # Drag-drop file upload + client-side validation
│   │   │   ├── DocumentList.tsx     # Doc list with status polling + selection
│   │   │   └── ChatPanel.tsx        # Q&A with citations + confidence tags
│   │   ├── lib/
│   │   │   └── api.ts           # fetch wrapper for backend endpoints
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

---

## Build Plan

### Phase 1: Project Setup + Database ✅
**Goal:** Skeleton running locally, database connected

- [x] Initialize project structure (backend + frontend dirs)
- [x] FastAPI app with `/health` endpoint
- [x] config.py loading env vars (DATABASE_URL, GEMINI_API_KEY)
- [x] Async Postgres connection using asyncpg
- [x] schema.sql with all 4 tables + pgvector extension + all indexes
- [x] DB initialization on startup (run schema if tables don't exist)
- [x] React + Vite + TypeScript scaffold
- [x] Placeholder frontend page with FinSight branding
- [x] .gitignore, .env.example, README.md
- **Test:** `GET /health` returns 200, database connects, frontend renders

### Phase 2: PDF Upload + Extraction Pipeline ✅
**Goal:** Upload a PDF, extract text and tables, store in database

- [x] `POST /api/documents/upload` — accept PDF, validate size (10MB), save metadata
- [x] Metadata detection — parse company, filing type, period from filename + first page
- [x] Page-by-page processing with pdfplumber
- [x] Table extraction + quality validation (empty cells, inconsistent cols, no numbers)
- [x] Table parsing to structured JSON
- [x] Metric flattening — extract key numbers into metrics table
- [x] Text extraction + section detection (regex for SEC filing sections)
- [x] Text chunking with RecursiveCharacterTextSplitter
- [x] Processing status tracking (processing → ready/failed)
- [x] `GET /api/documents/{id}/status`
- [x] `GET /api/documents/{id}/tables`
- [x] `GET /api/documents/{id}/metrics`
- **Test:** Upload Apple 10-Q, verify extracted tables and metrics match actual PDF data

### Phase 3: Financial Intelligence Layer ✅
**Goal:** Encode finance domain knowledge as data, not LLM guesses

- [x] Metric synonym dictionary (`app/finance/synonyms.py`) — ~60 canonical metrics with synonyms
- [x] Financial jargon map (`app/finance/jargon.py`) — ~30 shorthand → metric mappings, with special multi-metric concepts ("margins", "leverage")
- [x] Ratio definitions (`app/finance/ratios.py`) — ~20 formulas with `compute_ratio` / `compute_all_ratios` and `ComputedRatio` dataclass
- **Test:** "How's the top line?" resolves to revenue. "What are the margins?" expands to gross_profit + revenue + operating_income + net_income and triggers gross/operating/net margin computation.

> **Note:** This phase originally bundled XBRL/EdgarTools integration. That entire branch was dropped (see Decision #19) — FinSight is now RAG-only over uploaded PDFs. Phase 3 is now scoped to the hand-built financial intelligence data files alone.

### Phase 4: Embeddings + Retrieval ✅
**Goal:** Chunks are searchable via finance-specific vector similarity and structured SQL

- [x] Lazy-load FinBERT on first request
- [x] Generate FinBERT embeddings for all text chunks during upload processing
- [x] Store embeddings in pgvector (768-dim)
- [x] Vector search function — query embedding vs stored chunk embeddings, return top-K
- [x] Structured search function — metric name lookup via SQL with synonym expansion
- [x] Hybrid retrieval — combine vector search + SQL metrics + computed ratios, deduplicate, rank
- [x] `DELETE /api/documents/{id}` — cascade delete
- [x] `GET /api/documents` — list all documents
- **Test:** Upload Apple 10-Q, search "profitability concerns" → matches "operating margin" chunks (FinBERT understands this)

### Phase 5: Query Pipeline + Answer Generation ✅
**Goal:** Ask a question in natural language, get a grounded answer with citations

- [x] Query classifier — Gemini Flash few-shot prompt returning `{query_type, metrics, section_hint, reasoning}`
- [x] Financial jargon resolution applied post-classification (adds metrics and `ratios_needed`)
- [x] Routing logic for 4 query types: NUMERICAL, NARRATIVE, MIXED, SENTIMENT (each tunes top_k and metric/section behavior)
- [x] Context assembly — markdown sections for ## Extracted Metrics, ## Computed Ratios, ## Relevant Document Excerpts
- [x] Grounded generation — Gemini Flash with strict 8-rule system prompt (cite [Page N] / [Metric: name], say "I don't have enough information" if context insufficient)
- [x] Confidence assessment heuristic per query type
- [x] Empty-retrieval short-circuit (skip LLM call, return canned upload-prompt message)
- [x] Response formatting — `{answer, citations, query_type, confidence, metrics_used, ratios_computed}`
- [x] `POST /api/query` endpoint
- **Test:** 215/215 unit tests pass. "How's the top line?" resolves to revenue via jargon map.

> **Note:** Original phase listed 7 query types including CROSS_DOC, CROSS_COMPANY, UNSUPPORTED. The first two collapsed when XBRL was dropped (CROSS_DOC is now naturally handled by passing multiple `document_ids`; CROSS_COMPANY is gone). UNSUPPORTED is handled by the empty-retrieval short-circuit instead of a dedicated type.

### Phase 6: Frontend ✅
**Goal:** Usable UI — upload docs, ask questions, see answers with citations

- [x] Two-panel layout (documents left, chat right)
- [x] UploadZone — drag-drop, 10MB/file + 40MB total client-side validation
- [x] DocumentList — selection checkboxes, delete button, status badge with 2.5s polling for processing docs
- [x] ChatPanel — question textarea, answer bubbles with confidence/query_type tags, expandable citation list
- [x] Adaptive empty state — prompts user to upload when no ready docs
- [x] Error handling — file too large, upload failed, backend unreachable, document still processing (409)
- [x] Shared TS types mirroring backend Pydantic models
- [x] `lib/api.ts` fetch wrapper with `ApiError` class
- **Test:** `tsc -b && vite build` clean, dev server boots and serves 200. Live browser flow still requires manual verification with running backend.

### Phase 7: Sentiment + Deploy ✅
**Goal:** FinBERT sentiment on MD&A, deployed live at $0

- [x] FinBERT sentiment service (`app/services/sentiment.py`) — `AutoModelForSequenceClassification` on MD&A chunks, per-chunk + aggregated positive/negative/neutral scores
- [x] Sentiment integrated into SENTIMENT query type — runs on retrieved chunks, injects analysis into generation context, returns scores in response
- [x] Sentiment displayed in frontend — tag in response metadata showing overall tone + confidence percentage
- [x] Backend Dockerfile for Render — CPU-only torch, slim Python 3.12
- [x] CORS configuration for production — comma-separated `FRONTEND_URL` env var for multiple origins
- [x] Cold-start UX in frontend — health-check polling with backoff, "waking up the server" banner
- [x] Cleaned up config — removed unused `sec_edgar_user_agent`, updated `.env.example`
- **Remaining (manual):** Render deployment, Vercel deployment, Neon database setup, end-to-end test on live URL, multi-doc cross-period testing

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
| 19 | **Drop XBRL/EdgarTools entirely** | RAG-only over uploaded PDFs | Scope simplification: the dual-path PDF extraction + financial intelligence layer + grounded RAG is already differentiated enough vs generic RAG demos. XBRL added significant scope (ticker search, cross-company, cross-verification, two pipelines) for marginal portfolio value. Cleaner story: "domain-aware RAG for SEC filings." | 2026-04-12 |
| 20 | Query types | 4 (NUMERICAL, NARRATIVE, MIXED, SENTIMENT) instead of 7 | CROSS_DOC handled by passing multiple `document_ids`. CROSS_COMPANY gone with XBRL. UNSUPPORTED handled by empty-retrieval short-circuit. | 2026-04-12 |
| 21 | UI layout | Two static panels (docs left, chat right) instead of unified "smart input" | Original mockup mixed ticker search and file drop into one input. With ticker search gone the unified input lost its purpose; explicit upload zone + doc list + chat is clearer. | 2026-04-12 |

---

## Current Status

**Phase:** All 7 phases complete (code-side). Deployment is the remaining manual step.

**What's done:** Full pipeline — PDF upload + dual-path extraction, financial intelligence layer (synonyms + jargon + ratios), FinBERT embeddings + hybrid retrieval, query classification + grounded generation, FinBERT sentiment on MD&A, React frontend with cold-start handling, Dockerfile for Render.

**What's left (manual):**
1. Deploy backend to Render (Docker, set `DATABASE_URL`, `GEMINI_API_KEY`, `FRONTEND_URL`)
2. Deploy frontend to Vercel (set `VITE_API_URL` to Render URL)
3. Run `schema.sql` on production Neon database
4. End-to-end test on live URL with a real 10-Q
5. Multi-document cross-period testing
