import asyncpg
import logging
from pathlib import Path

from app.config import get_settings

logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_db() first.")
    return _pool


async def init_db() -> None:
    global _pool
    settings = get_settings()

    if not settings.database_url:
        logger.warning("DATABASE_URL not set — skipping database initialization")
        return

    logger.info("Connecting to database...")
    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=10,
    )

    # Run schema migration
    schema_path = Path(__file__).parent / "schema.sql"
    schema_sql = schema_path.read_text()

    async with _pool.acquire() as conn:
        await conn.execute(schema_sql)

    logger.info("Database initialized successfully")


async def close_db() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database connection pool closed")
