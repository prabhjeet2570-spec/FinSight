"""Filing ingestion orchestrator.

Given a (cik, ticker, accession_number) — or just the accession from a
FilingMeta — this module runs the full pipeline:

  1. fetch_filing      EDGAR HTML + XBRL via edgar_client (network)
  2. extract_html      BeautifulSoup -> sections + tables + page count
  3. extract_xbrl      XBRL facts -> canonical metrics (preferred path)
  4. flatten_html      HTML tables -> canonical metrics (fallback only)
  5. chunk_sections    sections -> chunks (RecursiveCharacterTextSplitter)
  6. embed_texts       chunks -> 768-dim FinBERT vectors
  7. INSERT            companies (upsert), filings, text_chunks,
                       extracted_tables, metrics — all in one transaction

The filings row goes from status='processing' -> 'ready' (or 'failed' on
exception). On 'ready', the cache is populated and subsequent queries hit
it directly. On 'failed', the row remains so we can show the error in the
UI and so retry logic can target it.

The whole pipeline is async-friendly: edgar_client and embed_texts already
wrap their sync work, and the SQL writes are async.
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from app.db.connection import get_pool
from app.services.chunking import chunk_sections
from app.services.edgar_client import (
    CompanyInfo,
    FetchedFiling,
    FilingMeta,
    fetch_filing,
    get_company,
)
from app.services.embedding import embed_texts
from app.services.html_extraction import extract_html
from app.services.metric_flattening import flatten_html_tables
from app.services.storage_eviction import evict_if_needed
from app.services.xbrl_extraction import extract_xbrl_metrics

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    filing_id: UUID
    accession_number: str
    chunk_count: int
    metric_count: int
    table_count: int
    page_count: int
    status: str  # 'ready' or 'failed'
    error: str | None = None


# ---------- Helpers ----------


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _period_label(form: str, period_of_report: date | None) -> str | None:
    """Build a human-readable period label like 'Q3 2025' or 'FY 2025 (ended Jan 2026)'.

    For 10-K filings, we show the calendar year the fiscal year mostly falls in,
    plus the actual end date to avoid confusion (e.g., NVIDIA's FY 2026 ends Jan 2026).
    For 10-Q filings, we use the calendar quarter of the period_of_report date.
    """
    if not period_of_report:
        return None
    if form.upper().startswith("10-K") or form.upper().startswith("20-F"):
        month_name = period_of_report.strftime("%b")
        return f"FY {period_of_report.year} (ended {month_name} {period_of_report.year})"
    if form.upper().startswith("10-Q"):
        q = (period_of_report.month - 1) // 3 + 1
        return f"Q{q} {period_of_report.year}"
    return None


# ---------- Cache check ----------


async def get_cached_filing_id(accession_number: str) -> UUID | None:
    """Return the filing_id if this accession is cached and ready, else None."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM filings WHERE accession_number = $1 AND status = 'ready'",
            accession_number,
        )
    return row["id"] if row else None


# ---------- Company upsert ----------


async def _upsert_company(company: CompanyInfo) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO companies (cik, ticker, name, sic, last_synced)
            VALUES ($1, $2, $3, $4, now())
            ON CONFLICT (cik) DO UPDATE
                SET ticker = EXCLUDED.ticker,
                    name = EXCLUDED.name,
                    sic = EXCLUDED.sic,
                    last_synced = now()
            """,
            company.cik, company.ticker, company.name, company.sic,
        )


# ---------- Filing row create / update ----------


async def _create_filing_row(
    company: CompanyInfo,
    meta: FilingMeta,
) -> UUID:
    period_dt = _parse_date(meta.period_of_report)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO filings (
                cik, ticker, accession_number, filing_type, filing_date,
                period_of_report, period_label, primary_doc_url, status
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'processing')
            ON CONFLICT (accession_number) DO UPDATE
                SET status = 'processing',
                    error_message = NULL,
                    filing_date = EXCLUDED.filing_date,
                    period_of_report = EXCLUDED.period_of_report,
                    period_label = EXCLUDED.period_label,
                    primary_doc_url = EXCLUDED.primary_doc_url
            RETURNING id
            """,
            company.cik,
            company.ticker,
            meta.accession_number,
            meta.form,
            _parse_date(meta.filing_date),
            period_dt,
            _period_label(meta.form, period_dt),
            meta.primary_doc_url,
        )
    return row["id"]


