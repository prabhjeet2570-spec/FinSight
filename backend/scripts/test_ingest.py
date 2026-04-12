"""Phase 9 smoke test: ingest Apple's latest 10-Q end-to-end.

  1. init_db (applies schema, idempotent)
  2. list latest AAPL 10-Q
  3. ingest_filing — full pipeline (fetch + extract + embed + insert)
  4. read back row counts to confirm

Usage:
    cd backend
    python -m scripts.test_ingest
"""
import asyncio
import logging

from app.db.connection import close_db, get_pool, init_db
from app.services.edgar_client import list_filings
from app.services.filing_ingestion import get_cached_filing_id, ingest_filing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def main() -> None:
    await init_db()
    try:
        print("\n== list_filings('AAPL', '10-Q', limit=1) ==")
        filings = await list_filings("AAPL", form_type="10-Q", limit=1)
        if not filings:
            print("  no 10-Q found")
            return
        meta = filings[0]
        print(f"  {meta.accession_number}  filed={meta.filing_date}  period={meta.period_of_report}")

        cached = await get_cached_filing_id(meta.accession_number)
        if cached:
            print(f"\n  already cached as filing_id={cached} — re-running for idempotency")

        print(f"\n== ingest_filing('AAPL', '{meta.accession_number}') ==")
        result = await ingest_filing("AAPL", meta.accession_number)
        print(f"  status:       {result.status}")
        print(f"  filing_id:    {result.filing_id}")
        print(f"  pages:        {result.page_count}")
        print(f"  chunks:       {result.chunk_count}")
        print(f"  metrics:      {result.metric_count}")
        print(f"  tables:       {result.table_count}")
        if result.error:
            print(f"  error:        {result.error}")
            return

        pool = await get_pool()
        async with pool.acquire() as conn:
            n_chunks = await conn.fetchval(
                "SELECT count(*) FROM text_chunks WHERE filing_id = $1", result.filing_id
            )
            n_tables = await conn.fetchval(
                "SELECT count(*) FROM extracted_tables WHERE filing_id = $1", result.filing_id
            )
            n_metrics = await conn.fetchval(
                "SELECT count(*) FROM metrics WHERE filing_id = $1", result.filing_id
            )
            sections = await conn.fetch(
                "SELECT section, count(*) FROM text_chunks WHERE filing_id = $1 GROUP BY section ORDER BY count(*) DESC",
                result.filing_id,
            )
            sample_metrics = await conn.fetch(
                "SELECT metric_name, value, prior_value, change_pct, source FROM metrics WHERE filing_id = $1 ORDER BY metric_name LIMIT 10",
                result.filing_id,
            )

        print("\n== DB row counts ==")
        print(f"  text_chunks:      {n_chunks}")
        print(f"  extracted_tables: {n_tables}")
        print(f"  metrics:          {n_metrics}")

        print("\n== chunks per section ==")
        for row in sections:
            print(f"  {row['section'] or '<none>':30s}  {row['count']}")

        print("\n== sample metrics (first 10) ==")
        for row in sample_metrics:
            v = float(row["value"]) if row["value"] is not None else None
            pv = float(row["prior_value"]) if row["prior_value"] is not None else None
            cp = float(row["change_pct"]) if row["change_pct"] is not None else None
            print(
                f"  {row['metric_name']:30s} {v:>20,.0f}  prior={pv}  Δ={cp}  src={row['source']}"
            )

    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
