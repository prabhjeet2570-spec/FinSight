"""End-to-end query pipeline orchestrator.

The query router stays thin: it just classifies, resolves entities,
builds a plan, and dispatches sync vs async. All the actual pipeline
work — ingestion-on-cache-miss, retrieval, generation, response
shaping — lives here so the same code runs whether the query is sync
(cache hit) or async (background job).

Public entry points:
  - run_query(question, classification, plan)
        Runs ingestion for any uncached targets, then retrieve+generate.
        Returns a fully-populated dict matching QueryResponse.
  - run_query_job(job_id, question, classification, plan)
        Same as above, but writes progress + result/error into the job
        queue. This is the function the router schedules as a background
        task on the cache-miss path.
"""
import logging
from uuid import UUID

from app.db.connection import get_pool
from app.services.classifier import classify_query  # noqa: F401  (re-export convenience)
from app.services.filing_ingestion import ingest_filing
from app.services.filing_resolver import FilingTarget, ResolutionPlan
from app.services.generation import generate_answer
from app.services.job_queue import set_error, set_progress, set_result
from app.services.retrieval import hybrid_retrieve
from app.services.sentiment import analyze_sentiment

logger = logging.getLogger(__name__)


# ---------- Per-query-type retrieval routing ----------

def _route_retrieval(classification: dict) -> tuple[list[str] | None, str | None, int]:
    """Choose metric_names, section_filter, top_k based on query type.

    Returns (metric_names, section_filter, top_k_chunks).
    """
    metric_names: list[str] | None = classification.get("metrics") or None
    section_hint: str | None = classification.get("section_hint")
    query_type = classification.get("query_type", "MIXED")

    top_k = 5
    if query_type == "NUMERICAL":
        top_k = 2
    elif query_type == "NARRATIVE":
        metric_names = None
        top_k = 8
    elif query_type == "SENTIMENT":
        top_k = 8
        section_hint = section_hint or "MD&A"

    return metric_names, section_hint, top_k


# ---------- Filing metadata enrichment ----------

