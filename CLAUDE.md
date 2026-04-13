# FinSight

## What This Is

A financial intelligence assistant for SEC filings. Users ask natural language questions about any US public company ("How is Apple doing?", "What are NVIDIA's risk factors?", "Compare Microsoft and Google margins") and the system:

1. Detects the company (or companies) from the question
2. Fetches the relevant filings from SEC EDGAR on demand (HTML + XBRL)
3. Runs domain-aware RAG over the fetched filings
4. Returns grounded answers with section + filing citations

**No file uploads. No setup. Just ask.**

**This is NOT a generic document Q&A tool.** It has domain-specific financial intelligence: dual-path filing extraction (HTML narrative + tables + XBRL structured facts), FinBERT embeddings, financial jargon understanding, and computed financial ratios.

**Portfolio project for Prabhjeet Singh** (NYU MS CS student). Demonstrates backend/ML engineering, domain-specific intelligence design, and end-to-end system design (entity resolution, external API fetch, ingestion pipeline, RAG, grounded generation).

---

## Core Requirements

1. **Strictly grounded answers** — answers come ONLY from fetched SEC filings. Never hallucinate.
2. **Self-serve, no uploads** — the system fetches filings from SEC EDGAR based on the company detected in the question.
3. **Dual-path extraction** — narrative text + tables from HTML, plus structured facts from XBRL.
4. **Caching by accession number** — fetched filings are processed once and reused.
5. **Multi-company queries** — entity extraction supports >1 company per question for comparison queries.
6. **Financial sentiment analysis** — within-filing YoY comparisons + FinBERT on MD&A text.
7. **Free deployment** — $0 cost using free tiers only.
8. **Open-source models** for embedding and sentiment (no paid API for these).
9. **SEC EDGAR compliance** — User-Agent header with contact info, rate-limited to 10 req/sec.

---

## Financial Intelligence Layer

Encoded domain knowledge that ships with the app:

**1. Metric Synonym Dictionary (~60 entries)** — `app/finance/synonyms.py`
Maps financial terms across different reporting styles: "revenue" = "net sales" = "total net sales" = "net revenue" = "top line", etc.

**2. Financial Jargon Map (~30 entries)** — `app/finance/jargon.py`
Maps analyst shorthand to metrics: "top line" -> revenue, "bottom line" -> net income, "margins" -> expands to multiple metrics + triggers ratio computation.

**3. Computable Ratio Definitions (~20 formulas)** — `app/finance/ratios.py`
Standard financial ratios computed in code, not by the LLM: gross margin, operating margin, net margin, YoY growth, debt-to-equity, etc.

**4. XBRL Concept Map** — `app/finance/xbrl_concepts.py`
Maps us-gaap XBRL tags to canonical metric names.

**5. FinBERT** — finance-trained embeddings and sentiment. Understands that "profitability concerns" and "operating margin compression" are related.

---

## Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| **Backend** | FastAPI (Python) | Best ML/NLP ecosystem, async, auto-docs |
| **Frontend** | React + Vite + TypeScript | Simple SPA, no SSR needed |
| **Database** | PostgreSQL + pgvector (Neon) | One DB for relational + vector search. Free 512MB |
| **SEC EDGAR** | `edgartools` + BeautifulSoup + lxml | Wraps EDGAR API; HTML extraction with explicit table/section tags |
| **XBRL** | `edgartools` built-in | Structured numerical facts by concept tag |
| **Entity Extraction** | DeepSeek Chat V3 via OpenRouter | Single LLM call extracts query type + target companies |
| **Embeddings** | ProsusAI/finbert (768-dim) | Finance-specific; "bearish" matches "declining revenue" |
| **Sentiment** | ProsusAI/finbert | Trained on 10K+ financial texts |
| **Generation** | DeepSeek Chat V3 via OpenRouter | Free tier, OpenAI-compatible API |
| **Chunking** | LangChain RecursiveCharacterTextSplitter | Just this one utility |
| **Deployment** | Vercel + HuggingFace Spaces + Neon | All free tier, $0 total |

---

## Architecture

### End-to-End Flow

