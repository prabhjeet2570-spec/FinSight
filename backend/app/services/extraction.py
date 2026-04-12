"""PDF extraction pipeline using pdfplumber.

Handles both table extraction (structured) and text extraction (unstructured).
Page-by-page classification routes pages to the appropriate extractor.
Quality validation flags bad extractions silently returned by pdfplumber.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import pdfplumber

from app.utils.section_detector import detect_section_for_page

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTable:
    page_num: int
    headers: list[str]
    rows: list[dict[str, Any]]
    raw_text: str
    table_type: str | None = None
    period: str | None = None
    quality_ok: bool = True
    quality_issues: list[str] = field(default_factory=list)


@dataclass
class ExtractedPage:
    page_num: int
    text: str
    section: str | None
    tables: list[ExtractedTable]
    is_table_heavy: bool


@dataclass
class ExtractionResult:
    pages: list[ExtractedPage]
    page_count: int
    total_text: str
    all_tables: list[ExtractedTable]


# ---------- Page classification ----------

def _is_table_heavy(page) -> bool:
    """A page is table-heavy if pdfplumber finds tables on it."""
    try:
        tables = page.find_tables()
        return len(tables) > 0
    except Exception:
        return False


# ---------- Quality validation ----------

# A cell is "primarily numeric" if (after stripping currency/parens/whitespace)
# it's mostly digits. This rejects cells like "See note 2" that just contain
# an incidental digit.
NUMERIC_CELL_RE = re.compile(r"^\(?\$?\s*-?[\d,]+\.?\d*\s*%?\)?$")


def _is_numeric_cell(cell: str | None) -> bool:
    if cell is None:
        return False
    s = str(cell).strip()
    if not s:
        return False
    return bool(NUMERIC_CELL_RE.match(s))


def _validate_table_quality(rows: list[list[str | None]]) -> tuple[bool, list[str]]:
    """Detect silently-bad pdfplumber output.

    Returns (is_ok, list_of_issues).
    """
    issues = []

    if not rows or len(rows) < 2:
        issues.append("too few rows")
        return False, issues

    # Check empty cell ratio
    total_cells = sum(len(row) for row in rows)
    empty_cells = sum(1 for row in rows for cell in row if not cell or not str(cell).strip())
    if total_cells > 0 and empty_cells / total_cells > 0.4:
        issues.append(f"empty cells {empty_cells}/{total_cells}")

    # Check column count consistency
    col_counts = [len(row) for row in rows]
    if len(set(col_counts)) > 1:
        issues.append(f"inconsistent column counts: {set(col_counts)}")

    # Financial tables MUST have numeric data — count cells that are primarily
    # numeric (not just contain a digit). Skip the first column (labels) and
    # first row (headers).
    numeric_cells = sum(
        1
        for row in rows[1:]
        for cell in row[1:]
        if _is_numeric_cell(cell)
    )
    if numeric_cells < 2:
        issues.append(f"insufficient numeric data ({numeric_cells} cells)")

    return len(issues) == 0, issues


# ---------- Table type inference ----------

TABLE_TYPE_KEYWORDS = {
    "income_statement": [
        "revenue", "net sales", "cost of sales", "cost of revenue",
        "gross profit", "operating income", "net income", "earnings per share",
        "operating expenses",
    ],
    "balance_sheet": [
        "total assets", "total liabilities", "stockholders' equity",
        "cash and cash equivalents", "accounts receivable", "current assets",
        "current liabilities",
    ],
    "cash_flow": [
        "cash flows", "operating activities", "investing activities",
        "financing activities", "net cash provided",
    ],
}


def _infer_table_type(headers: list[str], rows: list[list[str | None]]) -> str | None:
    """Infer financial statement type from table content."""
    text_blob = " ".join(
        str(cell).lower()
        for row in [headers] + rows
        for cell in row
        if cell
    )
    best_match = None
    best_score = 0
    for table_type, keywords in TABLE_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in text_blob)
        if score > best_score:
            best_score = score
            best_match = table_type
    return best_match if best_score >= 2 else None


# ---------- Table parsing ----------

def _parse_table(raw_table: list[list[str | None]], page_num: int) -> ExtractedTable | None:
    """Convert raw pdfplumber table to structured ExtractedTable."""
    if not raw_table or len(raw_table) < 2:
        return None

    quality_ok, issues = _validate_table_quality(raw_table)

    # Headers = first non-empty row
    headers_raw = raw_table[0]
    headers = [str(h).strip() if h else f"col_{i}" for i, h in enumerate(headers_raw)]

    # Rows = remaining rows, normalized to dicts
    rows = []
    for row_data in raw_table[1:]:
        if not any(cell and str(cell).strip() for cell in row_data):
            continue
        # Pad row to header length
        padded = list(row_data) + [None] * (len(headers) - len(row_data))
        row_dict = {
            "label": str(padded[0]).strip() if padded[0] else "",
            "values": {
                headers[i]: str(padded[i]).strip() if padded[i] else None
                for i in range(1, len(headers))
            },
        }
        if row_dict["label"]:
            rows.append(row_dict)

    if not rows:
        return None

    raw_text = "\n".join(
        " | ".join(str(c) if c else "" for c in row)
        for row in raw_table
    )

    table_type = _infer_table_type(headers, raw_table)

    return ExtractedTable(
        page_num=page_num,
        headers=headers,
        rows=rows,
        raw_text=raw_text,
        table_type=table_type,
        quality_ok=quality_ok,
        quality_issues=issues,
    )


# ---------- Main extraction ----------

def extract_pdf(pdf_path: str) -> ExtractionResult:
    """Extract text and tables from a PDF file page by page."""
    pages: list[ExtractedPage] = []
    all_tables: list[ExtractedTable] = []
    text_parts: list[str] = []
    current_section: str | None = None

    with pdfplumber.open(pdf_path) as pdf:
        page_count = len(pdf.pages)
        logger.info(f"Extracting {page_count} pages from {pdf_path}")

        for i, page in enumerate(pdf.pages, start=1):
            # Extract text (always)
            try:
                page_text = page.extract_text() or ""
            except Exception as e:
                logger.warning(f"Page {i} text extraction failed: {e}")
                page_text = ""

            # Detect section (carries forward from previous page)
            current_section = detect_section_for_page(page_text, current_section)

            # Extract tables if page is table-heavy
            page_tables: list[ExtractedTable] = []
            is_table_heavy = _is_table_heavy(page)

            if is_table_heavy:
                try:
                    raw_tables = page.extract_tables() or []
                except Exception as e:
                    logger.warning(f"Page {i} table extraction failed: {e}")
                    raw_tables = []

                for raw_table in raw_tables:
                    parsed = _parse_table(raw_table, page_num=i)
                    if parsed:
                        page_tables.append(parsed)
                        all_tables.append(parsed)
                        if not parsed.quality_ok:
                            logger.info(
                                f"Page {i} table quality issues: {parsed.quality_issues}"
                            )

            pages.append(ExtractedPage(
                page_num=i,
                text=page_text,
                section=current_section,
                tables=page_tables,
                is_table_heavy=is_table_heavy,
            ))
            text_parts.append(page_text)

    return ExtractionResult(
        pages=pages,
        page_count=page_count,
        total_text="\n\n".join(text_parts),
        all_tables=all_tables,
    )
