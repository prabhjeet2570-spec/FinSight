"""Map SEC filing section header text to canonical section names.

SEC filings (10-Q/10-K) use a fixed item structure:
  Part I:  Item 1 (Financial Statements), Item 2 (MD&A),
           Item 3 (Quantitative Disclosures), Item 4 (Controls)
  Part II: Item 1 (Legal), Item 1A (Risk Factors), Item 2 (Unregistered Sales),
           Item 5 (Other), Item 6 (Exhibits)

The HTML extractor walks the document and uses these matchers to identify
section boundaries. Each matcher takes a line of header text and returns a
canonical section name (or None).
"""
import re

# Regex matches the "Item N." or "Item NA." prefix at the start of a line.
# Captures the item number (with optional letter suffix like "1A").
ITEM_PREFIX = re.compile(
    r"^\s*item\s+(\d+[a-z]?)\s*\.?\s*(.*?)$",
    re.IGNORECASE,
)

# Map (item_number_lower) -> canonical section name.
# Where the item number alone is ambiguous (Item 1, Item 2 mean different things
# in Part I vs Part II), the title text disambiguates.
ITEM_TITLE_MAP: list[tuple[re.Pattern, str]] = [
    # 10-Q Part I
    (re.compile(r"financial\s+statements", re.I),                       "Financial Statements"),
    (re.compile(r"management.*discussion.*analysis", re.I),             "MD&A"),
    (re.compile(r"quantitative\s+and\s+qualitative\s+disclosures", re.I), "Quantitative Disclosures"),
    (re.compile(r"controls\s+and\s+procedures", re.I),                  "Controls and Procedures"),
    # 10-Q / 10-K Part II
    (re.compile(r"legal\s+proceedings", re.I),                          "Legal Proceedings"),
    (re.compile(r"risk\s+factors", re.I),                               "Risk Factors"),
    (re.compile(r"unregistered\s+sales", re.I),                         "Unregistered Sales"),
    (re.compile(r"defaults\s+upon\s+senior\s+securities", re.I),        "Defaults on Senior Securities"),
    (re.compile(r"mine\s+safety\s+disclosures", re.I),                  "Mine Safety Disclosures"),
    (re.compile(r"other\s+information", re.I),                          "Other Information"),
    (re.compile(r"exhibits", re.I),                                     "Exhibits"),
    # 10-K only
    (re.compile(r"^business$|^business\s*$", re.I),                     "Business"),
    (re.compile(r"unresolved\s+staff\s+comments", re.I),                "Unresolved Staff Comments"),
    (re.compile(r"properties", re.I),                                   "Properties"),
    (re.compile(r"market\s+for\s+registrant", re.I),                    "Market for Common Equity"),
    (re.compile(r"selected\s+financial\s+data", re.I),                  "Selected Financial Data"),
    (re.compile(r"financial\s+statements\s+and\s+supplementary", re.I), "Financial Statements"),
    (re.compile(r"changes\s+in\s+and\s+disagreements\s+with\s+accountants", re.I), "Accountant Disagreements"),
    (re.compile(r"directors|executive\s+officers", re.I),               "Directors and Officers"),
    (re.compile(r"executive\s+compensation", re.I),                     "Executive Compensation"),
    (re.compile(r"security\s+ownership", re.I),                         "Security Ownership"),
    (re.compile(r"certain\s+relationships", re.I),                      "Related Party Transactions"),
    (re.compile(r"principal\s+account(?:ant|ing)\s+fees", re.I),        "Accountant Fees"),
]


def detect_section_from_header(text: str) -> str | None:
    """Identify the canonical SEC section name from header text.

    Returns None if the text doesn't look like a section header.
    Examples:
      "Item 2. Management's Discussion and Analysis..." -> "MD&A"
      "Item 1A. Risk Factors"                            -> "Risk Factors"
      "Total revenue"                                    -> None
    """
    if not text:
        return None
    text = text.strip()
    if len(text) > 200:
        return None  # Headers are short

    m = ITEM_PREFIX.match(text)
    if m:
        title = m.group(2).strip()
        for pattern, canonical in ITEM_TITLE_MAP:
            if pattern.search(title):
                return canonical
        return None

    # Headers without "Item N." prefix (10-K business description style)
    for pattern, canonical in ITEM_TITLE_MAP:
        if pattern.fullmatch(text):
            return canonical

    return None


def is_likely_header(text: str) -> bool:
    """Quick check whether a line of text could be a section header at all.

    Used to skip detect_section_from_header on long paragraphs.
    """
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) > 200 or len(stripped) < 4:
        return False
    return bool(ITEM_PREFIX.match(stripped))
