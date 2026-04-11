# FinSight

Financial intelligence tool combining document RAG with SEC EDGAR structured data to analyze US public companies.

- **Ticker search** -- instant structured metrics from XBRL, no upload needed
- **Document upload** -- deep narrative analysis of SEC filings (10-Q, 10-K)
- **Combined** -- both, with cross-verification

## Tech Stack

- **Backend:** FastAPI + asyncpg + pgvector
- **Frontend:** React + Vite + TypeScript
- **Database:** PostgreSQL + pgvector (Neon)
- **Embeddings/Sentiment:** FinBERT
- **Generation:** Gemini 2.0 Flash
- **XBRL Data:** EdgarTools

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

- `DATABASE_URL` -- Neon PostgreSQL connection string
- `GEMINI_API_KEY` -- Google AI Studio API key
- `SEC_EDGAR_USER_AGENT` -- Your name and email (SEC requires identification)

## License

MIT
