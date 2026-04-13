"""Query endpoint — the public entry point for the RAG pipeline.

Phase 10 dispatch:
  - Classify the question and extract company tickers in one LLM call.
  - Resolve tickers to CompanyInfo (cache-first, edgartools fallback).
  - Build a filing plan (one filing per company; cache-checked per accession).
  - If every filing is already cached: run the pipeline synchronously and
    return 200 with a full QueryResponse.
  - If any filing needs ingestion: create a job, kick off run_query_job as
    a background task, and return 202 with the job_id. The frontend polls
    GET /api/query/jobs/{id} until status is 'ready' or 'failed'.
"""
import logging
import time

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import JSONResponse

from app.db.connection import get_pool
from app.models.query import (
    QueryJobAccepted,
    QueryJobStatus,
    QueryRequest,
    QueryResponse,
)
from app.services.classifier import classify_query
from app.services.entity_resolution import resolve_entities
from app.services.filing_resolver import resolve_filings
from app.services.job_queue import create_job, get_job
from app.services.query_pipeline import run_query, run_query_job

logger = logging.getLogger(__name__)


async def _log_query(
    question: str,
    companies: list[str],
    query_type: str | None,
    filings_used: list[str],
    confidence: str | None,
    cache_hit: bool,
    response_time_ms: int,
) -> None:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO query_logs
                    (question, companies, query_type, filings_used, confidence, cache_hit, response_time_ms)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                question,
                companies,
                query_type,
                filings_used,
                confidence,
                cache_hit,
                response_time_ms,
            )
    except Exception as e:
        logger.warning(f"Failed to log query: {e}")

router = APIRouter(prefix="/api", tags=["query"])


def _rate_limited_response() -> QueryResponse:
    return QueryResponse(
        answer=(
            "The server is currently experiencing high demand. "
            "Please wait a moment and try again."
        ),
        citations=[],
        query_type="NARRATIVE",
        confidence="low",
        companies_resolved=[],
        filings_used=[],
    )


def _no_company_response(question: str) -> QueryResponse:
    return QueryResponse(
        answer=(
            "I couldn't identify a public company in your question. "
            "Try asking about a specific US public company by name or ticker — "
            "for example: 'How is Apple doing?' or 'What are NVIDIA's risk factors?'"
        ),
        citations=[],
        query_type="NARRATIVE",
        confidence="low",
        companies_resolved=[],
        filings_used=[],
    )


def _unresolved_response(unresolved: list[str]) -> QueryResponse:
    joined = ", ".join(f"'{s}'" for s in unresolved)
    return QueryResponse(
        answer=(
            f"I couldn't find {joined} on SEC EDGAR. Make sure you're asking about "
            "a US public company that files with the SEC."
        ),
        citations=[],
        query_type="NARRATIVE",
        confidence="low",
        companies_resolved=[],
        filings_used=[],
    )


def _no_filings_response(unresolved_tickers: list[str]) -> QueryResponse:
    joined = ", ".join(unresolved_tickers)
    return QueryResponse(
        answer=(
            f"I found {joined} on SEC EDGAR but couldn't locate a recent 10-Q or 10-K "
            "to answer this question."
        ),
        citations=[],
        query_type="NARRATIVE",
        confidence="low",
        companies_resolved=[],
        filings_used=[],
    )


@router.post(
    "/query",
    response_model=QueryResponse,
    responses={202: {"model": QueryJobAccepted}},
)
async def query_endpoint(req: QueryRequest, background_tasks: BackgroundTasks):
    """Ask a question about any US public company.

    Returns 200 with a QueryResponse on cache hit, or 202 with a
    QueryJobAccepted (job_id) when one or more filings need to be
    ingested from SEC EDGAR.
    """
    logger.info(f"Query: {req.question[:80]}")

    # 1. Classify + extract companies in one LLM call
    classification = await classify_query(req.question)

    if classification.get("_classifier_failed"):
        return _rate_limited_response()

    company_strings = classification.get("companies") or []
    if not company_strings:
        return _no_company_response(req.question)

    # 2. Resolve tickers/names -> CompanyInfo (uses cache, falls back to EDGAR)
    resolution = await resolve_entities(company_strings)
    if not resolution.resolved:
        return _unresolved_response(resolution.unresolved or company_strings)

    # 3. Build a filing plan: which filings per company, which are cached
    plan = await resolve_filings(
        companies=resolution.resolved,
        filings_needed=classification.get("filings_needed", [{"form": "10-Q", "count": 1}]),
    )

    if not plan.targets:
        return _no_filings_response(plan.unresolved or [c.ticker for c in resolution.resolved])

    # 4. Sync (cache hit) vs async (cache miss) dispatch
    if not plan.needs_ingestion:
        logger.info(f"Cache hit — running pipeline synchronously")
        t0 = time.monotonic()
        result = await run_query(req.question, classification, plan)
        elapsed = int((time.monotonic() - t0) * 1000)
        await _log_query(
            question=req.question,
            companies=[c.ticker for c in resolution.resolved],
            query_type=result.get("query_type"),
            filings_used=[f"{f.get('ticker')} {f.get('filing_type')} {f.get('period_label')}" for f in result.get("filings_used", [])],
            confidence=result.get("confidence"),
            cache_hit=True,
            response_time_ms=elapsed,
        )
        return QueryResponse(**result)

    # Some filings need fetching from EDGAR — go async
    job_id = await create_job()
    logger.info(
        f"Cache miss — created job {job_id[:8]} for "
        f"{sum(1 for t in plan.targets if t.needs_ingestion)} ingestion(s)"
    )
    background_tasks.add_task(run_query_job, job_id, req.question, classification, plan)

    miss_count = sum(1 for t in plan.targets if t.needs_ingestion)
    progress = (
        f"Fetching {miss_count} filing(s) from SEC EDGAR — this takes 1-3 minutes per filing."
    )
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={"job_id": job_id, "status": "processing", "progress": progress},
    )


@router.get("/query/jobs/{job_id}", response_model=QueryJobStatus)
async def get_query_job(job_id: str):
    """Poll the status of an async query job.

    Status values:
      - pending     job created, work not yet started
      - processing  background task is running (`progress` is human-readable)
      - ready       finished — `result` is a full QueryResponse
      - failed      finished with an error — `error` has the message
    """
    job = await get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")

    result_payload = None
    if job.result is not None:
        result_payload = QueryResponse(**job.result)

    return QueryJobStatus(
        job_id=job.id,
        status=job.status.value,
        progress=job.progress,
        result=result_payload,
        error=job.error,
    )
