"""Metric synonym dictionary for financial term normalization.

Maps canonical metric names to all known aliases found in SEC filings.
Different companies use different labels for the same concept — this
dictionary lets us recognize them all.

Used by:
  - metric_flattening.py: match table row labels to canonical names
  - retrieval.py: expand user queries to find related metrics
"""
import re

# Canonical metric name -> list of patterns (regex) matching how it appears
# in SEC filing tables. Patterns are matched against lowercase, stripped labels.
#
# ~60 entries covering income statement, balance sheet, cash flow, and per-share metrics.

METRIC_SYNONYMS: dict[str, list[str]] = {
    # ---------- Income Statement ----------
    "revenue": [
        r"^(?:total\s+)?(?:net\s+)?(?:revenue|sales)$",
        r"^net\s+(?:sales|revenue)$",
        r"^total\s+net\s+(?:sales|revenue)$",
        r"^product\s+(?:revenue|sales)$",
        r"^service\s+(?:revenue|sales)$",
        r"^subscription\s+revenue$",
        r"^interest\s+income$",
        r"^total\s+interest\s+income$",
        r"^net\s+interest\s+income$",
        r"^premium(?:s)?\s+(?:earned|revenue)$",
    ],
    "cost_of_revenue": [
        r"^(?:total\s+)?cost\s+of\s+(?:sales|revenue|goods\s+sold|products?\s+sold)$",
        r"^cost\s+of\s+(?:products?\s+and\s+services?)$",
        r"^cogs$",
    ],
    "gross_profit": [
        r"^gross\s+(?:profit|margin|income)$",
    ],
    "research_and_development": [
        r"^research\s+and\s+development$",
        r"^r\s*&\s*d(?:\s+expense(?:s)?)?$",
        r"^research,?\s+development(?:\s+and\s+engineering)?$",
    ],
    "selling_general_admin": [
        r"^selling,?\s*general\s+and\s+admin(?:istrative)?$",
        r"^sg\s*&\s*a$",
        r"^selling\s+and\s+marketing$",
        r"^general\s+and\s+admin(?:istrative)?$",
    ],
    "operating_expenses": [
        r"^total\s+operating\s+expenses$",
        r"^operating\s+expenses$",
    ],
    "operating_income": [
        r"^(?:total\s+)?operating\s+income(?:\s*\(loss\))?$",
        r"^income(?:\s*\(loss\))?\s+from\s+operations$",
        r"^operating\s+(?:profit|earnings)$",
    ],
    "interest_expense": [
        r"^interest\s+expense$",
        r"^(?:total\s+)?interest\s+(?:expense|cost)(?:\s*,?\s*net)?$",
    ],
    "pretax_income": [
        r"^income(?:\s*\(loss\))?\s+before\s+(?:income\s+)?tax(?:es)?$",
        r"^(?:pre[-\s]?tax|pretax)\s+(?:income|earnings|profit)$",
        r"^earnings\s+before\s+(?:income\s+)?tax(?:es)?$",
    ],
    "income_tax_expense": [
        r"^(?:provision|expense)\s+for\s+income\s+tax(?:es)?$",
        r"^income\s+tax\s+(?:expense|provision|benefit)$",
    ],
    "net_income": [
        r"^net\s+(?:income|earnings|profit)(?:\s*\(loss\))?$",
        r"^(?:net\s+)?(?:income|earnings)\s+attributable\s+to\s+.*$",
        r"^profit\s+(?:for\s+the\s+period|after\s+tax)$",
    ],
    "ebitda": [
        r"^ebitda$",
        r"^adjusted\s+ebitda$",
    ],

    # ---------- Per-Share Metrics ----------
    "eps_basic": [
        r"^basic\s+(?:earnings|net\s+income)\s+per\s+(?:common\s+)?share$",
        r"^(?:earnings|net\s+income)\s+per\s+share[\s,\-—]+basic$",
        r"^basic\s+eps$",
    ],
    "eps_diluted": [
        r"^diluted\s+(?:earnings|net\s+income)\s+per\s+(?:common\s+)?share$",
        r"^(?:earnings|net\s+income)\s+per\s+share[\s,\-—]+diluted$",
        r"^diluted\s+eps$",
    ],
    "dividends_per_share": [
        r"^(?:cash\s+)?dividends?\s+(?:declared\s+)?per\s+(?:common\s+)?share$",
    ],
    "shares_outstanding_basic": [
        r"^(?:weighted[\s-]average\s+)?(?:basic\s+)?shares?\s+outstanding[\s,\-—]*basic$",
        r"^basic\s+(?:weighted[\s-]average\s+)?shares?\s+outstanding$",
    ],
    "shares_outstanding_diluted": [
        r"^(?:weighted[\s-]average\s+)?(?:diluted\s+)?shares?\s+outstanding[\s,\-—]*diluted$",
        r"^diluted\s+(?:weighted[\s-]average\s+)?shares?\s+outstanding$",
    ],

    # ---------- Balance Sheet — Assets ----------
    "cash_and_equivalents": [
        r"^cash\s+and\s+cash\s+equivalents$",
        r"^cash,?\s+cash\s+equivalents(?:\s+and\s+.*)?$",
    ],
    "short_term_investments": [
        r"^(?:short[\s-]term|current|marketable)\s+(?:investments|securities)$",
    ],
    "accounts_receivable": [
        r"^(?:accounts?\s+)?receivable(?:s)?(?:,?\s*net)?$",
        r"^trade\s+(?:accounts?\s+)?receivable(?:s)?$",
    ],
    "inventories": [
        r"^inventor(?:y|ies)(?:,?\s*net)?$",
    ],
    "current_assets": [
        r"^total\s+current\s+assets$",
    ],
    "property_plant_equipment": [
        r"^property(?:,?\s*plant)?\s+and\s+equipment(?:,?\s*net)?$",
        r"^(?:net\s+)?pp\s*&\s*e$",
    ],
    "goodwill": [
        r"^goodwill$",
    ],
    "intangible_assets": [
        r"^(?:acquired\s+)?intangible\s+assets(?:,?\s*net)?$",
    ],
    "total_assets": [
        r"^total\s+assets$",
    ],

    # ---------- Balance Sheet — Liabilities ----------
    "accounts_payable": [
        r"^accounts?\s+payable$",
    ],
    "short_term_debt": [
        r"^(?:short[\s-]term|current(?:\s+portion\s+of)?)\s+(?:debt|borrowings?)$",
        r"^commercial\s+paper$",
        r"^current\s+portion\s+of\s+long[\s-]term\s+debt$",
    ],
    "current_liabilities": [
        r"^total\s+current\s+liabilities$",
    ],
    "long_term_debt": [
        r"^long[\s-]term\s+debt(?:,?\s*(?:net|excluding\s+current))?$",
        r"^(?:term\s+)?(?:debt|notes?\s+payable)[\s,\-—]+(?:non[\s-]?current|long[\s-]term)$",
    ],
    "total_debt": [
        r"^total\s+(?:debt|borrowings?)$",
    ],
    "total_liabilities": [
        r"^total\s+liabilities$",
    ],
    "stockholders_equity": [
        r"^(?:total\s+)?(?:stockholders?|shareholders?)[''\u2019]?\s+equity$",
        r"^total\s+equity$",
        r"^(?:total\s+)?(?:members?|partners?)[''\u2019]?\s+(?:equity|capital)$",
    ],
    "retained_earnings": [
        r"^retained\s+earnings(?:\s*\((?:accumulated\s+)?deficit\))?$",
    ],
    "total_liabilities_and_equity": [
        r"^total\s+liabilities\s+and\s+(?:stockholders?|shareholders?)[''\u2019]?\s+equity$",
        r"^total\s+liabilities\s+and\s+equity$",
    ],

    # ---------- Cash Flow Statement ----------
    "operating_cash_flow": [
        r"^(?:net\s+)?cash\s+(?:provided\s+by|(?:used\s+in|from))\s+operating\s+activities$",
        r"^cash\s+flows?\s+from\s+operat(?:ing|ions)$",
    ],
    "capital_expenditures": [
        r"^(?:purchases?\s+of|payments?\s+for)\s+property(?:,?\s*plant)?\s+and\s+equipment$",
        r"^capital\s+expenditure(?:s)?$",
        r"^capex$",
    ],
    "investing_cash_flow": [
        r"^(?:net\s+)?cash\s+(?:provided\s+by|(?:used\s+in|from))\s+investing\s+activities$",
        r"^cash\s+flows?\s+from\s+investing$",
    ],
    "financing_cash_flow": [
        r"^(?:net\s+)?cash\s+(?:provided\s+by|(?:used\s+in|from))\s+financing\s+activities$",
        r"^cash\s+flows?\s+from\s+financing$",
    ],
    "free_cash_flow": [
        r"^free\s+cash\s+flow$",
    ],
    "depreciation_amortization": [
        r"^depreciation\s+and\s+amortization$",
        r"^depreciation$",
        r"^d\s*&\s*a$",
    ],
    "stock_based_compensation": [
        r"^(?:stock|share)[\s-]based\s+compensation(?:\s+expense)?$",
    ],
    "dividends_paid": [
        r"^(?:payments?\s+of|cash\s+)?dividends?\s+paid$",
        r"^dividends?\s+(?:paid|payments?)$",
    ],
    "share_repurchases": [
        r"^(?:repurchase(?:s)?\s+of|payments?\s+for.*)\s+(?:common\s+)?(?:stock|shares?)$",
        r"^(?:treasury\s+)?stock\s+repurchase(?:s)?$",
    ],
}

