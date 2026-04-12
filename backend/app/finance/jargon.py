"""Financial jargon resolution map.

Maps analyst shorthand and colloquial finance terms to canonical metric
names from synonyms.py. Used during query processing (Phase 5) to
translate user questions before retrieval.

Example: user asks "how's the top line?" -> resolve "top line" to "revenue"
-> expand via synonyms -> search for revenue/net sales/total sales.
"""
import re

# Jargon term -> canonical metric name (must match keys in synonyms.METRIC_SYNONYMS)
# or a special key starting with "_" for concepts that map to multiple metrics.

JARGON_MAP: dict[str, str] = {
    # Revenue aliases
    "top line": "revenue",
    "top-line": "revenue",
    "topline": "revenue",
    "sales": "revenue",
    "turnover": "revenue",

    # Net income aliases
    "bottom line": "net_income",
    "bottom-line": "net_income",
    "bottomline": "net_income",
    "profit": "net_income",
    "earnings": "net_income",

    # Operating income
    "operating profit": "operating_income",
    "ebit": "operating_income",

    # Margins (these resolve to ratio computations, not single metrics)
    "margins": "_margins",
    "margin": "_margins",
    "gross margin": "_gross_margin",
    "operating margin": "_operating_margin",
    "net margin": "_net_margin",
    "profit margin": "_net_margin",

    # Cash flow
    "burn rate": "operating_cash_flow",
    "cash burn": "operating_cash_flow",
    "cash generation": "operating_cash_flow",
    "fcf": "free_cash_flow",

    # Balance sheet
    "leverage": "_leverage",
    "debt load": "total_debt",
    "debt level": "total_debt",
    "cash position": "cash_and_equivalents",
    "cash on hand": "cash_and_equivalents",
    "cash pile": "cash_and_equivalents",
    "war chest": "cash_and_equivalents",
    "book value": "stockholders_equity",

    # Per-share
    "eps": "eps_diluted",
    "earnings per share": "eps_diluted",

    # Capex
    "capex": "capital_expenditures",
    "capital spending": "capital_expenditures",

    # Buybacks
    "buybacks": "share_repurchases",
    "buyback": "share_repurchases",
    "share buyback": "share_repurchases",
    "stock buyback": "share_repurchases",

    # R&D
    "r&d": "research_and_development",
    "r&d spend": "research_and_development",
    "r&d spending": "research_and_development",
    "research spend": "research_and_development",

    # SG&A
    "sg&a": "selling_general_admin",
    "overhead": "selling_general_admin",

    # Growth / trends (special keys for query classifier)
    "growth": "_growth",
    "growth rate": "_growth",
    "yoy growth": "_growth",
    "year over year": "_growth",
    "trend": "_trend",

    # Dividends
    "dividend": "dividends_per_share",
    "dividend yield": "_dividend_yield",
    "payout": "dividends_paid",
}

# Special keys starting with "_" map to ratio computations or multi-metric concepts.
# The query pipeline uses these to trigger ratio computation instead of direct lookup.
SPECIAL_CONCEPTS: dict[str, dict] = {
    "_margins": {
        "description": "Profitability margins",
        "metrics": ["gross_profit", "operating_income", "net_income", "revenue"],
        "ratios": ["gross_margin", "operating_margin", "net_margin"],
    },
    "_gross_margin": {
        "description": "Gross margin (gross profit / revenue)",
        "metrics": ["gross_profit", "revenue"],
        "ratios": ["gross_margin"],
    },
    "_operating_margin": {
        "description": "Operating margin (operating income / revenue)",
        "metrics": ["operating_income", "revenue"],
        "ratios": ["operating_margin"],
    },
    "_net_margin": {
        "description": "Net margin (net income / revenue)",
        "metrics": ["net_income", "revenue"],
        "ratios": ["net_margin"],
    },
    "_leverage": {
        "description": "Financial leverage (debt / equity)",
        "metrics": ["total_debt", "total_liabilities", "stockholders_equity"],
        "ratios": ["debt_to_equity"],
    },
    "_growth": {
        "description": "Revenue/earnings growth rates",
        "metrics": ["revenue", "net_income", "operating_income", "eps_diluted"],
        "ratios": ["revenue_growth", "earnings_growth"],
    },
    "_trend": {
        "description": "Multi-period trends",
        "metrics": ["revenue", "net_income", "gross_profit", "operating_income"],
        "ratios": [],
    },
    "_dividend_yield": {
        "description": "Dividend yield",
        "metrics": ["dividends_per_share"],
        "ratios": ["dividend_yield"],
    },
}


def resolve_jargon(term: str) -> str | None:
    """Resolve a financial jargon term to a canonical metric or special key.

    Returns None if the term isn't recognized jargon.
    Case-insensitive matching.
    """
    normalized = term.strip().lower()
    # Try exact match first
    if normalized in JARGON_MAP:
        return JARGON_MAP[normalized]
    # Try with common punctuation stripped
    normalized_clean = re.sub(r"['''\-]", "", normalized)
    for jargon, canonical in JARGON_MAP.items():
        if re.sub(r"['''\-]", "", jargon) == normalized_clean:
            return canonical
    return None


def is_special_concept(key: str) -> bool:
    """Check if a resolved jargon key is a special multi-metric concept."""
    return key.startswith("_")


def get_special_concept(key: str) -> dict | None:
    """Get the definition of a special concept (metrics + ratios needed)."""
    return SPECIAL_CONCEPTS.get(key)
