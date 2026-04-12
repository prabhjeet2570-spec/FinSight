"""LRU eviction for the filings table.

Neon free tier = 512MB. When the database exceeds 80% of that, we evict
the oldest filings (by fetched_at) until we're back under. Child rows
(text_chunks, extracted_tables, metrics) cascade-delete automatically.
"""
import logging

from app.db.connection import get_pool

logger = logging.getLogger(__name__)

NEON_FREE_TIER_BYTES = 512 * 1024 * 1024
EVICTION_THRESHOLD = 0.80
EVICTION_BATCH = 5


async def get_db_size_bytes() -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT pg_database_size(current_database())")


async def evict_if_needed() -> int:
    threshold_bytes = int(NEON_FREE_TIER_BYTES * EVICTION_THRESHOLD)
    db_size = await get_db_size_bytes()

    if db_size < threshold_bytes:
        return 0

    logger.warning(
        f"DB size {db_size / 1024 / 1024:.1f}MB exceeds "
        f"{threshold_bytes / 1024 / 1024:.0f}MB threshold — evicting oldest filings"
    )

    pool = await get_pool()
    evicted = 0

    while db_size >= threshold_bytes:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                DELETE FROM filings
                WHERE id IN (
                    SELECT id FROM filings
                    ORDER BY fetched_at ASC
                    LIMIT $1
                )
                RETURNING ticker, accession_number
                """,
                EVICTION_BATCH,
            )

        if not rows:
            break

        for r in rows:
            logger.info(f"Evicted {r['ticker']} {r['accession_number']}")
        evicted += len(rows)

        db_size = await get_db_size_bytes()

    if evicted:
        logger.info(
            f"Evicted {evicted} filings — DB now {db_size / 1024 / 1024:.1f}MB"
        )

    return evicted