async def _mark_filing_ready(
    filing_id: UUID,
    chunk_count: int,
    metric_count: int,
    page_count: int,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE filings
               SET status = 'ready',
                   chunk_count = $2,
                   metric_count = $3,
                   page_count = $4,
                   error_message = NULL
             WHERE id = $1
            """,
            filing_id, chunk_count, metric_count, page_count,
        )


async def _mark_filing_failed(filing_id: UUID, error: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE filings SET status = 'failed', error_message = $2 WHERE id = $1",
            filing_id, error[:1000],
        )


# ---------- Inserts: chunks / tables / metrics ----------


async def _insert_chunks(filing_id: UUID, chunks: list, embeddings: list[list[float]]) -> None:
    if not chunks:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        from pgvector.asyncpg import register_vector
        await register_vector(conn)
        await conn.executemany(
            """
            INSERT INTO text_chunks (filing_id, chunk_text, page_num, section, chunk_index, embedding)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            [
                (filing_id, c.text, c.page_num, c.section, c.chunk_index, emb)
                for c, emb in zip(chunks, embeddings)
            ],
        )


async def _insert_tables(filing_id: UUID, tables: list) -> None:
    if not tables:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO extracted_tables (filing_id, page_num, table_type, headers, rows)
            VALUES ($1, $2, $3, $4, $5)
            """,
            [
                (
                    filing_id,
                    t.page_num,
                    None,
                    json.dumps(t.headers),
                    json.dumps(t.rows),
                )
                for t in tables
            ],
        )


async def _insert_metrics(
    filing_id: UUID,
    xbrl_metrics: list,
    html_metrics: list,
) -> int:
    rows: list[tuple] = []

    for m in xbrl_metrics:
        rows.append((
            filing_id, m.metric_name, m.value, m.prior_value, m.change_pct,
            m.unit, m.period, m.prior_period, "xbrl", m.xbrl_concept, None, None,
        ))

    for m in html_metrics:
        rows.append((
            filing_id, m.metric_name, m.value, m.prior_value, m.change_pct,
            m.unit, None, None, "html_table", None, m.page_num, m.table_type,
        ))

    if not rows:
        return 0

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO metrics (
                filing_id, metric_name, value, prior_value, change_pct,
                unit, period, prior_period, source, xbrl_concept, page_num, table_type
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
            """,
            rows,
        )

    return len(rows)


# ---------- Sync extraction (CPU-bound) ----------


def _run_extraction_sync(fetched: FetchedFiling) -> tuple:
    """Run all CPU-bound extraction work in one shot for asyncio.to_thread."""
    doc = extract_html(fetched.html)
    xbrl_metrics = extract_xbrl_metrics(fetched.xbrl) if fetched.xbrl is not None else []
    skip = {m.metric_name for m in xbrl_metrics}
    html_metrics = flatten_html_tables(doc.tables, skip_metrics=skip)
    chunks = chunk_sections(doc.sections)
    return doc, xbrl_metrics, html_metrics, chunks


# ---------- Public entry point ----------


async def ingest_filing(ticker: str, accession_number: str) -> IngestResult:
    """Run the full ingestion pipeline for one filing.

    Idempotent on accession_number — re-runs will reuse the existing row
    and overwrite chunks/metrics.
    """
    company = await get_company(ticker)
    await _upsert_company(company)

    fetched = await fetch_filing(accession_number)
    filing_id = await _create_filing_row(company, fetched.meta)

    try:
        doc, xbrl_metrics, html_metrics, chunks = await asyncio.to_thread(
            _run_extraction_sync, fetched,
        )

        # Embed chunks (also CPU-bound — wrap in thread)
        embeddings = await asyncio.to_thread(
            embed_texts, [c.text for c in chunks],
        )

        # Wipe any prior child rows for this filing (idempotent re-run)
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM text_chunks WHERE filing_id = $1", filing_id)
            await conn.execute("DELETE FROM extracted_tables WHERE filing_id = $1", filing_id)
            await conn.execute("DELETE FROM metrics WHERE filing_id = $1", filing_id)

        await _insert_chunks(filing_id, chunks, embeddings)
        await _insert_tables(filing_id, doc.tables)
        metric_count = await _insert_metrics(filing_id, xbrl_metrics, html_metrics)

        await _mark_filing_ready(
            filing_id=filing_id,
            chunk_count=len(chunks),
            metric_count=metric_count,
            page_count=doc.page_count,
        )

        logger.info(
            f"Ingested {ticker} {fetched.meta.form} {accession_number}: "
            f"{len(chunks)} chunks, {metric_count} metrics ({len(xbrl_metrics)} xbrl + "
            f"{len(html_metrics)} html), {len(doc.tables)} tables, {doc.page_count} pages"
        )

        await evict_if_needed()

        return IngestResult(
            filing_id=filing_id,
            accession_number=accession_number,
            chunk_count=len(chunks),
            metric_count=metric_count,
            table_count=len(doc.tables),
            page_count=doc.page_count,
            status="ready",
        )

    except Exception as e:
        logger.exception(f"Ingestion failed for {accession_number}")
        await _mark_filing_failed(filing_id, str(e))
        return IngestResult(
            filing_id=filing_id,
            accession_number=accession_number,
            chunk_count=0,
            metric_count=0,
            table_count=0,
            page_count=0,
            status="failed",
            error=str(e),
        )
