"""Filing resolver: companies + classifier output -> concrete filings to retrieve over.

Given the resolved companies and the classifier's `filings_needed` list,
this module:

  1. For each (company, form_type, count), checks the local DB first for
     cached filings with status='ready'. If we already have enough, no
     EDGAR call is made at all.

  2. Only calls EDGAR when the DB doesn't have enough cached filings for
     the request.

  3. Returns a `ResolutionPlan` that tells the router whether the query
     can run synchronously (all hits) or needs background ingestion
     (any miss).

The classifier (LLM) decides which filing types and how many — no
handcrafted rules here.
"""
import logging
from dataclasses import dataclass, field
from uuid import UUID

from app.db.connection import get_pool
from app.services.edgar_client import (
    CompanyInfo,
    EdgarError,
    FilingMeta,
    list_filings,
)

logger = logging.getLogger(__name__)


@dataclass
class FilingTarget:
    """One filing the query wants to retrieve over."""
    company: CompanyInfo
    meta: FilingMeta
    cached_filing_id: UUID | None  # None = needs ingestion

    @property
    def needs_ingestion(self) -> bool:
        return self.cached_filing_id is None


@dataclass
class ResolutionPlan:
    targets: list[FilingTarget] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)  # tickers we couldn't find a filing for

    @property
    def needs_ingestion(self) -> bool:
        return any(t.needs_ingestion for t in self.targets)

    @property
    def cached_filing_ids(self) -> list[UUID]:
        return [t.cached_filing_id for t in self.targets if t.cached_filing_id]


# ---------- DB cache lookup ----------


async def _find_cached_filings(
    ticker: str,
    form_type: str,
    count: int,
) -> list[tuple[UUID, FilingMeta]]:
    """Check local DB for cached filings matching ticker + form type.

    Returns up to `count` filings, newest first, only those with
    status='ready'.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, accession_number, filing_type, filing_date,
                   period_of_report, primary_doc_url
            FROM filings
            WHERE ticker = $1
              AND filing_type = $2
              AND status = 'ready'
            ORDER BY filing_date DESC
            LIMIT $3
            """,
            ticker, form_type, count,
        )

    results: list[tuple[UUID, FilingMeta]] = []
    for r in rows:
        meta = FilingMeta(
            accession_number=r["accession_number"],
            form=r["filing_type"],
            filing_date=str(r["filing_date"]) if r["filing_date"] else "",
            period_of_report=str(r["period_of_report"]) if r["period_of_report"] else None,
            primary_doc_url=r["primary_doc_url"],
        )
        results.append((r["id"], meta))
    return results


# ---------- EDGAR fallback lookup ----------


async def _find_filings_from_edgar(
    company: CompanyInfo,
    form_type: str,
    count: int,
) -> list[FilingMeta]:
    """Fetch the N most recent filings of a given form type from EDGAR.

    Falls back to 10-K if 10-Q returns nothing (and vice versa).
    Returns an empty list if neither yields results.
    """
    try:
        filings = await list_filings(company.ticker, form_type=form_type, limit=count)
    except EdgarError as e:
        logger.warning(
            f"EDGAR list_filings failed for {company.ticker} {form_type}: {e}"
        )
        filings = []

    if filings:
        return filings

    fallback = "10-K" if form_type == "10-Q" else "10-Q"
    try:
        filings = await list_filings(company.ticker, form_type=fallback, limit=count)
    except EdgarError as e:
        logger.warning(
            f"EDGAR list_filings fallback failed for {company.ticker} {fallback}: {e}"
        )
        return []

    return filings


# ---------- Public API ----------


async def resolve_filings(
    companies: list[CompanyInfo],
    filings_needed: list[dict],
) -> ResolutionPlan:
    """Build a retrieval plan for the given companies and filing requirements.

    Checks the local DB first. Only calls EDGAR when we don't have enough
    cached filings.
    """
    if not filings_needed:
        filings_needed = [{"form": "10-Q", "count": 1}]

    logger.info(
        f"Filing resolver: {len(companies)} companies, "
        f"filings_needed={filings_needed}"
    )

    plan = ResolutionPlan()
    seen_accessions: set[str] = set()

    for company in companies:
        company_has_filings = False

        for req in filings_needed:
            form_type = req.get("form", "10-Q")
            count = req.get("count", 1)

            # Step 1: Check DB cache first
            cached = await _find_cached_filings(company.ticker, form_type, count)

            if len(cached) >= count:
                logger.info(
                    f"  {company.ticker} {form_type} x{count}: "
                    f"fully served from DB cache"
                )
                for filing_id, meta in cached:
                    if meta.accession_number in seen_accessions:
                        continue
                    seen_accessions.add(meta.accession_number)
                    plan.targets.append(FilingTarget(
                        company=company,
                        meta=meta,
                        cached_filing_id=filing_id,
                    ))
                    company_has_filings = True
                continue

            # Step 2: Not enough in cache — call EDGAR
            logger.info(
                f"  {company.ticker} {form_type} x{count}: "
                f"have {len(cached)} cached, calling EDGAR"
            )
            metas = await _find_filings_from_edgar(company, form_type, count)

            for meta in metas:
                if meta.accession_number in seen_accessions:
                    continue
                seen_accessions.add(meta.accession_number)

                # Check if this specific accession is cached
                cached_id: UUID | None = None
                for cid, cmeta in cached:
                    if cmeta.accession_number == meta.accession_number:
                        cached_id = cid
                        break

                if cached_id is None:
                    pool = await get_pool()
                    async with pool.acquire() as conn:
                        row = await conn.fetchrow(
                            "SELECT id FROM filings WHERE accession_number = $1 AND status = 'ready'",
                            meta.accession_number,
                        )
                    if row:
                        cached_id = row["id"]

                plan.targets.append(FilingTarget(
                    company=company,
                    meta=meta,
                    cached_filing_id=cached_id,
                ))
                company_has_filings = True
                logger.info(
                    f"    {meta.form} {meta.accession_number} "
                    f"({'CACHED' if cached_id else 'NEEDS INGESTION'})"
                )

        if not company_has_filings:
            logger.warning(f"No filings found for {company.ticker}")
            plan.unresolved.append(company.ticker)

    return plan
