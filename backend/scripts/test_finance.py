"""Tests for the financial intelligence layer (Phase 3).

Tests synonyms, jargon resolution, and ratio computation.
Run from backend dir: python -m scripts.test_finance
"""
import sys

from app.finance.synonyms import match_metric, get_synonyms_for_metric
from app.finance.jargon import resolve_jargon, is_special_concept, get_special_concept
from app.finance.ratios import compute_ratio, compute_all_ratios


PASS = "\033[92m\u2713\033[0m"
FAIL = "\033[91m\u2717\033[0m"

results = []


def check(name: str, actual, expected):
    ok = actual == expected
    results.append(ok)
    marker = PASS if ok else FAIL
    print(f"  {marker} {name}")
    if not ok:
        print(f"      expected: {expected!r}")
        print(f"      actual:   {actual!r}")


def check_true(name: str, condition: bool, detail: str = ""):
    results.append(condition)
    marker = PASS if condition else FAIL
    suffix = f" ({detail})" if detail else ""
    print(f"  {marker} {name}{suffix}")


def section(title: str):
    print(f"\n{title}")
    print("-" * len(title))


# ---------- Synonym matching ----------
section("match_metric (expanded synonyms)")

# Income statement
check("Total net sales", match_metric("Total net sales"), "revenue")
check("Net sales", match_metric("Net sales"), "revenue")
check("Revenue", match_metric("Revenue"), "revenue")
check("Total revenue", match_metric("Total revenue"), "revenue")
check("Net income", match_metric("Net income"), "net_income")
check("Net earnings", match_metric("Net earnings"), "net_income")
check("Gross profit", match_metric("Gross profit"), "gross_profit")
check("Cost of sales", match_metric("Cost of sales"), "cost_of_revenue")
check("Cost of goods sold", match_metric("Cost of goods sold"), "cost_of_revenue")
check("Operating income", match_metric("Operating income"), "operating_income")
check("Income from operations", match_metric("Income from operations"), "operating_income")
check("Operating expenses", match_metric("Operating expenses"), "operating_expenses")
check("Research and development", match_metric("Research and development"), "research_and_development")
check("Selling, general and administrative", match_metric("Selling, general and administrative"), "selling_general_admin")
check("Interest expense", match_metric("Interest expense"), "interest_expense")
check("Income before income taxes", match_metric("Income before income taxes"), "pretax_income")
check("Provision for income taxes", match_metric("Provision for income taxes"), "income_tax_expense")

# Per-share
check("Basic earnings per share", match_metric("Basic earnings per share"), "eps_basic")
check("Diluted earnings per share", match_metric("Diluted earnings per share"), "eps_diluted")

# Balance sheet
check("Total assets", match_metric("Total assets"), "total_assets")
check("Total liabilities", match_metric("Total liabilities"), "total_liabilities")
check("Stockholders' equity", match_metric("Stockholders' equity"), "stockholders_equity")
check("Cash and cash equivalents", match_metric("Cash and cash equivalents"), "cash_and_equivalents")
check("Accounts receivable, net", match_metric("Accounts receivable, net"), "accounts_receivable")
check("Inventories", match_metric("Inventories"), "inventories")
check("Total current assets", match_metric("Total current assets"), "current_assets")
check("Total current liabilities", match_metric("Total current liabilities"), "current_liabilities")
check("Long-term debt", match_metric("Long-term debt"), "long_term_debt")
check("Goodwill", match_metric("Goodwill"), "goodwill")
check("Retained earnings", match_metric("Retained earnings"), "retained_earnings")

# Cash flow
check("Cash from operating activities", match_metric(
    "Net cash provided by operating activities"), "operating_cash_flow")
check("Cash from investing activities", match_metric(
    "Net cash used in investing activities"), "investing_cash_flow")
check("Cash from financing activities", match_metric(
    "Net cash used in financing activities"), "financing_cash_flow")
check("Depreciation and amortization", match_metric("Depreciation and amortization"), "depreciation_amortization")
check("Stock-based compensation", match_metric("Stock-based compensation"), "stock_based_compensation")

# Should NOT match
check("Random label", match_metric("Some random text"), None)
check("See note 2", match_metric("See note 2"), None)

# With footnote markers (should be stripped)
check("Revenue (1)", match_metric("Revenue (1)"), "revenue")
check("Net income [2]", match_metric("Net income [2]"), "net_income")


# ---------- Synonym text expansion ----------
section("get_synonyms_for_metric")

rev_synonyms = get_synonyms_for_metric("revenue")
check_true("revenue has multiple synonyms", len(rev_synonyms) >= 3,
           f"got {len(rev_synonyms)}: {rev_synonyms}")
check_true("'net sales' in revenue synonyms", "net sales" in rev_synonyms)

ni_synonyms = get_synonyms_for_metric("net_income")
check_true("net_income has synonyms", len(ni_synonyms) >= 2)

unknown = get_synonyms_for_metric("nonexistent_metric")
check_true("unknown metric returns fallback", len(unknown) >= 1)


# ---------- Jargon resolution ----------
section("resolve_jargon")