```
User question: "How is Apple's revenue trending?"
       |
       v
   Query Classifier + Entity Extractor (Groq Llama 3.3 70B, single call)
   Returns: {query_type, metrics, section_hint, companies: ["AAPL"], filing_strategy}
       |
       v
   Filing Resolution
   For each company:
     - Look up CIK from ticker
     - Determine which filings are needed (10-Q? 10-K? trend -> multiple?)
     - Check cache for already-processed accession numbers
       |
       +---------- cache hit ----------+
       |                               |
       v                               |
   EDGAR Fetch (cache misses only)     |
   - edgartools: fetch HTML + XBRL     |
       |                               |
       v                               |
   Ingestion Pipeline (once per filing, cached)
       |                               |
       +-------------+-----------------+
                     |
                     v
   Hybrid Retrieval (scoped to resolved filings)
   - Vector search: FinBERT embedding vs text_chunks (cosine)
   - Structured lookup: metrics WHERE metric_name IN (synonyms)
   - Ratio computation: compute_all_ratios() over retrieved metrics
       |
       v
   Context Assembly (## Metrics + ## Ratios + ## Excerpts)
       |
       v
   Grounded Answer Generation (Groq Llama 3.3 70B)
   Strict system prompt: answer ONLY from context, cite sources
       |
       v
   Response: {answer, citations, query_type, confidence,
              companies_resolved, filings_used, metrics_used, ratios_computed}
```

### Filing Ingestion Pipeline (per filing, runs once)

```
EDGAR fetch -> HTML + XBRL bytes
       |
       +------------------+------------------+
       |                                     |
       v                                     v
   HTML PARSE (BeautifulSoup)             XBRL PARSE (edgartools)
       |                                     |
       +---- tables ----+                    v
       |                |              Structured facts by
       v                v              concept tag + period
   Text per section   Table to JSON         |
   (header tags for      |                  v
    section tagging)     v              Map to canonical
       |             extracted_tables    metric names
       v                |                   |
   Chunking +           v                   v
   Embed (FinBERT)   extracted_tables    metrics table
       |              table              (XBRL preferred,
       v                |                HTML fallback)
   text_chunks          |                   |
   table                +-------------------+
       |                         |
       +-------------------------+
                  |
                  v
           Mark filing 'ready'
```

### Query Pipeline

```
User question -> Classify + extract (single Groq call)
  -> Financial jargon resolution ("top line" -> revenue)
  -> Filing resolution (cache check + EDGAR fetch if needed)
  -> Route by query type:
     NUMERICAL  -> metrics SQL lookup + 2 chunks for context
     NARRATIVE  -> 8 chunks via vector search
     SENTIMENT  -> 8 MD&A chunks + metrics + FinBERT sentiment
     MIXED      -> 5 chunks + metrics + ratios
  -> Hybrid retrieval (scoped to resolved filing_ids)
  -> Context assembly
  -> Grounded answer generation
  -> Confidence assessment
  -> Response
```

### Filing Resolution Heuristics

| Query Intent | Filings to Fetch |
|---|---|
| Latest snapshot ("how is X doing?") | Latest 10-Q (or 10-K if no recent 10-Q) |
| Annual / risks / business overview | Latest 10-K |
| Trend ("how is X trending?", "YoY") | Latest 10-K + last 4 10-Qs |
| Recent events ("any recent news?") | Latest 5-10 8-Ks |
| Comparison ("compare X and Y") | Latest 10-Q for each company |
| Executive compensation | Latest DEF 14A |
| Foreign company | Latest 20-F |

### Sentiment Analysis

Two signal sources, both grounded in the filing:

- **Quantitative**: within-filing YoY changes from XBRL/HTML metrics, trend detection across periods
- **Qualitative**: FinBERT sentiment on MD&A chunks, extracting directional signals

---

## Database Schema

5 tables: `companies`, `filings`, `text_chunks`, `extracted_tables`, `metrics`

See `backend/app/db/schema.sql` for full definitions. Key design:

- **`companies`** — cached EDGAR ticker/CIK lookup
- **`filings`** — one row per fetched filing, keyed by `accession_number` (UNIQUE). Status: processing/ready/failed
- **`text_chunks`** — narrative chunks with FinBERT 768-dim embeddings, section tags, filing_id FK
- **`extracted_tables`** — HTML tables as JSONB (headers + rows)
- **`metrics`** — flattened key numbers. `source` field: 'xbrl' (preferred) or 'html_table' (fallback)

Storage: ~4.5MB per company (1x10-K + 4x10-Q + 5x8-K). ~100 companies fit in Neon's 512MB free tier. LRU eviction via `storage_eviction.py`.

---

## API

```
POST   /api/query                    -- Ask a question about any company
       Body: {question: str}
       Returns 200 (cache hit) or 202 + job_id (cache miss)

GET    /api/query/jobs/{job_id}      -- Poll async query status
       Response: {status, progress?, result?}

GET    /health                       -- Health check
```

The 202 pattern exists because first queries trigger EDGAR fetch + ingestion (60-180s), which exceeds standard HTTP timeouts.

---

## UI

Single-column chat interface. Dark theme with glass morphism, ambient gradient orbs, and smooth animations.

