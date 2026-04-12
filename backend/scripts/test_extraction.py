"""Standalone test script for Phase 2 extraction pipeline.

Tests each component with synthetic inputs (no DB, no real PDF).
Run from backend dir: python -m scripts.test_extraction
"""
import sys

from app.services.metric_flattening import (
    flatten_tables,
    parse_number,
    _classify_columns,
    _match_metric,
)
from app.services.extraction import (
    ExtractedTable,
    _validate_table_quality,
    _infer_table_type,
    _parse_table,
)
from app.services.metadata_detection import detect_metadata
from app.utils.section_detector import detect_section


PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"

results = []


def check(name: str, actual, expected):
    ok = actual == expected
    results.append(ok)
    marker = PASS if ok else FAIL
    print(f"  {marker} {name}")
    if not ok:
        print(f"      expected: {expected!r}")
        print(f"      actual:   {actual!r}")


def section(title: str):
    print(f"\n{title}")
    print("-" * len(title))


# ---------- Number parsing ----------
section("parse_number")
check("plain int", parse_number("1234"), 1234.0)
check("with commas", parse_number("1,234,567"), 1234567.0)
check("with dollar sign", parse_number("$1,234.56"), 1234.56)
check("parens = negative", parse_number("(1,234)"), -1234.0)
check("dash", parse_number("-"), None)
check("em-dash", parse_number("—"), None)
check("None", parse_number(None), None)
check("empty", parse_number(""), None)
check("decimal only", parse_number("0.45"), 0.45)


# ---------- Metric matching ----------
section("_match_metric")
check("Total Net Sales", _match_metric("Total net sales"), "revenue")
check("Net Sales", _match_metric("Net sales"), "revenue")
check("Revenue", _match_metric("Revenue"), "revenue")
check("Net Income", _match_metric("Net income"), "net_income")
check("Gross Profit", _match_metric("Gross profit"), "gross_profit")
check("Cost of Sales", _match_metric("Cost of sales"), "cost_of_revenue")
check("Total Assets", _match_metric("Total assets"), "total_assets")
check("Diluted EPS", _match_metric("Diluted earnings per share"), "eps_diluted")
check("Random label", _match_metric("Random unrelated label"), None)


# ---------- Section detection ----------
section("detect_section")
check(
    "MD&A header",
    detect_section("Item 2. Management's Discussion and Analysis of Financial Condition"),
    "MD&A",
)
check(
    "Risk Factors",
    detect_section("PART II — ITEM 1A. RISK FACTORS\n\nThe following risks..."),
    "Risk Factors",
)
check(
    "Financial Statements",
    detect_section("Item 1. Financial Statements\n\nCondensed Consolidated..."),
    "Financial Statements",
)
check("No header", detect_section("Just some random text without a section marker"), None)


# ---------- Table quality validation ----------
section("_validate_table_quality")
good_table = [
    ["Item", "Q3 2025", "Q3 2024"],
    ["Revenue", "94,000", "85,800"],
    ["Net Income", "23,400", "21,400"],
]
ok, _ = _validate_table_quality(good_table)
check("good table accepted", ok, True)

empty_table = [
    ["Item", "Q3 2025", "Q3 2024"],
    ["", "", ""],
    ["", "", ""],
]
ok, issues = _validate_table_quality(empty_table)
check("empty table rejected", ok, False)

no_numbers = [
    ["Item", "Note", "Description"],
    ["Revenue", "See note 2", "Recognized when..."],
]
ok, _ = _validate_table_quality(no_numbers)
check("no-numbers table rejected", ok, False)


# ---------- Table type inference ----------
section("_infer_table_type")
income_headers = ["Item", "Q3 2025", "Q3 2024"]
income_rows = [
    ["Revenue", "94,000", "85,800"],
    ["Cost of sales", "50,000", "47,000"],
    ["Gross profit", "44,000", "38,800"],
    ["Operating income", "30,000", "25,000"],
    ["Net income", "23,400", "21,400"],
]
check(
    "income statement detected",
    _infer_table_type(income_headers, income_rows),
    "income_statement",
)

balance_rows = [
    ["Cash and cash equivalents", "30,000", "25,000"],
    ["Accounts receivable", "20,000", "18,000"],
    ["Total assets", "350,000", "330,000"],
    ["Total liabilities", "270,000", "260,000"],
]
check(
    "balance sheet detected",
    _infer_table_type(["Item", "Sep 2025", "Sep 2024"], balance_rows),
    "balance_sheet",
)


# ---------- Column classification ----------
section("_classify_columns")
headers = ["", "Three Months Ended September 28, 2025", "Three Months Ended September 30, 2024"]
cur_idx, prior_idx, cur_period, prior_period = _classify_columns(headers)
check("current idx", cur_idx, 1)
check("prior idx", prior_idx, 2)
check("current period", cur_period, "2025")
check("prior period", prior_period, "2024")


# ---------- End-to-end: parse table -> flatten metrics ----------
section("flatten_tables (end-to-end)")
raw_table = [
    ["", "Three Months Ended Sep 28, 2025", "Three Months Ended Sep 30, 2024"],
    ["Net sales", "$94,000", "$85,800"],
    ["Cost of sales", "50,000", "47,000"],
    ["Gross profit", "44,000", "38,800"],
    ["Operating income", "30,000", "25,000"],
    ["Net income", "$23,400", "$21,400"],
    ["Diluted earnings per share", "$1.40", "$1.25"],
]
parsed = _parse_table(raw_table, page_num=4)
check("table parsed", parsed is not None, True)
check("table type inferred", parsed.table_type if parsed else None, "income_statement")

metrics = flatten_tables([parsed]) if parsed else []
metric_dict = {m.metric_name: m for m in metrics}
check("revenue extracted", metric_dict.get("revenue") is not None, True)
if "revenue" in metric_dict:
    check("revenue current value", metric_dict["revenue"].value, 94000.0)
    check("revenue prior value", metric_dict["revenue"].prior_value, 85800.0)
    # 94000 -> 85800 = +9.55%
    pct = metric_dict["revenue"].change_pct
    check(
        "revenue change_pct ~9.55",
        round(pct, 2) if pct is not None else None,
        9.56,
    )
check("net_income extracted", metric_dict.get("net_income") is not None, True)
check("gross_profit extracted", metric_dict.get("gross_profit") is not None, True)
check("eps_diluted extracted", metric_dict.get("eps_diluted") is not None, True)
if "eps_diluted" in metric_dict:
    check("eps_diluted value", metric_dict["eps_diluted"].value, 1.40)


# ---------- Metadata detection ----------
section("detect_metadata")
first_page = """
Apple Inc. (AAPL)
NASDAQ: AAPL

UNITED STATES SECURITIES AND EXCHANGE COMMISSION
Washington, D.C. 20549
FORM 10-Q

For the quarterly period ended September 28, 2025
"""
md = detect_metadata("aapl-10q-q3-2025.pdf", first_page)
check("company detected", md.company.startswith("Apple"), True)
check("ticker detected", md.ticker, "AAPL")
check("filing type", md.filing_type, "10-Q")
check("period", md.period, "Q3 2025")


# ---------- Summary ----------
print()
total = len(results)
passed = sum(results)
print(f"{passed}/{total} tests passed")
sys.exit(0 if passed == total else 1)
