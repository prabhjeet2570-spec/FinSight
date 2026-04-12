"""Seed the `companies` table from EDGAR's company_tickers.json (~13MB).

Run once after a fresh DB, or periodically to refresh new listings.

Usage:
    cd backend
    python -m scripts.seed_companies
"""
import asyncio
import logging

import httpx

from app.config import get_settings
from app.db.connection import init_db, close_db, get_pool

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

EDGAR_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


async def fetch_company_tickers() -> list[dict]:
    """Pull EDGAR's master ticker -> CIK -> name map.

    JSON format: {"0": {"cik_str": int, "ticker": str, "title": str}, ...}
    """
    settings = get_settings()
    headers = {"User-Agent": settings.edgar_user_agent}
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(EDGAR_TICKERS_URL, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    return list(data.values())


async def upsert_companies(companies: list[dict]) -> int:
    pool = await get_pool()
    rows = [
        (str(c["cik_str"]).zfill(10), c["ticker"].upper(), c["title"])
        for c in companies
    ]
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(
                """
                INSERT INTO companies (cik, ticker, name)
                VALUES ($1, $2, $3)
                ON CONFLICT (cik) DO UPDATE
                  SET ticker = EXCLUDED.ticker,
                      name = EXCLUDED.name,
                      last_synced = now()
                """,
                rows,
            )
    return len(rows)


async def main() -> None:
    await init_db()
    try:
        logger.info("Fetching company_tickers.json from SEC EDGAR...")
        companies = await fetch_company_tickers()
        logger.info(f"Pulled {len(companies)} companies. Upserting...")
        n = await upsert_companies(companies)
        logger.info(f"Upserted {n} companies into the `companies` table.")
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
