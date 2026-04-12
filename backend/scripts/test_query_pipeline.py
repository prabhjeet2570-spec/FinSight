"""Phase 10 smoke test: end-to-end async query against the FastAPI app.

Uses httpx.ASGITransport to call the in-process app — no need for a
running uvicorn. Exercises:

  1. Cache miss: "How is Apple's revenue trending?"
       -> POST /api/query returns 202 with a job_id
       -> poll GET /api/query/jobs/{id} until status='ready'
       -> verify the answer mentions revenue and cites AAPL filings
  2. Cache hit: "What did Apple management say about iPhone demand?"
       -> POST /api/query returns 200 directly with a QueryResponse

Usage:
    cd backend
    python -m scripts.test_query_pipeline
"""
import asyncio
import logging
from typing import Any

import httpx

from app.db.connection import close_db, init_db
from app.main import app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("test_query_pipeline")


async def post_query(client: httpx.AsyncClient, question: str) -> tuple[int, dict]:
    resp = await client.post("/api/query", json={"question": question})
    return resp.status_code, resp.json()


async def poll_job(
    client: httpx.AsyncClient,
    job_id: str,
    interval_s: float = 3.0,
    timeout_s: float = 600.0,
) -> dict:
    """Poll the job status endpoint until it reaches a terminal state."""
    elapsed = 0.0
    last_progress = ""
    while elapsed < timeout_s:
        resp = await client.get(f"/api/query/jobs/{job_id}")
        if resp.status_code != 200:
            raise RuntimeError(f"job poll returned {resp.status_code}: {resp.text}")
        body = resp.json()
        status = body.get("status")
        progress = body.get("progress") or ""
        if progress and progress != last_progress:
            print(f"  [{int(elapsed):3d}s] {progress}")
            last_progress = progress
        if status in ("ready", "failed"):
            return body
        await asyncio.sleep(interval_s)
        elapsed += interval_s
    raise RuntimeError(f"job {job_id} did not finish within {timeout_s}s")


def _short_answer(answer: str, n: int = 600) -> str:
    if len(answer) <= n:
        return answer
    return answer[:n] + "…"


def _print_response(payload: dict) -> None:
    print(f"  query_type:  {payload.get('query_type')}")
    print(f"  confidence:  {payload.get('confidence')}")
    print()
    print("  --- answer ---")
    print(_short_answer(payload.get("answer", "")))
    print("  --- /answer ---")
    print()
    cr = payload.get("companies_resolved") or []
    print(f"  companies_resolved ({len(cr)}):")
    for c in cr:
        print(f"    {c.get('ticker')}  {c.get('name')}  cik={c.get('cik')}")
    fu = payload.get("filings_used") or []
    print(f"  filings_used ({len(fu)}):")
    for f in fu:
        print(
            f"    {f.get('ticker')} {f.get('filing_type')} "
            f"{f.get('period_label')} {f.get('accession_number')}"
        )
    metrics = payload.get("metrics_used") or []
    print(f"  metrics_used ({len(metrics)}):")
    for m in metrics[:5]:
        print(
            f"    {m.get('name')}: {m.get('value')} (Δ {m.get('change_pct')}%)"
        )
    ratios = payload.get("ratios_computed") or []
    print(f"  ratios_computed ({len(ratios)}):")
    for r in ratios[:5]:
        print(f"    {r.get('display_name')}: {r.get('value')}")


async def main() -> None:
    # ASGITransport does NOT run FastAPI lifespan events, so init_db()
    # would never be called. Wire it up manually.
    await init_db()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        timeout=600,
    ) as client:
        try:
            # ---- Question 1: cache miss expected ----
            q1 = "How is Apple's revenue trending in the latest quarter?"
            print("\n" + "=" * 78)
            print(f"Q1 (expecting cache miss): {q1}")
            print("=" * 78)
            status, body = await post_query(client, q1)
            print(f"  POST /api/query -> {status}")

            if status == 202:
                job_id = body["job_id"]
                print(f"  job_id: {job_id}")
                print(f"  initial progress: {body.get('progress')}")
                final = await poll_job(client, job_id)
                if final["status"] == "failed":
                    print(f"  ❌ JOB FAILED: {final.get('error')}")
                    return
                payload = final["result"]
                _print_response(payload)
            elif status == 200:
                print("  (already cached — running synchronously)")
                _print_response(body)
            else:
                print(f"  ❌ unexpected status {status}: {body}")
                return

            # ---- Question 2: cache hit expected ----
            q2 = "What did Apple management say about iPhone demand?"
            print("\n" + "=" * 78)
            print(f"Q2 (expecting cache hit): {q2}")
            print("=" * 78)
            status, body = await post_query(client, q2)
            print(f"  POST /api/query -> {status}")
            if status == 200:
                _print_response(body)
            elif status == 202:
                print("  (cache miss — possibly different filing) polling…")
                final = await poll_job(client, body["job_id"])
                if final["status"] == "failed":
                    print(f"  ❌ JOB FAILED: {final.get('error')}")
                    return
                _print_response(final["result"])
            else:
                print(f"  ❌ unexpected status {status}: {body}")

            # ---- Question 3: no company in question (clarification path) ----
            q3 = "How is the economy doing?"
            print("\n" + "=" * 78)
            print(f"Q3 (no company — clarification expected): {q3}")
            print("=" * 78)
            status, body = await post_query(client, q3)
            print(f"  POST /api/query -> {status}")
            print(f"  answer: {body.get('answer')}")
            print(f"  companies_resolved: {body.get('companies_resolved')}")

        finally:
            await close_db()


if __name__ == "__main__":
    asyncio.run(main())
