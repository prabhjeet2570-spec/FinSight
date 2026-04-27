from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import pytest
from app.contracts import Filing
from app.ingest import parse_filing
from app.store import Store


@pytest.fixture
def filing():
    return Filing(
        id="demo",
        ticker="DEMO",
        company="Fixture",
        cik="0000000001",
        form="10-K",
        fiscal_year=2024,
        period_end="2024-12-31",
        accession="0000000001-24-000001",
        source_url="https://www.sec.gov/Archives/edgar/data/1/test.html",
    )


@pytest.fixture
def html():
    return """<html><ix:header><xbrli:context id="annual"><xbrli:period><xbrli:startDate>2024-01-01</xbrli:startDate><xbrli:endDate>2024-12-31</xbrli:endDate></xbrli:period></xbrli:context><xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit></ix:header><div>Item 1A. Risk Factors</div><p id="risk">Our supply chain depends on third party manufacturers and interruptions may affect shipments and revenue.</p><ix:nonFraction id="revenue" name="us-gaap:Revenues" contextRef="annual" unitRef="usd" scale="6" decimals="-6" format="ixt:num-dot-decimal">1,250</ix:nonFraction></html>"""


def test_scale_period_provenance(html, filing):
    chunks, facts = parse_filing(html, filing)
    assert facts[0].value == Decimal(1250000000)
    assert str(facts[0].start) == "2024-01-01"
    assert facts[0].unit == "USD" and facts[0].source_anchor == "revenue"
    assert chunks[0].section == "Risk factors" and chunks[0].source_anchor == "risk"


def test_idempotent_restart_and_conflict(tmp_path, html, filing):
    s = Store(tmp_path / "state.db")
    assert not s.ingest(filing, html.encode())["cached"]
    assert Store(s.path).ingest(filing, html.encode())["cached"]
    with pytest.raises(ValueError, match="different content"):
        s.ingest(filing, (html + "x").encode())
    assert len(s.list_filings()) == 1


def test_concurrent_import(tmp_path, html, filing):
    s = Store(tmp_path / "state.db")
    with ThreadPoolExecutor(max_workers=4) as pool:
        result = list(pool.map(lambda _: s.ingest(filing, html.encode()), range(8)))
    assert sum(not r["cached"] for r in result) == 1
    assert len(s.facts(["demo"])) == 1


def test_unsupported_transformation_is_not_guessed(html, filing):
    _, facts = parse_filing(html.replace("num-dot-decimal", "num-comma-decimal"), filing)
    assert not facts
