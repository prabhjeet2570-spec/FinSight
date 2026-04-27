"""Inline-XBRL extraction and provenance-preserving, section-aware chunking."""

import hashlib
import re
from decimal import Decimal, InvalidOperation

from bs4 import BeautifulSoup

from app.contracts import Chunk, Fact, Filing

PARSER_VERSION = "ixbrl-sections-v1"
SECTION_NAMES = {
    "1": "Business",
    "1a": "Risk factors",
    "1b": "Unresolved staff comments",
    "1c": "Cybersecurity",
    "2": "Properties",
    "3": "Legal proceedings",
    "5": "Market information",
    "6": "Selected financial data",
    "7": "Management discussion",
    "7a": "Market risk",
    "8": "Financial statements",
    "9": "Accounting changes",
    "9a": "Controls and procedures",
    "9b": "Other information",
    "9c": "Foreign jurisdictions",
    "10": "Directors and governance",
    "11": "Executive compensation",
    "12": "Ownership",
    "13": "Related transactions",
    "14": "Accounting fees",
    "15": "Exhibits",
    "16": "Summary",
}


def stable_id(*parts):
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:24]


def tag_name(tag):
    return tag.name.lower().split(":")[-1]


def extract_facts(soup, filing):
    contexts, units = {}, {}
    for tag in soup.find_all(lambda t: tag_name(t) == "context"):

        def text_of(name, context=tag):
            el = context.find(lambda child: tag_name(child) == name)
            return el.get_text(strip=True) if el else None

        dims = {
            t.get("dimension", ""): t.get_text(strip=True)
            for t in tag.find_all(lambda t: tag_name(t) in ("explicitmember", "typedmember"))
        }
        contexts[tag.get("id")] = (
            text_of("startdate"),
            text_of("enddate") or text_of("instant"),
            dims,
        )
    for tag in soup.find_all(lambda t: tag_name(t) == "unit"):
        measures = [
            t.get_text(strip=True).split(":")[-1]
            for t in tag.find_all(lambda t: tag_name(t) == "measure")
        ]
        units[tag.get("id")] = "/".join(measures)
    facts, seen = [], set()
    for tag in soup.find_all(lambda t: tag_name(t) == "nonfraction"):
        context_id = tag.get("contextref", "")
        if context_id not in contexts or tag.get("xsi:nil") == "true":
            continue
        start, end, dims = contexts[context_id]
        if not end:
            continue
        # Supported numeric transformations only. Unknown/localized formats abstain.
        transform = str(tag.get("format", "")).lower().split(":")[-1]
        if transform not in (
            "",
            "num-dot-decimal",
            "numdotdecimal",
            "zero-dash",
            "zerodash",
            "num-dot-decimal-in",
            "fixed-zero",
        ):
            continue
        raw = (
            tag.get_text("", strip=True)
            .replace(",", "")
            .replace("$", "")
            .replace("\u00a0", "")
            .strip()
        )
        negative = tag.get("sign") == "-" or raw.startswith("(")
        raw = raw.strip("()")
        if raw in ("—", "–", "-", ""):
            if transform in ("zero-dash", "zerodash", "fixed-zero"):
                raw = "0"
            else:
                continue
        try:
            value = Decimal(raw) * Decimal(10) ** int(tag.get("scale", "0"))
            if negative:
                value = -abs(value)
        except (InvalidOperation, ValueError):
            continue
        concept = tag.get("name", "")
        unit = units.get(tag.get("unitref"), "")
        if not concept or not unit:
            continue
        fid = stable_id(filing.id, concept, unit, start, end, sorted(dims.items()), value)
        if fid in seen:
            continue
        try:
            fact = Fact(
                id=fid,
                filing_id=filing.id,
                concept=concept,
                value=value,
                unit=unit,
                start=start,
                end=end,
                decimals=str(tag.get("decimals", "INF")),
                context_id=context_id,
                dimensions=dims,
                source_anchor=tag.get("id"),
            )
        except ValueError:
            continue
        facts.append(fact)
        seen.add(fid)
    return facts


def parse_filing(html: str, filing: Filing):
    soup = BeautifulSoup(html, "html.parser")
    facts = extract_facts(soup, filing)
    for t in soup.find_all(
        lambda t: tag_name(t) in ("header", "hidden", "script", "style", "head")
    ):
        t.decompose()
    # Leaf blocks avoid repeating every nested div; tables stay intact before slicing.
    blocks = []
    section = "Overview"
    for node in soup.find_all(["p", "div", "table"]):
        if node.find_parent("table") or (node.name != "table" and node.find(["div", "p", "table"])):
            continue
        text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        if len(text) < 8:
            continue
        heading = re.match(r"^item\s+(\d{1,2}[abc]?)\s*[.:-]?\s+", text, re.IGNORECASE)
        # TOC entries contain dotted leaders/page numbers. Require a heading-like block.
        if heading and len(text) < 200 and not re.search(r"\.{3}|\s\d{1,3}\s*$", text):
            section = SECTION_NAMES.get(heading[1].lower(), section)
        anchor = node.get("id")
        if not anchor:
            parent = node.find_parent(id=True)
            anchor = parent.get("id") if parent else None
        blocks.append((section, text, anchor, "table" if node.name == "table" else "passage"))
    chunks, offset = [], 0
    for section, text, anchor, kind in blocks:
        # Small character windows leave headroom under the encoder's token limit.
        # Keep sentence boundaries where possible and record offsets into normalized blocks.
        start = 0
        while start < len(text):
            end = min(start + 700, len(text))
            if end < len(text):
                boundary = text.rfind(" ", start + 350, end)
                if boundary > start:
                    end = boundary
            passage = text[start:end].strip()
            if len(passage) >= 35:
                chunks.append(
                    Chunk(
                        id=stable_id(filing.id, PARSER_VERSION, offset + start, passage),
                        filing_id=filing.id,
                        section=section,
                        text=passage,
                        ordinal=len(chunks),
                        start_offset=offset + start,
                        end_offset=offset + end,
                        source_anchor=anchor,
                        kind=kind,
                    )
                )
            if end == len(text):
                break
            next_start = max(start + 1, end - 90)
            space = text.find(" ", next_start, end)
            start = space + 1 if space >= 0 else next_start
        offset += len(text) + 1
    if not chunks:
        raise ValueError("No supported filing text found")
    return chunks, facts