# Total count of canonical metrics
METRIC_COUNT = len(METRIC_SYNONYMS)  # ~48 canonical metrics

# ---------- Compiled patterns for fast matching ----------

_compiled_synonyms: dict[str, list[re.Pattern]] = {
    metric: [re.compile(p, re.IGNORECASE) for p in patterns]
    for metric, patterns in METRIC_SYNONYMS.items()
}


def match_metric(label: str) -> str | None:
    """Match a table row label to a canonical metric name.

    Cleans the label (strips whitespace, footnote markers, trailing
    punctuation) then checks against all synonym patterns.
    """
    label_clean = label.strip().lower()
    # Strip footnote markers like (1), [2], etc.
    label_clean = re.sub(r"[\(\[][\d\w,\s]*[\)\]]", "", label_clean).strip()
    label_clean = label_clean.rstrip(":").strip()

    for canonical, patterns in _compiled_synonyms.items():
        for pattern in patterns:
            if pattern.match(label_clean):
                return canonical
    return None


def get_synonyms_for_metric(metric_name: str) -> list[str]:
    """Return all known text aliases for a canonical metric name.

    Used by retrieval to expand a metric query into multiple search terms.
    Returns plain-text labels (not regexes) for use in text search.
    """
    TEXT_LABELS: dict[str, list[str]] = {
        "revenue": ["revenue", "net sales", "total sales", "total revenue", "net revenue"],
        "cost_of_revenue": ["cost of revenue", "cost of sales", "cost of goods sold", "COGS"],
        "gross_profit": ["gross profit", "gross margin", "gross income"],
        "research_and_development": ["research and development", "R&D"],
        "selling_general_admin": ["selling general and administrative", "SG&A"],
        "operating_expenses": ["operating expenses", "total operating expenses"],
        "operating_income": ["operating income", "income from operations", "operating profit"],
        "interest_expense": ["interest expense"],
        "pretax_income": ["pretax income", "income before taxes", "earnings before taxes"],
        "income_tax_expense": ["income tax expense", "provision for income taxes"],
        "net_income": ["net income", "net earnings", "net profit"],
        "ebitda": ["EBITDA", "adjusted EBITDA"],
        "eps_basic": ["basic earnings per share", "basic EPS"],
        "eps_diluted": ["diluted earnings per share", "diluted EPS"],
        "dividends_per_share": ["dividends per share"],
        "cash_and_equivalents": ["cash and cash equivalents", "cash"],
        "accounts_receivable": ["accounts receivable", "receivables"],
        "inventories": ["inventories", "inventory"],
        "current_assets": ["total current assets", "current assets"],
        "total_assets": ["total assets"],
        "accounts_payable": ["accounts payable"],
        "current_liabilities": ["total current liabilities", "current liabilities"],
        "long_term_debt": ["long-term debt"],
        "total_debt": ["total debt"],
        "total_liabilities": ["total liabilities"],
        "stockholders_equity": ["stockholders equity", "shareholders equity", "total equity"],
        "retained_earnings": ["retained earnings"],
        "operating_cash_flow": ["cash from operations", "operating cash flow"],
        "capital_expenditures": ["capital expenditures", "capex"],
        "investing_cash_flow": ["cash from investing", "investing cash flow"],
        "financing_cash_flow": ["cash from financing", "financing cash flow"],
        "free_cash_flow": ["free cash flow", "FCF"],
        "depreciation_amortization": ["depreciation and amortization", "D&A"],
        "stock_based_compensation": ["stock-based compensation"],
        "dividends_paid": ["dividends paid"],
        "share_repurchases": ["share repurchases", "stock repurchases", "buybacks"],
    }
    return TEXT_LABELS.get(metric_name, [metric_name.replace("_", " ")])
