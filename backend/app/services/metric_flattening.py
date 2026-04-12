"""HTML table -> metric rows (XBRL fallback path).

When XBRL doesn't have a concept (some non-GAAP figures, smaller filers, or
older 8-Ks), we fall back to parsing the income statement / balance sheet /
cash flow tables ourselves.

The orchestrator passes the metrics already extracted from XBRL alongside the
HTML tables. We only emit a metric for canonical names that XBRL did not cover.

Heuristic:
  1. For each table row, treat the first non-empty cell as a label.
  2. Match the label against the synonym dictionary -> canonical metric name.
  3. Skip if XBRL already has that metric.
  4. Find the first numeric cell in the row -> current value.
  5. Find the second numeric cell -> prior_value (best-effort).
  6. Compute change_pct.

This is a fallback. XBRL is the preferred source — when it's available it
gives clean tagged values with unambiguous units and periods.
"""
import logging
import re
from dataclasses import dataclass

from app.finance.synonyms import match_metric
from app.services.html_extraction import ExtractedTable

logger = logging.getLogger(__name__)


@dataclass
class HtmlMetric:
    metric_name: str
    value: float
    prior_value: float | None
    change_pct: float | None
    unit: str
    page_num: int | None
    table_type: str | None


_NUMBER_RE = re.compile(r"^[\(\-]?[\$]?\s*[\d,]+(?:\.\d+)?\s*\)?%?$")


def _parse_number(cell: str) -> float | None:
    """Parse a financial table cell into a float, or None if not numeric.

    Handles: '$1,234', '1,234.5', '(1,234)' (negative in parens),
             '12.5%', '$ 1,234' (whitespace).
    """
    if not cell:
        return None
    s = cell.strip().replace(",", "").replace("$", "").replace(" ", "")
    if not s:
        return None
    is_negative_paren = s.startswith("(") and s.endswith(")")
    if is_negative_paren:
        s = s[1:-1]
    is_percent = s.endswith("%")
    if is_percent:
        s = s[:-1]
    try:
        val = float(s)
    except ValueError:
        return None
    if is_negative_paren:
        val = -val
    return val


def _find_label_and_numbers(row: list[str]) -> tuple[str, list[float]] | None:
    """Pick the row label (leftmost text) and all numeric cells (in order).

    Returns (label, [num1, num2, ...]) or None if the row has no usable label.
    """
    label = ""
    label_idx = -1
    for i, cell in enumerate(row):
        c = cell.strip()
        if c and not _NUMBER_RE.match(c.replace(" ", "")) and c not in {"$", "%"}:
            label = c
            label_idx = i
            break
    if not label:
        return None

    numbers: list[float] = []
    for cell in row[label_idx + 1:]:
        val = _parse_number(cell)
        if val is not None:
            numbers.append(val)

    return label, numbers


def flatten_html_tables(
    tables: list[ExtractedTable],
    skip_metrics: set[str] | None = None,
) -> list[HtmlMetric]:
    """Extract canonical metrics from HTML tables, skipping any in skip_metrics.

    Args:
        tables: ExtractedTable list from html_extraction
        skip_metrics: canonical metric names already covered by XBRL — don't
                      duplicate them from HTML tables. Pass None to extract all.

    Returns:
        List of HtmlMetric records ready to insert with source='html_table'.
    """
    skip = skip_metrics or set()
    seen: set[str] = set(skip)
    out: list[HtmlMetric] = []

    for table in tables:
        for row in table.rows:
            parsed = _find_label_and_numbers(row)
            if parsed is None:
                continue
            label, numbers = parsed
            if not numbers:
                continue

            canonical = match_metric(label)
            if canonical is None or canonical in seen:
                continue

            current = numbers[0]
            prior: float | None = numbers[1] if len(numbers) > 1 else None
            change_pct: float | None = None
            if prior is not None and prior != 0:
                change_pct = round((current - prior) / abs(prior) * 100, 2)

            out.append(HtmlMetric(
                metric_name=canonical,
                value=current,
                prior_value=prior,
                change_pct=change_pct,
                unit="USD",
                page_num=table.page_num,
                table_type=None,
            ))
            seen.add(canonical)

    return out
