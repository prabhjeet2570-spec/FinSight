"""Financial conclusions are deterministic Decimal calculations, never LLM arithmetic."""

import re
from datetime import date
from decimal import Decimal

from app.contracts import Fact

METRICS = {
    "revenue": (
        "Revenue",
        [
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            "us-gaap:Revenues",
            "us-gaap:SalesRevenueNet",
        ],
    ),
    "operating_income": ("Operating income", ["us-gaap:OperatingIncomeLoss"]),
    "net_income": ("Net income", ["us-gaap:NetIncomeLoss"]),
    "gross_profit": ("Gross profit", ["us-gaap:GrossProfit"]),
    "cost_of_revenue": (
        "Cost of revenue",
        ["us-gaap:CostOfRevenue", "us-gaap:CostOfGoodsAndServicesSold"],
    ),
    "assets": ("Total assets", ["us-gaap:Assets"]),
    "liabilities": ("Total liabilities", ["us-gaap:Liabilities"]),
    "cash": (
        "Cash and cash equivalents",
        ["us-gaap:CashAndCashEquivalentsAtCarryingValue"],
    ),
    "operating_cash_flow": (
        "Operating cash flow",
        ["us-gaap:NetCashProvidedByUsedInOperatingActivities"],
    ),
    "research": ("Research and development", ["us-gaap:ResearchAndDevelopmentExpense"]),
}
ALIASES = {
    "revenue": r"\brevenue\b|\bsales\b|\btop.line\b",
    "operating_income": r"\boperating (?:income|profit)\b",
    "net_income": r"\bnet (?:income|profit|earnings)\b",
    "gross_profit": r"\bgross profit\b",
    "cost_of_revenue": r"\bcost of (?:revenue|sales)\b|\bcogs\b",
    "assets": r"\bassets\b",
    "liabilities": r"\bliabilities\b",
    "cash": r"\bcash(?: and cash equivalents)?\b",
    "operating_cash_flow": r"\b(?:operating cash flow|cash from operations|cash flow)\b",
    "research": r"\bresearch\b|\br&d\b",
}
RATIOS = {
    "operating_margin": ("Operating margin", "operating_income", "revenue"),
    "net_margin": ("Net margin", "net_income", "revenue"),
    "gross_margin": ("Gross margin", "gross_profit", "revenue"),
    "cash_flow_margin": (
        "Operating cash flow margin",
        "operating_cash_flow",
        "revenue",
    ),
    "revenue_growth": ("Revenue growth", "revenue", "revenue"),
}


class Unsupported(ValueError):
    pass


def selected_fact(facts, metric, year, period_end=None):
    concepts = METRICS[metric][1]
    candidates = [
        f
        for f in facts
        if f.concept in concepts and not f.dimensions and f.end.year == year and f.unit == "USD"
    ]
    instant = metric in ("assets", "liabilities", "cash")
    candidates = [
        f
        for f in candidates
        if (
            f.start is None
            if instant
            else f.start is not None and 330 <= (f.end - f.start).days <= 380
        )
    ]
    if period_end:
        candidates = [f for f in candidates if f.end == period_end]
    if not candidates:
        raise Unsupported(
            f"{METRICS[metric][0]} has no supported consolidated USD {'instant' if instant else 'annual'} fact for the requested fiscal year."
        )
    keys = {(f.value, f.start, f.end, f.unit) for f in candidates}
    if len(keys) != 1:
        raise Unsupported(
            f"Conflicting or ambiguous {METRICS[metric][0].lower()} facts; the application will not silently pick a value."
        )
    return sorted(candidates, key=lambda f: (concepts.index(f.concept), f.id))[0]


def comparable(a: Fact, b: Fact, growth=False):
    if a.unit != b.unit or a.dimensions != b.dimensions or a.filing_id != b.filing_id:
        raise Unsupported(
            "Operands must come from the same filing with the same units and dimensions."
        )
    if not a.start or not b.start:
        raise Unsupported("The formula requires duration facts.")
    if abs((a.end - a.start).days - (b.end - b.start).days) > 7:
        raise Unsupported("Reporting durations are not comparable.")
    if not growth and (a.start, a.end) != (b.start, b.end):
        raise Unsupported("Margin operands must cover the same reporting period.")
    if growth and not 350 <= (a.end - b.end).days <= 380:
        raise Unsupported("Growth operands must be adjacent annual periods.")
    if b.value == 0:
        raise Unsupported("A zero denominator cannot produce a meaningful ratio.")


