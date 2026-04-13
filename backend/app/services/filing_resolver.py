"""Filing resolver: companies + classifier output -> concrete filings to retrieve over.

Given the resolved companies and the classifier's `filings_needed` list,
this module:

  1. Always checks EDGAR for the latest filings (lightweight metadata call).
  2. Checks if each accession number is already cached in the local DB.
  3. Returns a `ResolutionPlan` that tells the router whether the query
     can run synchronously (all cached) or needs background ingestion.

This ensures we always use the most recent filings, not stale cached data.
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


# ---------- EDGAR lookup ----------


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

    # Only fallback between 10-K <-> 10-Q. Other form types (8-K, DEF 14A,
    # 20-F, S-1, Form 4) are distinct — no sensible fallback exists.
    if form_type in ("10-Q", "10-K"):
        fallback = "10-K" if form_type == "10-Q" else "10-Q"
        try:
            filings = await list_filings(company.ticker, form_type=fallback, limit=count)
        except EdgarError as e:
            logger.warning(
                f"EDGAR list_filings fallback failed for {company.ticker} {fallback}: {e}"
            )
            return []
        return filings

    logger.warning(f"No {form_type} filings found for {company.ticker}, no fallback available")
    return []


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

            # Always check EDGAR for the latest filings to avoid stale cache
            logger.info(
                f"  {company.ticker} {form_type} x{count}: checking EDGAR"
            )
            metas = await _find_filings_from_edgar(company, form_type, count)

            for meta in metas:
                if meta.accession_number in seen_accessions:
                    continue
                seen_accessions.add(meta.accession_number)

                # Check if this specific accession is already cached
                cached_id: UUID | None = None
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
