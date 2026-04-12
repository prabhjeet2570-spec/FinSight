"""Phase 8 smoke test: fetch Apple's latest 10-Q via edgar_client.

Prints company info, the 3 most recent 10-Q filings, and the HTML byte
size + XBRL fact count for the latest one.

Usage:
    cd backend
    python -m scripts.test_edgar
"""
import asyncio
import logging

from app.services.edgar_client import get_company, list_filings, fetch_filing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


async def main() -> None:
    print("== get_company('AAPL') ==")
    company = await get_company("AAPL")
    print(f"  CIK:    {company.cik}")
    print(f"  Ticker: {company.ticker}")
    print(f"  Name:   {company.name}")
    print(f"  SIC:    {company.sic}")

    print()
    print("== list_filings('AAPL', '10-Q', limit=3) ==")
    filings = await list_filings("AAPL", form_type="10-Q", limit=3)
    for f in filings:
        print(
            f"  {f.accession_number}  {f.form:6}  "
            f"filed={f.filing_date}  period={f.period_of_report}"
        )
    if not filings:
        print("  (no filings returned)")
        return

    latest = filings[0]
    print()
    print(f"== fetch_filing('{latest.accession_number}') ==")
    fetched = await fetch_filing(latest.accession_number)
    print(f"  HTML size:  {len(fetched.html):,} bytes")
    if fetched.xbrl is None:
        print("  XBRL:       <none>")
    else:
        print(f"  XBRL:       {type(fetched.xbrl).__name__}")


if __name__ == "__main__":
    asyncio.run(main())