- **ChatPanel** — conversation view with suggested-question chips on first load
- **JobProgress** — inline progress for async queries ("Fetching from EDGAR...", "Extracting...", etc.)
- **AnswerBubble** — confidence + query_type tags, per-company filing tags, expandable citations
- **CompanyChip** — filing label renderer (e.g., "AAPL - 10-Q - Q3 2025")

---

## Deployment

```
Vercel (Frontend)          HuggingFace Spaces (Backend)   Neon (Database)
React + Vite               FastAPI + Python                PostgreSQL + pgvector
Static files               16GB RAM free tier              512MB storage free tier
                  <-- HTTPS -->                <-- SQL + pgvector -->
                                   |
                                   +--> SEC EDGAR (HTTPS, User-Agent required)
                                   +--> OpenRouter API (free tier, OpenAI-compatible)
```

### RAM Budget (16GB on HuggingFace Spaces)

~370MB total at baseline: FastAPI (~80MB) + edgartools/httpx (~20MB) + BS4/lxml (~15MB) + FinBERT embedding model (~110MB) + FinBERT sentiment model (~110MB) + working overhead (~35MB). Well within HF Spaces 16GB free tier.

### Cold Starts

1. **Server**: ~30s after inactivity. UI shows "Warming up the server..."
2. **First query for new company**: 60-180s for EDGAR fetch + ingestion. UI shows progress steps. Cached companies respond in seconds.

---

## Project Structure

```
finsight/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app, CORS, lifespan
│   │   ├── config.py                # DATABASE_URL, GROQ_API_KEY, EDGAR_USER_AGENT, FRONTEND_URL
│   │   ├── db/
│   │   │   ├── connection.py        # Async Postgres pool + schema migration
│   │   │   └── schema.sql           # 5 tables: companies, filings, text_chunks, extracted_tables, metrics
│   │   ├── models/
│   │   │   └── query.py             # Pydantic request/response schemas
│   │   ├── routers/
│   │   │   └── query.py             # POST /api/query, GET /api/query/jobs/{id}
│   │   ├── services/
│   │   │   ├── query_pipeline.py    # Orchestrates sync vs async dispatch
│   │   │   ├── classifier.py        # Groq Llama 3.3 70B: query type + entity extraction
│   │   │   ├── entity_resolution.py # Company name -> ticker resolution
│   │   │   ├── filing_resolver.py   # (companies, query_type) -> filing_ids
│   │   │   ├── edgar_client.py      # edgartools wrapper: fetch HTML + XBRL
│   │   │   ├── filing_ingestion.py  # fetch -> extract -> chunk -> embed -> cache
│   │   │   ├── html_extraction.py   # BeautifulSoup: HTML -> text + tables + sections
│   │   │   ├── xbrl_extraction.py   # XBRL -> metrics rows
│   │   │   ├── chunking.py          # RecursiveCharacterTextSplitter
│   │   │   ├── embedding.py         # FinBERT 768-dim embeddings
│   │   │   ├── metric_flattening.py # HTML tables -> metrics (XBRL fallback)
│   │   │   ├── retrieval.py         # Vector search + SQL lookup + ratio compute
│   │   │   ├── generation.py        # Grounded answer generation
│   │   │   ├── sentiment.py         # FinBERT sentiment on MD&A
│   │   │   ├── job_queue.py         # In-memory async job tracking
│   │   │   └── storage_eviction.py  # LRU cache eviction
│   │   ├── finance/
│   │   │   ├── synonyms.py          # ~60 metric synonym entries
│   │   │   ├── jargon.py            # ~30 jargon -> metric mappings
│   │   │   ├── ratios.py            # ~20 ratio formulas
│   │   │   └── xbrl_concepts.py     # us-gaap concept -> canonical name map
│   │   └── utils/
│   │       └── html_section_detector.py
│   ├── scripts/
│   │   └── seed_companies.py        # Populate companies table from EDGAR
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── App.tsx                  # Health check polling, main layout
│   │   ├── App.css                  # Dark theme, glass morphism, animations
│   │   ├── index.css                # CSS variables, color scheme
│   │   ├── config.ts                # API_BASE_URL
│   │   ├── lib/api.ts               # Fetch wrapper, sync/async handling
│   │   ├── types/index.ts           # TypeScript types mirroring backend
│   │   └── components/
│   │       ├── ChatPanel.tsx        # Main chat interface + job polling
│   │       ├── AnswerBubble.tsx     # Response display + citations
│   │       ├── JobProgress.tsx      # Loading progress for async queries
│   │       └── CompanyChip.tsx      # Filing label (AAPL - 10-Q - Q3 2025)
│   ├── package.json
│   ├── tsconfig.json
│   └── vite.config.ts
├── CLAUDE.md
├── README.md
└── .gitignore
```

