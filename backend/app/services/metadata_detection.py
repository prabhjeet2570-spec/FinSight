"""Detect document metadata (company, filing type, period) from filename + first page.

This is a best-effort heuristic. Phase 3 will cross-reference with EdgarTools
when a ticker can be inferred.
"""
import re
from pathlib import Path

from app.models.document import DocumentMetadata


# ---------- Filing type ----------

FILING_TYPE_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("10-K", re.compile(r"\b(?:10[-_]?K|annual\s+report)\b", re.IGNORECASE)),
    ("10-Q", re.compile(r"\b10[-_]?Q\b|quarterly\s+report", re.IGNORECASE)),
    ("8-K", re.compile(r"\b8[-_]?K\b|current\s+report", re.IGNORECASE)),
    ("press-release", re.compile(r"press[-_\s]release|earnings[-_\s]release", re.IGNORECASE)),
    ("S-1", re.compile(r"\bS[-_]?1\b", re.IGNORECASE)),
]


def detect_filing_type(filename: str, first_page_text: str) -> str | None:
    combined = f"{filename}\n{first_page_text}"
    for filing_type, pattern in FILING_TYPE_PATTERNS:
        if pattern.search(combined):
            return filing_type
    return None


# ---------- Period ----------

PERIOD_PATTERNS = [
    re.compile(r"(?:for\s+the\s+)?(?:three|nine|six|twelve)\s+months\s+ended\s+(\w+\s+\d{1,2},?\s+(20\d{2}))", re.IGNORECASE),
    re.compile(r"\bQ([1-4])[\s\-]?(20\d{2})\b", re.IGNORECASE),
    re.compile(r"\b(20\d{2})\s*Q([1-4])\b", re.IGNORECASE),
    re.compile(r"fiscal\s+year\s+(?:ended\s+)?(20\d{2})", re.IGNORECASE),
]


def detect_period(filename: str, first_page_text: str) -> tuple[str | None, str | None]:
    """Returns (period, fiscal_year)."""
    combined = f"{filename}\n{first_page_text}"

    # Try Q-pattern first (most specific)
    q_match = re.search(r"\bQ([1-4])[\s\-]?(20\d{2})\b", combined, re.IGNORECASE)
    if q_match:
        return f"Q{q_match.group(1)} {q_match.group(2)}", f"FY{q_match.group(2)}"

    q_match2 = re.search(r"\b(20\d{2})\s*Q([1-4])\b", combined, re.IGNORECASE)
    if q_match2:
        return f"Q{q_match2.group(2)} {q_match2.group(1)}", f"FY{q_match2.group(1)}"

    # "Three months ended September 28, 2025" -> infer quarter from month
    months_match = re.search(
        r"(?:three|nine|six|twelve)\s+months\s+ended\s+(\w+)\s+\d{1,2},?\s+(20\d{2})",
        combined,
        re.IGNORECASE,
    )
    if months_match:
        month_name = months_match.group(1).lower()
        year = months_match.group(2)
        quarter = _month_to_quarter(month_name)
        if quarter:
            return f"Q{quarter} {year}", f"FY{year}"
        return f"Period ending {month_name.title()} {year}", f"FY{year}"

    # Just a year
    year_match = re.search(r"fiscal\s+year\s+(?:ended\s+)?(20\d{2})", combined, re.IGNORECASE)
    if year_match:
        return f"FY{year_match.group(1)}", f"FY{year_match.group(1)}"

    return None, None


def _month_to_quarter(month: str) -> int | None:
    quarters = {
        "january": 1, "february": 1, "march": 1,
        "april": 2, "may": 2, "june": 2,
        "july": 3, "august": 3, "september": 3,
        "october": 4, "november": 4, "december": 4,
    }
    return quarters.get(month.lower())


# ---------- Company ----------

# Common SEC filer suffixes
COMPANY_SUFFIXES = r"(?:Inc\.?|Corporation|Corp\.?|Company|Co\.?|Ltd\.?|LLC|Holdings|Group|plc)"


def detect_company(filename: str, first_page_text: str) -> tuple[str, str | None]:
    """Returns (company_name, ticker_or_none)."""
    # Look for ticker in parentheses near the top: "Apple Inc. (AAPL)"
    ticker_match = re.search(
        r"([A-Z][A-Za-z&.,\s]+?\s+" + COMPANY_SUFFIXES + r")\s*\(([A-Z]{1,5})\)",
        first_page_text[:2000],
    )
    if ticker_match:
        return ticker_match.group(1).strip().rstrip(","), ticker_match.group(2)

    # Standalone ticker mention
    standalone_ticker = re.search(
        r"(?:NASDAQ|NYSE|Nasdaq|NYSE)\s*:\s*([A-Z]{1,5})",
        first_page_text[:2000],
    )
    ticker = standalone_ticker.group(1) if standalone_ticker else None

    # Company name: first matching "X Inc." pattern in early text
    company_match = re.search(
        r"\b([A-Z][A-Za-z&.\s]{2,40}?\s+" + COMPANY_SUFFIXES + r")",
        first_page_text[:2000],
    )
    if company_match:
        return company_match.group(1).strip(), ticker

    # Fallback: filename without extension and common separators
    name_from_file = Path(filename).stem
    name_from_file = re.sub(r"[-_]", " ", name_from_file).strip()
    if name_from_file:
        return name_from_file, ticker

    return "Unknown", ticker


# ---------- Top-level ----------

def detect_metadata(filename: str, first_page_text: str) -> DocumentMetadata:
    company, ticker = detect_company(filename, first_page_text)
    filing_type = detect_filing_type(filename, first_page_text)
    period, fiscal_year = detect_period(filename, first_page_text)
    return DocumentMetadata(
        company=company,
        ticker=ticker,
        filing_type=filing_type,
        period=period,
        fiscal_year=fiscal_year,
    )
