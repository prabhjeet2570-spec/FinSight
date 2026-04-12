"""HTML extraction for SEC filings.

Parses an EDGAR HTML filing into:
  - Sections of narrative text, tagged with their SEC item name (MD&A, Risk
    Factors, etc.)
  - Tables (headers + rows) with the section they appeared in

Walks the DOM in document order. Section boundaries are detected by header
text matching the SEC "Item N." structure (see html_section_detector). Page
boundaries are inferred from CSS page-break elements — best-effort, since
HTML has no real page concept.

Output feeds into chunking.py (text → chunks) and metric_flattening.py
(tables → metrics rows, as a fallback when XBRL doesn't have a concept).
"""
import logging
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

from app.utils.html_section_detector import detect_section_from_header

logger = logging.getLogger(__name__)


@dataclass
class ExtractedSection:
    """A contiguous block of narrative text from one SEC filing section."""
    section: str | None              # Canonical SEC section name, or None
    text: str
    page_num: int                    # Synthetic page number from page-break count


@dataclass
class ExtractedTable:
    """A table parsed from HTML, ready to store in extracted_tables."""
    headers: list[str]
    rows: list[list[str]]            # Each row is a list of cell strings
    page_num: int
    section: str | None              # The section this table appeared in


@dataclass
class ExtractedDocument:
    """Output of html_extraction — ready for chunking + metric flattening."""
    sections: list[ExtractedSection] = field(default_factory=list)
    tables: list[ExtractedTable] = field(default_factory=list)
    page_count: int = 1


# Tags whose content we ignore entirely (not visible content)
_SKIP_TAGS = {"script", "style", "head", "meta", "link"}

# Min characters for a section to be worth keeping
_MIN_SECTION_LENGTH = 50

# Min cells in a row for a table row to be considered substantive
_MIN_ROW_CELLS = 2


def _is_page_break(elem: Tag) -> bool:
    """True if this element marks a visual page break (CSS or <hr>)."""
    if elem.name == "hr":
        return True
    style = elem.get("style", "")
    if isinstance(style, str) and "page-break" in style.lower():
        return True
    return False


def _normalize_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _table_to_rows(table: Tag) -> tuple[list[str], list[list[str]]]:
    """Extract a (headers, rows) tuple from a BeautifulSoup <table>.

    The first row containing <th> cells (or otherwise looking header-like)
    becomes the header row; everything else is a data row. Cell text is
    whitespace-normalized. Empty rows are dropped.
    """
    all_rows: list[list[str]] = []
    has_th_first = False
    header_idx: int | None = None

    for r_idx, tr in enumerate(table.find_all("tr")):
        cells = tr.find_all(["th", "td"])
        if not cells:
            continue
        row_text = [_normalize_whitespace(c.get_text(" ", strip=True)) for c in cells]
        # Drop completely empty rows
        if not any(row_text):
            continue
        if header_idx is None and any(c.name == "th" for c in cells):
            header_idx = len(all_rows)
            has_th_first = True
        all_rows.append(row_text)

    headers: list[str] = []
    rows: list[list[str]] = all_rows

    if has_th_first and header_idx is not None:
        headers = all_rows[header_idx]
        rows = all_rows[:header_idx] + all_rows[header_idx + 1:]

    # Drop rows with too few non-empty cells
    rows = [r for r in rows if sum(1 for c in r if c) >= _MIN_ROW_CELLS]

    return headers, rows


def extract_html(html: str) -> ExtractedDocument:
    """Parse a filing HTML into sections + tables.

    Args:
        html: raw filing HTML (UTF-8 string)

    Returns:
        ExtractedDocument with .sections (text per section), .tables, .page_count
    """
    soup = BeautifulSoup(html, "lxml")

    # Strip non-visible content
    for tag_name in _SKIP_TAGS:
        for t in soup.find_all(tag_name):
            t.decompose()

    body = soup.body or soup
    if body is None:
        return ExtractedDocument()

    sections: list[ExtractedSection] = []
    tables: list[ExtractedTable] = []
    current_section: str | None = None
    current_text: list[str] = []
    current_page = 1
    section_start_page = 1

    def flush_text() -> None:
        nonlocal current_text, section_start_page
        if not current_text:
            return
        joined = " ".join(current_text).strip()
        if len(joined) >= _MIN_SECTION_LENGTH:
            sections.append(ExtractedSection(
                section=current_section,
                text=joined,
                page_num=section_start_page,
            ))
        current_text = []
        section_start_page = current_page

    # Walk all descendants in document order
    for elem in body.descendants:
        if isinstance(elem, Tag):
            # Page break detection
            if _is_page_break(elem):
                current_page += 1
                continue

            # Tables: capture and skip their inner text walk by extracting
            # them inline. Note: descendants will still iterate inside the
            # table, but we'll skip text inside tables via a parent check.
            if elem.name == "table":
                headers, rows = _table_to_rows(elem)
                if rows:
                    tables.append(ExtractedTable(
                        headers=headers,
                        rows=rows,
                        page_num=current_page,
                        section=current_section,
                    ))
                continue

        elif isinstance(elem, NavigableString):
            # Skip text inside tables (we already captured them above)
            if elem.find_parent("table") is not None:
                continue
            text = str(elem).strip()
            if not text:
                continue

            # Section header check
            section_name = detect_section_from_header(text)
            if section_name is not None:
                flush_text()
                current_section = section_name
                continue

            current_text.append(_normalize_whitespace(text))

    flush_text()

    return ExtractedDocument(
        sections=sections,
        tables=tables,
        page_count=current_page,
    )
