# FinSight

Financial intelligence assistant for SEC filings. Ask natural language questions about any US public company — revenue, risks, management outlook, and more. The system fetches filings from SEC EDGAR on demand, runs domain-aware RAG, and returns grounded answers with citations.

**No file uploads. No setup. Just ask.**

## What Makes This Different

- **Dual-path extraction** — narrative text from HTML + structured metrics from XBRL
- **Computed financial ratios** — margins, growth rates, leverage computed in code, not by the LLM
- **Financial intelligence layer** — 60 metric synonyms, 30 jargon mappings, 20 ratio formulas
- **FinBERT** — finance-trained embeddings and sentiment analysis
- **Fully free** — $0 deployment cost

## Tech Stack

| Layer | Choice |
|-------|--------|
| Backend | FastAPI + asyncpg + pgvector |
| Frontend | React + Vite + TypeScript |
| Database | PostgreSQL + pgvector (Neon) |
| Embeddings/Sentiment | FinBERT (ProsusAI/finbert) |
| Generation | DeepSeek Chat V3 via OpenRouter |
| SEC Data | edgartools + BeautifulSoup + XBRL |
| Deployment | Vercel (frontend) + HuggingFace Spaces (backend) + Neon (DB) |

## Development

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in your values
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Environment Variables

Copy `backend/.env.example` to `backend/.env` and fill in:

- `DATABASE_URL` — Neon PostgreSQL connection string
- `LLM_API_KEY` — OpenRouter API key (free tier)
- `LLM_BASE_URL` — LLM endpoint (default: `https://openrouter.ai/api/v1`)
- `LLM_MODEL` — Model name (default: `deepseek/deepseek-chat-v3-0324`)
- `EDGAR_USER_AGENT` — Your name and email (SEC requires identification)
- `FRONTEND_URL` — Frontend origin for CORS (default: `http://localhost:5173`)

## License

MIT