def fact_source(fact, filing):
    return {
        "id": fact.id,
        "type": "fact",
        "filing_id": filing["id"],
        "ticker": filing["ticker"],
        "company": filing["company"],
        "form": filing["form"],
        "accession": filing["accession"],
        "section": "Inline XBRL",
        "concept": fact.concept,
        "value": str(fact.value),
        "unit": fact.unit,
        "period_start": str(fact.start) if fact.start else None,
        "period_end": str(fact.end),
        "decimals": fact.decimals,
        "context_id": fact.context_id,
        "source_url": filing["source_url"]
        + ("#" + fact.source_anchor if fact.source_anchor else ""),
        "text": f"{fact.concept}: {fact.value} {fact.unit}; {fact.start or 'instant'} to {fact.end}",
        "dimensions": fact.dimensions,
    }


def money(value):
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= Decimal(1000000000):
        return f"{sign}${value / Decimal(1000000000):.3f}B"
    if value >= Decimal(1000000):
        return f"{sign}${value / Decimal(1000000):.3f}M"
    return f"{sign}${value:,.2f}"


def numeric_intent(question):
    q = question.lower()
    ratios = []
    for key, label in [
        ("operating_margin", "operating margin"),
        ("net_margin", "net margin"),
        ("gross_margin", "gross margin"),
        ("cash_flow_margin", "cash flow margin"),
    ]:
        if label in q:
            ratios.append(key)
    if re.search(r"\b(?:growth|grew|year.over.year|yoy|increase|change)\b", q) and re.search(
        ALIASES["revenue"], q
    ):
        ratios.append("revenue_growth")
    metrics = [m for m, pattern in ALIASES.items() if re.search(pattern, q)]
    if "operating_cash_flow" in metrics and "cash" in metrics:
        metrics.remove("cash")
    # Risk/strategy questions mentioning revenue still need narrative evidence.
    narrative = bool(
        re.search(
            r"\b(?:risk|risks|strategy|strategies|why|how|depend|exposure|uncertainty|challenges|competition)\b",
            q,
        )
    )
    return (metrics, ratios) if ratios or (metrics and not narrative) else ([], [])


def financial_answer(question, filings, facts, year):
    metrics, ratios = numeric_intent(question)
    if not metrics and not ratios:
        return None
    sources, claims, calculations, issues = [], [], [], []
    for filing in filings:
        company_facts = [f for f in facts if f.filing_id == filing["id"]]
        target_end = (
            date.fromisoformat(filing["period_end"]) if year == filing["fiscal_year"] else None
        )
        for metric in metrics:
            try:
                f = selected_fact(company_facts, metric, year, target_end)
                sources.append(fact_source(f, filing))
                claims.append(
                    {
                        "text": f"{filing['ticker']} FY{year} {METRICS[metric][0].lower()}: {money(f.value)}.",
                        "source_ids": [f.id],
                        "kind": "fact",
                    }
                )
            except Unsupported as e:
                issues.append(f"{filing['ticker']}: {e}")
        for key in ratios:
            label, numerator, denominator = RATIOS[key]
            try:
                a = selected_fact(company_facts, numerator, year, target_end)
                b = selected_fact(
                    company_facts,
                    denominator,
                    year - 1 if key == "revenue_growth" else year,
                    None if key == "revenue_growth" else target_end,
                )
                comparable(a, b, growth=key == "revenue_growth")
                value = (
                    (a.value - b.value) / abs(b.value) * 100
                    if key == "revenue_growth"
                    else a.value / b.value * 100
                )
                formula = (
                    "(current revenue - prior revenue) / abs(prior revenue) × 100"
                    if key == "revenue_growth"
                    else f"{METRICS[numerator][0]} / {METRICS[denominator][0]} × 100"
                )
                sources.extend([fact_source(a, filing), fact_source(b, filing)])
                calculations.append(
                    {
                        "label": label,
                        "ticker": filing["ticker"],
                        "value": str(value.quantize(Decimal(".000001"))),
                        "display_value": f"{value:.2f}%",
                        "formula": formula,
                        "operands": [a.id, b.id],
                        "fiscal_year": year,
                        "period_start": str(a.start),
                        "period_end": str(a.end),
                    }
                )
                claims.append(
                    {
                        "text": f"{filing['ticker']} FY{year} {label.lower()}: {value:.2f}%.",
                        "source_ids": [a.id, b.id],
                        "kind": "calculation",
                    }
                )
            except Unsupported as e:
                issues.append(f"{filing['ticker']}: {label}: {e}")
    if len(filings) > 1:
        periods = {f["period_end"] for f in filings}
        if len(periods) > 1:
            issues.append(
                "These issuers have different fiscal year ends. Values are issuer fiscal-year results, not aligned calendar-year comparisons."
            )
    return {
        "claims": claims,
        "sources": list({s["id"]: s for s in sources}.values()),
        "calculations": calculations,
        "issues": issues,
        "status": "supported"
        if claims
        and not any("no supported" in i or "Conflicting" in i or "cannot" in i for i in issues)
        else ("partial" if claims else "insufficient_evidence"),
    }