---

## Design Decisions

| # | Decision | Choice | Reason |
|---|----------|--------|--------|
| 1 | Frontend | React + Vite (not Next.js) | SPA, no SSR/SEO needed |
| 2 | Database | PostgreSQL + pgvector on Neon | One DB for relational + vector, one free tier |
| 3 | Orchestration | Roll our own (not LangChain/LlamaIndex) | Full control, less abstraction |
| 4 | Embeddings | FinBERT (not all-MiniLM-L6-v2) | Finance-specific, better retrieval for financial queries |
| 5 | Sentiment | FinBERT sentiment variant | Trained on 10K+ financial texts |
| 6 | Generation LLM | DeepSeek Chat V3 via OpenRouter (not Gemini/OpenAI) | Free tier, OpenAI-compatible API, strong reasoning |
| 7 | Filing source | SEC EDGAR (not user uploads) | Stronger product story, more system design to demonstrate |
| 8 | EDGAR client | `edgartools` (not raw HTTP) | Maintained wrapper, handles EDGAR quirks |
| 9 | Filing format | HTML primary, XBRL for metrics | HTML has explicit tags; XBRL gives clean numbers but no narrative |
| 10 | UI layout | Single-column chat | The chat IS the app — one input, ask anything |
| 11 | Query API | Async (200 cache hit, 202 + polling for cache miss) | First queries take 60-180s, exceeds HTTP timeout |
| 12 | Cache key | `accession_number` (UNIQUE) | EDGAR's globally unique filing ID |
| 13 | Storage policy | LRU eviction at ~80% of Neon free tier | ~100 companies fit, evict oldest when full |
| 14 | Query types | 4: NUMERICAL, NARRATIVE, MIXED, SENTIMENT | Covers all question categories |
| 15 | Processing | One filing at a time | Keeps peak RAM under 512MB |
| 16 | Financial intelligence | Hand-built synonyms + jargon + ratios as data | Not LLM-guessed |
| 17 | Sentiment approach | Within-filing YoY + FinBERT on MD&A | Grounded in filing data, no external market data |

---

## Current Status

**All core features are implemented and deployed.**

- SEC EDGAR fetch + HTML/XBRL extraction
- Financial intelligence layer (synonyms, jargon, ratios)
- FinBERT embeddings + hybrid retrieval
- Query classification + entity extraction (DeepSeek Chat V3 via OpenRouter)
- Filing resolution with cache-first strategy
- Async query pipeline with job polling
- Grounded answer generation with citations
- FinBERT sentiment analysis
- LRU storage eviction
- Premium dark UI with glass morphism and animations

**Deployed:** Frontend on Vercel (`finsight-xi-ten.vercel.app`), backend on HuggingFace Spaces (`prabhjeet5201-finsight.hf.space`), database on Neon.

**Next:** Build the news sentiment + stock prediction layer (see below).

---

## Planned: News Sentiment + Stock Prediction Layer

Adds real-time financial news gathering and ML-based stock price direction prediction on top of the existing SEC filing intelligence.

### Why This Matters

SEC filings are the foundation — they provide deep, grounded financial data. News + prediction adds a forward-looking signal layer. The two together create a full financial intelligence platform that no other portfolio project combines: filing RAG + news sentiment + price prediction in one deployed web app.

### Data Sources

| Source | What | Free Tier |
|--------|------|-----------|
| **Finnhub** (`finnhub-python`) | Company news + stock prices | 60 calls/min, no daily cap, no deployment restrictions |
| **yfinance** | Historical OHLCV bulk backfill | No API key, unofficial |

Finnhub is the primary source for both news and daily price updates. yfinance is for one-time historical backfill (2-3 years of daily prices per ticker). Avoid NewsAPI (localhost-only on free tier) and Alpha Vantage (25 req/day).

### ML Approach: FinBERT-LSTM

FinBERT is already loaded (~110MB). The prediction pipeline reuses it for news sentiment:

```
Daily News Articles -> FinBERT Sentiment Scores
                              |
                    Daily Sentiment Features
                    (avg score, volume, momentum)
                              |
Historical Prices -> Price Features ----> LSTM (2-layer) -> Next-day Direction
                    (returns, MAs,              ^              (up/down)
                     volume, RSI)               |
                              |                 |
SEC Filing Metrics -> Filing Features ----------+
                    (earnings growth,
                     MD&A sentiment)
```

**Realistic accuracy**: 55-63% directional accuracy out-of-sample. Sentiment adds ~8-12% relative improvement over price-only models. Frame as engineering + methodology demonstration, not market-beating claims.