check("top line -> revenue", resolve_jargon("top line"), "revenue")
check("bottom line -> net_income", resolve_jargon("bottom line"), "net_income")
check("eps -> eps_diluted", resolve_jargon("eps"), "eps_diluted")
check("burn rate -> operating_cash_flow", resolve_jargon("burn rate"), "operating_cash_flow")
check("capex -> capital_expenditures", resolve_jargon("capex"), "capital_expenditures")
check("buybacks -> share_repurchases", resolve_jargon("buybacks"), "share_repurchases")
check("r&d -> research_and_development", resolve_jargon("r&d"), "research_and_development")
check("sg&a -> selling_general_admin", resolve_jargon("sg&a"), "selling_general_admin")
check("cash position -> cash_and_equivalents", resolve_jargon("cash position"), "cash_and_equivalents")
check("margins -> _margins (special)", resolve_jargon("margins"), "_margins")
check("gross margin -> _gross_margin", resolve_jargon("gross margin"), "_gross_margin")
check("leverage -> _leverage", resolve_jargon("leverage"), "_leverage")
check("growth -> _growth", resolve_jargon("growth"), "_growth")
check("unknown jargon -> None", resolve_jargon("flibbertigibbet"), None)

# Case insensitive
check("TOP LINE (case)", resolve_jargon("TOP LINE"), "revenue")
check("Bottom Line (case)", resolve_jargon("Bottom Line"), "net_income")


# ---------- Special concepts ----------
section("special concepts")

check_true("_margins is special", is_special_concept("_margins"))
check_true("revenue is NOT special", not is_special_concept("revenue"))

margins = get_special_concept("_margins")
check_true("_margins has metrics", margins is not None and len(margins["metrics"]) >= 3)
check_true("_margins has ratios", margins is not None and len(margins["ratios"]) >= 2)

leverage = get_special_concept("_leverage")
check_true("_leverage defined", leverage is not None)
check_true("_leverage has debt metric", leverage is not None and "total_debt" in leverage["metrics"])


# ---------- Ratio computation ----------
section("compute_ratio")

# Gross margin: 44000 / 94000 = 46.81%
metrics = {
    "revenue": (94000.0, 85800.0),
    "gross_profit": (44000.0, 38800.0),
    "operating_income": (30000.0, 25000.0),
    "net_income": (23400.0, 21400.0),
    "total_assets": (350000.0, 330000.0),
    "total_liabilities": (270000.0, 260000.0),
    "stockholders_equity": (80000.0, 70000.0),
    "current_assets": (120000.0, 110000.0),
    "current_liabilities": (90000.0, 85000.0),
}

gm = compute_ratio("gross_margin", metrics)
check_true("gross_margin computed", gm is not None)
if gm:
    check("gross_margin value", gm.value, 46.81)
    check("gross_margin prior", gm.prior_value, 45.22)
    check("gross_margin format", gm.format, "percentage")

om = compute_ratio("operating_margin", metrics)
check_true("operating_margin computed", om is not None)
if om:
    check("operating_margin value", om.value, 31.91)

nm = compute_ratio("net_margin", metrics)
check_true("net_margin computed", nm is not None)
if nm:
    check("net_margin value", nm.value, 24.89)

cr = compute_ratio("current_ratio", metrics)
check_true("current_ratio computed", cr is not None)
if cr:
    check("current_ratio value", cr.value, 1.33)
    check("current_ratio format", cr.format, "ratio")

dte = compute_ratio("debt_to_assets", metrics)
check_true("debt_to_assets computed", dte is not None)
if dte:
    check("debt_to_assets value", dte.value, 0.77)

roe = compute_ratio("return_on_equity", metrics)
check_true("return_on_equity computed", roe is not None)
if roe:
    check("roe value", roe.value, 29.25)

# Growth ratio (uses change_pct)
rg = compute_ratio("revenue_growth", metrics)
check_true("revenue_growth computed", rg is not None)
if rg:
    # Growth ratios don't go through the round() path — check approximate
    check_true("revenue_growth ~9.56",
               rg.value is not None and round(rg.value, 1) == 9.6,
               f"got {rg.value}")

# Missing metrics -> None
missing = compute_ratio("fcf_margin", metrics)
check("missing metric returns None", missing, None)

# Invalid ratio name -> None
invalid = compute_ratio("nonexistent_ratio", metrics)
check("invalid ratio returns None", invalid, None)


# ---------- compute_all_ratios ----------
section("compute_all_ratios")

all_ratios = compute_all_ratios(metrics)
ratio_names = {r.name for r in all_ratios}
check_true("gross_margin in results", "gross_margin" in ratio_names)
check_true("operating_margin in results", "operating_margin" in ratio_names)
check_true("net_margin in results", "net_margin" in ratio_names)
check_true("current_ratio in results", "current_ratio" in ratio_names)
check_true("at least 8 ratios computed", len(all_ratios) >= 8,
           f"got {len(all_ratios)}: {ratio_names}")


# ---------- Summary ----------
print()
total = len(results)
passed = sum(results)
print(f"{passed}/{total} tests passed")
sys.exit(0 if passed == total else 1)
