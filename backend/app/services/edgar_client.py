"""SEC EDGAR client — wraps edgartools to fetch filings on demand.

Three operations the rest of the system needs:
  - get_company(ticker)         ticker -> CIK + name + SIC
  - list_filings(ticker, form)  recent filings of a given form, newest first
  - fetch_filing(accession)     pull HTML + XBRL facts for one filing

edgartools calls are synchronous; we wrap them in asyncio.to_thread so the
async query pipeline never blocks. SEC's 10 req/sec rate limit is honored
by edgartools internally — no extra throttling in the wrapper.

SEC compliance: every request needs a User-Agent with contact info. We
call edgar.set_identity() once (lazily) using EDGAR_USER_AGENT from config.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

_identity_set = False


def _ensure_identity() -> None:
    """Set the SEC User-Agent identity once per process."""
    global _identity_set
    if _identity_set:
        return
    from edgar import set_identity
    settings = get_settings()
    if not settings.edgar_user_agent:
        raise EdgarError("EDGAR_USER_AGENT not configured")
    set_identity(settings.edgar_user_agent)
    _identity_set = True


class EdgarError(Exception):
    """Raised for any error talking to SEC EDGAR."""


@dataclass
class CompanyInfo:
    cik: str           # 10-digit zero-padded
    ticker: str
    name: str
    sic: str | None = None


@dataclass
class FilingMeta:
    accession_number: str          # e.g. '0000320193-25-000123'
    form: str                      # '10-K', '10-Q', '8-K'
    filing_date: str               # ISO date 'YYYY-MM-DD'
    period_of_report: str | None
    primary_doc_url: str


@dataclass
class FetchedFiling:
    meta: FilingMeta
    html: str
    xbrl: Any | None               # raw edgartools XBRL object, or None if no XBRL


def _normalize_cik(cik) -> str:
    return str(cik).zfill(10)


def _to_filing_meta(f) -> FilingMeta:
    """Convert an edgartools Filing object to our FilingMeta dataclass.

    edgartools has two filing classes with subtly different fields:
      - EntityFiling (from Company.get_filings()) has `report_date`
      - Filing (from find(accession)) has `period_of_report` instead
    Try both so we capture the period regardless of which call site
    produced the object.
    """
    period = (
        getattr(f, "period_of_report", None)
        or getattr(f, "report_date", None)
    )
    return FilingMeta(
        accession_number=str(f.accession_no),
        form=str(f.form),
        filing_date=str(f.filing_date),
        period_of_report=str(period) if period else None,
        primary_doc_url=str(
            getattr(f, "primary_doc_url", None)
            or getattr(f, "document_url", None)
            or getattr(f, "url", "")
        ),
    )


# ---------- get_company ----------

def _get_company_sync(ticker: str) -> CompanyInfo:
    _ensure_identity()
    from edgar import Company
    try:
        company = Company(ticker)
    except Exception as e:
        raise EdgarError(f"Could not look up company for ticker '{ticker}': {e}") from e

    if company is None:
        raise EdgarError(f"No company found for ticker '{ticker}'")

    sic_val = getattr(company, "sic", None)
    return CompanyInfo(
        cik=_normalize_cik(company.cik),
        ticker=ticker.upper(),
        name=str(company.name),
        sic=str(sic_val) if sic_val else None,
    )


async def get_company(ticker: str) -> CompanyInfo:
    """Look up a company by ticker. Returns CIK + name + SIC."""
    return await asyncio.to_thread(_get_company_sync, ticker)


# ---------- list_filings ----------

def _list_filings_sync(ticker: str, form_type: str, limit: int) -> list[FilingMeta]:
    _ensure_identity()
    from edgar import Company
    try:
        company = Company(ticker)
    except Exception as e:
        raise EdgarError(f"Could not look up company for ticker '{ticker}': {e}") from e

    try:
        filings = company.get_filings(form=form_type)
    except Exception as e:
        raise EdgarError(f"Could not list {form_type} filings for {ticker}: {e}") from e

    if filings is None:
        return []

    # edgartools' Filings collection supports head(n) for the most recent N
    if hasattr(filings, "head"):
        latest = filings.head(limit)
    else:
        latest = list(filings)[:limit]

    out: list[FilingMeta] = []
    for f in latest:
        try:
            out.append(_to_filing_meta(f))
        except Exception as e:
            logger.warning(f"Skipping filing with malformed metadata: {e}")
    return out


async def list_filings(
    ticker: str,
    form_type: str = "10-Q",
    limit: int = 5,
) -> list[FilingMeta]:
    """List recent filings of a given form type for a ticker, newest first."""
    return await asyncio.to_thread(_list_filings_sync, ticker, form_type, limit)


# ---------- fetch_filing ----------

def _fetch_filing_sync(accession_number: str) -> FetchedFiling:
    _ensure_identity()
    from edgar import find
    try:
        filing = find(accession_number)
    except Exception as e:
        raise EdgarError(f"Could not fetch filing {accession_number}: {e}") from e

    if filing is None:
        raise EdgarError(f"No filing found for accession number {accession_number}")

    try:
        html = filing.html()
    except Exception as e:
        raise EdgarError(f"Could not download HTML for {accession_number}: {e}") from e

    if html is None:
        raise EdgarError(f"Filing {accession_number} returned empty HTML")

    xbrl_obj: Any | None = None
    try:
        xbrl_obj = filing.xbrl()
    except Exception as e:
        logger.info(f"No XBRL for {accession_number}: {e}")

    return FetchedFiling(
        meta=_to_filing_meta(filing),
        html=str(html),
        xbrl=xbrl_obj,
    )


async def fetch_filing(accession_number: str) -> FetchedFiling:
    """Download the HTML + XBRL for one filing by accession number."""
    return await asyncio.to_thread(_fetch_filing_sync, accession_number)
