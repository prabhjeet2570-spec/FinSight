import re

# SEC filing section patterns — ordered by specificity
SECTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("Risk Factors", re.compile(
        r"(?:PART\s+II\s*[-—]?\s*)?ITEM\s+1A[\.\s\-—:]+RISK\s+FACTORS",
        re.IGNORECASE,
    )),
    ("Legal Proceedings", re.compile(
        r"(?:PART\s+II\s*[-—]?\s*)?ITEM\s+1[\.\s\-—:]+LEGAL\s+PROCEEDINGS",
        re.IGNORECASE,
    )),
    ("Financial Statements", re.compile(
        r"ITEM\s+1[\.\s\-—:]+FINANCIAL\s+STATEMENTS",
        re.IGNORECASE,
    )),
    ("MD&A", re.compile(
        r"ITEM\s+2[\.\s\-—:]+MANAGEMENT[''']?S?\s+DISCUSSION\s+AND\s+ANALYSIS",
        re.IGNORECASE,
    )),
    ("Quantitative Disclosures", re.compile(
        r"ITEM\s+3[\.\s\-—:]+QUANTITATIVE\s+AND\s+QUALITATIVE\s+DISCLOSURES",
        re.IGNORECASE,
    )),
    ("Controls and Procedures", re.compile(
        r"ITEM\s+4[\.\s\-—:]+CONTROLS\s+AND\s+PROCEDURES",
        re.IGNORECASE,
    )),
    ("Risk Factors", re.compile(
        r"RISK\s+FACTORS",
        re.IGNORECASE,
    )),
    ("MD&A", re.compile(
        r"MANAGEMENT[''']?S?\s+DISCUSSION\s+AND\s+ANALYSIS",
        re.IGNORECASE,
    )),
    ("Notes to Financial Statements", re.compile(
        r"NOTES\s+TO\s+(?:CONDENSED\s+)?(?:CONSOLIDATED\s+)?FINANCIAL\s+STATEMENTS",
        re.IGNORECASE,
    )),
]


def detect_section(text: str) -> str | None:
    """Detect which SEC filing section a chunk of text belongs to.

    Scans the first ~500 chars for section header patterns.
    Returns the section name or None if no match.
    """
    header = text[:500]
    for section_name, pattern in SECTION_PATTERNS:
        if pattern.search(header):
            return section_name
    return None


def detect_section_for_page(page_text: str, current_section: str | None) -> str | None:
    """Detect section for a full page of text.

    If a new section header is found, return that section.
    Otherwise, carry forward the current section (pages within a section
    don't repeat the header).
    """
    detected = detect_section(page_text)
    return detected if detected else current_section