async def _load_filings_used(filing_ids: list[UUID]) -> list[dict]:
    """Read filings metadata for the response payload."""
    if not filing_ids:
        return []
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id AS filing_id, ticker, filing_type, period_label,
                   accession_number, primary_doc_url
            FROM filings
            WHERE id = ANY($1::uuid[])
            ORDER BY filing_date DESC
            """,
            filing_ids,
        )
    return [dict(r) for r in rows]


# ---------- Ingestion sweep ----------

async def _ingest_misses(
    targets: list[FilingTarget],
    job_id: str | None = None,
) -> tuple[list[UUID], dict[UUID, str], list[str]]:
    """Run ingest_filing for each cache-miss target.

    Returns (filing_ids, filing_ticker_map, ingestion_errors).
    filing_ticker_map maps each filing_id -> company ticker (needed
    for multi-company context attribution in generation).
    """
    filing_ids: list[UUID] = []
    filing_ticker_map: dict[UUID, str] = {}
    errors: list[str] = []

    total = len(targets)
    for idx, target in enumerate(targets, 1):
        if not target.needs_ingestion:
            filing_ids.append(target.cached_filing_id)
            filing_ticker_map[target.cached_filing_id] = target.company.ticker
            continue

        if job_id:
            await set_progress(
                job_id,
                f"Fetching {target.company.ticker} {target.meta.form} from SEC EDGAR "
                f"({idx}/{total})…",
            )
        logger.info(
            f"Ingesting {target.company.ticker} {target.meta.form} "
            f"{target.meta.accession_number}"
        )

        result = await ingest_filing(target.company.ticker, target.meta.accession_number)

        if result.status == "ready":
            filing_ids.append(result.filing_id)
            filing_ticker_map[result.filing_id] = target.company.ticker
        else:
            errors.append(
                f"{target.company.ticker} {target.meta.accession_number}: {result.error}"
            )

    return filing_ids, filing_ticker_map, errors


# ---------- Pipeline ----------

async def run_query(
    question: str,
    classification: dict,
    plan: ResolutionPlan,
    job_id: str | None = None,
) -> dict:
    """Execute the full query pipeline against a filing plan.

    1. Ensure every target filing is ingested (no-op for cache hits).
    2. Run hybrid retrieval scoped to those filing_ids.
    3. Run sentiment if applicable.
    4. Generate the grounded answer.
    5. Shape the response payload (companies_resolved, filings_used, etc.).

    `job_id` is optional — when present, progress messages are written
    to the job queue so the polling client sees what's happening.
    """
    if job_id:
        await set_progress(job_id, "Resolving filings…")

    filing_ids, filing_ticker_map, ingestion_errors = await _ingest_misses(plan.targets, job_id=job_id)

    if not filing_ids:
        # Every ingestion failed — no point retrieving
        return {
            "answer": (
                "I couldn't fetch any filings from SEC EDGAR for your question. "
                + ("; ".join(ingestion_errors) if ingestion_errors else "")
            ),
            "citations": [],
            "query_type": classification.get("query_type", "MIXED"),
            "confidence": "low",
            "companies_resolved": list({
                t.company.ticker: {"ticker": t.company.ticker, "name": t.company.name, "cik": t.company.cik}
                for t in plan.targets
            }.values()),
            "filings_used": [],
            "metrics_used": None,
            "ratios_computed": None,
            "sentiment": None,
        }

    if job_id:
        await set_progress(job_id, "Searching filings…")

    metric_names, section_filter, top_k = _route_retrieval(classification)
    logger.info(
        f"Pipeline retrieve: filings={len(filing_ids)}, "
        f"type={classification.get('query_type')}, "
        f"metrics={metric_names}, section={section_filter}, top_k={top_k}"
    )

    retrieval_result = await hybrid_retrieve(
        query=question,
        filing_ids=filing_ids,
        metric_names=metric_names,
        section_filter=section_filter,
        top_k_chunks=top_k,
    )
    logger.info(
        f"Retrieved: {len(retrieval_result.chunks)} chunks, "
        f"{len(retrieval_result.metrics)} metrics, "
        f"{len(retrieval_result.ratios)} ratios"
    )

    sentiment_result = None
    if classification.get("query_type") == "SENTIMENT" and retrieval_result.chunks:
        if job_id:
            await set_progress(job_id, "Scoring sentiment with FinBERT…")
        chunk_texts = [c.text for c in retrieval_result.chunks]
        sentiment_result = analyze_sentiment(chunk_texts)
        logger.info(
            f"Sentiment: {sentiment_result.overall} "
            f"over {sentiment_result.analyzed_chunks} chunks"
        )

    if job_id:
        await set_progress(job_id, "Generating answer…")

    # Load filing metadata (needed for both generation context and response payload)
    filings_used = await _load_filings_used(filing_ids)

    # Build filing_id -> period_label map for consistent period display
    filing_period_map: dict = {}
    for f in filings_used:
        if f.get("period_label"):
            filing_period_map[f["filing_id"]] = f["period_label"]

    payload = await generate_answer(
        question=question,
        retrieval_result=retrieval_result,
        classification=classification,
        sentiment=sentiment_result,
        filing_ticker_map=filing_ticker_map,
        filing_period_map=filing_period_map,
        filings_used=filings_used,
    )

    # Enrich the payload with the new Phase 10 fields
    seen_tickers: set[str] = set()
    unique_companies: list[dict] = []
    for t in plan.targets:
        if t.company.ticker not in seen_tickers:
            seen_tickers.add(t.company.ticker)
            unique_companies.append(
                {"ticker": t.company.ticker, "name": t.company.name, "cik": t.company.cik}
            )
    payload["companies_resolved"] = unique_companies
    payload["filings_used"] = filings_used

    return payload


async def run_query_job(
    job_id: str,
    question: str,
    classification: dict,
    plan: ResolutionPlan,
) -> None:
    """Background-task wrapper around run_query.

    Writes progress / result / error into the job queue. Never raises;
    any exception is captured into the job's `error` field so the
    polling client sees it.
    """
    try:
        result = await run_query(question, classification, plan, job_id=job_id)
        await set_result(job_id, result)
    except Exception as e:
        logger.exception(f"Job {job_id} failed")
        await set_error(job_id, str(e))
