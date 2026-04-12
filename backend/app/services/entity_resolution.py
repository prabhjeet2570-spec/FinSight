"""Entity resolution: LLM-extracted company strings -> CompanyInfo.

The classifier returns a list of strings (typically tickers like "AAPL",
"MSFT") that the user mentioned in their question. This module resolves
each one to a concrete CompanyInfo (cik + ticker + name) so the rest of
the pipeline can fetch filings.

Resolution order for each string:
  1. Look up in the local `companies` table by ticker (fast, no network)
  2. Fall back to edgar_client.get_company(ticker) (one HTTP round-trip)
  3. On success, cache the result back into `companies` so the next call
     is a hit
  4. On failure, the string is reported as unresolved — the caller decides
     whether to error out or proceed with the others

Designed to never raise on a single bad ticker — bad tickers come back in
`unresolved` so the caller can show a useful error to the user.
"""
import logging
from dataclasses import dataclass

from app.db.connection import get_pool
from app.services.edgar_client import CompanyInfo, EdgarError, get_company

logger = logging.getLogger(__name__)


@dataclass
class ResolutionResult:
    resolved: list[CompanyInfo]
    unresolved: list[str]  # input strings we could not map to a company


# ---------- Local cache lookup ----------


async def _lookup_in_db(query: str) -> CompanyInfo | None:
    """Try to find a company in our local `companies` table.

    Matches in order:
      1. exact ticker (case-insensitive)
      2. exact lowercase name
      3. lowercase name LIKE '%query%' (best-effort fuzzy)
    """
    pool = await get_pool()
    q = query.strip()
    q_upper = q.upper()
    q_lower = q.lower()

    async with pool.acquire() as conn:
        # Ticker exact match
        row = await conn.fetchrow(
            "SELECT cik, ticker, name, sic FROM companies WHERE ticker = $1",
            q_upper,
        )
        if row:
            return CompanyInfo(
                cik=row["cik"],
                ticker=row["ticker"],
                name=row["name"],
                sic=row["sic"],
            )

        # Name exact match
        row = await conn.fetchrow(
            "SELECT cik, ticker, name, sic FROM companies WHERE lower(name) = $1",
            q_lower,
        )
        if row:
            return CompanyInfo(
                cik=row["cik"],
                ticker=row["ticker"],
                name=row["name"],
                sic=row["sic"],
            )

        # Name LIKE — only if input looks like a name (has a space or 6+ chars)
        if " " in q_lower or len(q_lower) >= 6:
            row = await conn.fetchrow(
                """
                SELECT cik, ticker, name, sic FROM companies
                WHERE lower(name) LIKE $1
                ORDER BY length(name) ASC
                LIMIT 1
                """,
                f"%{q_lower}%",
            )
            if row:
                return CompanyInfo(
                    cik=row["cik"],
                    ticker=row["ticker"],
                    name=row["name"],
                    sic=row["sic"],
                )

    return None


async def _cache_company(company: CompanyInfo) -> None:
    """Upsert a freshly-resolved company into the local cache."""
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


# ---------- Public API ----------


async def resolve_one(query: str) -> CompanyInfo | None:
    """Resolve a single ticker or company name. Returns None if not found."""
    if not query or not query.strip():
        return None

    cached = await _lookup_in_db(query)
    if cached:
        logger.debug(f"Entity resolution cache hit: '{query}' -> {cached.ticker}")
        return cached

    # Fall back to EDGAR. The classifier was prompted to emit tickers, so
    # try the input as a ticker first.
    try:
        company = await get_company(query.upper())
    except EdgarError as e:
        logger.warning(f"Entity resolution failed for '{query}': {e}")
        return None

    await _cache_company(company)
    logger.info(f"Entity resolution: '{query}' -> {company.ticker} ({company.name})")
    return company


async def resolve_entities(queries: list[str]) -> ResolutionResult:
    """Resolve a list of ticker/name strings into CompanyInfo objects.

    Order is preserved. Duplicates (same ticker after resolution) are
    deduplicated. Strings that fail to resolve are returned in `unresolved`.
    """
    resolved: list[CompanyInfo] = []
    seen_ciks: set[str] = set()
    unresolved: list[str] = []

    for q in queries:
        company = await resolve_one(q)
        if company is None:
            unresolved.append(q)
            continue
        if company.cik in seen_ciks:
            continue
        resolved.append(company)
        seen_ciks.add(company.cik)

    return ResolutionResult(resolved=resolved, unresolved=unresolved)