### New Database Tables

```sql
-- News articles (cached, deduplicated by finnhub_id)
CREATE TABLE IF NOT EXISTS news_articles (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    finnhub_id      BIGINT UNIQUE,
    ticker          TEXT NOT NULL,
    headline        TEXT NOT NULL,
    summary         TEXT,
    source          TEXT,
    url             TEXT,
    published_at    TIMESTAMPTZ NOT NULL,
    sentiment_pos   NUMERIC,
    sentiment_neg   NUMERIC,
    sentiment_neu   NUMERIC,
    sentiment_label TEXT,
    fetched_at      TIMESTAMPTZ DEFAULT now()
);

-- Daily stock prices (OHLCV, cached)
CREATE TABLE IF NOT EXISTS stock_prices (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker      TEXT NOT NULL,
    trade_date  DATE NOT NULL,
    open        NUMERIC,
    high        NUMERIC,
    low         NUMERIC,
    close       NUMERIC NOT NULL,
    volume      BIGINT,
    adj_close   NUMERIC,
    source      TEXT DEFAULT 'yfinance',
    UNIQUE(ticker, trade_date)
);

-- Prediction results (cached, refreshed daily)
CREATE TABLE IF NOT EXISTS predictions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticker           TEXT NOT NULL,
    prediction_date  DATE NOT NULL,
    target_date      DATE NOT NULL,
    direction        TEXT,
    confidence       NUMERIC,
    predicted_change NUMERIC,
    features_used    JSONB,
    model_version    TEXT,
    created_at       TIMESTAMPTZ DEFAULT now(),
    UNIQUE(ticker, prediction_date, target_date)
);
```

Storage impact: ~15MB for 100 tickers with 3 years of data. Negligible within Neon's 512MB.

### New Backend Files

```
backend/app/
├── services/
│   ├── news_client.py          # Finnhub news fetching + caching
│   ├── price_client.py         # yfinance bulk + Finnhub daily price fetching
│   └── prediction.py           # FinBERT-LSTM prediction pipeline
├── models/
│   └── prediction.py           # Pydantic schemas for prediction requests/responses
├── routers/
│   └── predictions.py          # GET /api/predictions/{ticker}
└── ml/
    ├── features.py             # Feature engineering (sentiment + price + filing signals)
    ├── lstm_model.py           # LSTM model definition (PyTorch)
    └── trained_models/         # Serialized model weights
```

### New Dependencies

`finnhub-python`, `yfinance`. PyTorch is already in the stack via FinBERT. RAM impact: ~10-15MB additional.

### Data Fetching Strategy

On-demand, same pattern as EDGAR: user asks a prediction question -> fetch news + prices for that ticker -> cache in DB -> run inference. No background scheduler needed (Render free tier sleeps after 15min anyway). Same async 202 + job polling pattern for first requests.

### Build Phases

| Phase | Work | Effort |
|-------|------|--------|
| **1: Data Infra** | Finnhub + yfinance clients, new DB tables, caching | 1-2 days |
| **2: News Sentiment** | FinBERT on news headlines+summaries, daily aggregation | 1 day |
| **3: Features + Model** | Price + sentiment + filing feature engineering, LSTM training (local/Colab), export weights | 2-3 days |
| **4: Serving + Frontend** | Prediction API endpoint, prediction card in UI, disclaimer | 1-2 days |
| **5: Evaluation** | Backtest results, accuracy vs baselines, feature importance | 1-2 days |

### Key Features to Engineer

**From news (via FinBERT)**: daily avg sentiment, sentiment volatility, news volume, sentiment momentum (5/10 day trend)

**From SEC filings (already have)**: MD&A sentiment, revenue/earnings growth, YoY metric changes, filing recency

**From price data**: daily returns, moving averages (5/10/20/50 day), rolling volatility, volume changes, RSI, MACD

### Evaluation Approach

Show honest comparison against baselines:

| Model | Expected Directional Accuracy |
|-------|-------------------------------|
| Naive (always up) | ~52% |
| Price-only LSTM | ~57% |
| Sentiment-only | ~55% |
| Combined (sentiment + price + filing) | ~60-63% |

### Disclaimer (Required)

Every prediction must display: "Educational project — not financial advice. Predictions are ML model outputs for demonstration purposes only. Do not make investment decisions based on this tool."

### How to Frame for Portfolio

"Multi-modal ML pipeline that quantifies the relationship between news sentiment, SEC filing signals, and short-term price movements. FinBERT-LSTM with honest evaluation against baselines." Show the engineering + methodology, not market-beating claims.
