"""Flatten extracted tables into a metrics table for fast SQL lookup.

Takes structured table rows and pulls out the key financial line items,
normalizing them to canonical metric names via the finance/synonyms.py
synonym dictionary.
"""
import logging
import re
from dataclasses import dataclass

from app.finance.synonyms import match_metric
from app.services.extraction import ExtractedTable

logger = logging.getLogger(__name__)


@dataclass
class FlatMetric:
    metric_name: str
    value: float | None
    prior_value: float | None
    change_pct: float | None
    unit: str
    period: str | None
    prior_period: str | None
    page_num: int
    table_type: str | None


# ---------- Number parsing ----------

NUMBER_CLEAN_RE = re.compile(r"[^\d.\-]")


def parse_number(s: str | None) -> float | None:
    """Parse a financial number string like '$1,234.5' or '(123)' to float."""
    if s is None:
        return None
    s = str(s).strip()
    if not s or s in {"-", "—", "N/A", "n/a"}:
        return None

    is_negative = False
    # Parentheses indicate negative in financial statements
    if s.startswith("(") and s.endswith(")"):
        is_negative = True
        s = s[1:-1]

    cleaned = NUMBER_CLEAN_RE.sub("", s)
    if not cleaned or cleaned in {".", "-", "-."}:
        return None

    try:
        val = float(cleaned)
        return -val if is_negative else val
    except ValueError:
        return None


def _match_metric(label: str) -> str | None:
    """Match a row label to a canonical metric name.

    Delegates to finance.synonyms.match_metric which has the full
    synonym dictionary (~48 canonical metrics).
    """
    return match_metric(label)


# ---------- Period detection ----------

def _classify_columns(headers: list[str]) -> tuple[int | None, int | None, str | None, str | None]:
    """Identify which column is current period vs prior period.

    Returns (current_idx, prior_idx, current_period, prior_period).
    """
    if not headers or len(headers) < 2:
        return None, None, None, None

    # Common patterns: "Three Months Ended ... 2025" / "... 2024"
    period_re = re.compile(r"(20\d{2})")

    column_periods: list[tuple[int, str]] = []
    for i, header in enumerate(headers):
        if not header:
            continue
        match = period_re.search(str(header))
        if match:
            column_periods.append((i, match.group(1)))

    if len(column_periods) >= 2:
        # Most recent year is "current"
        sorted_periods = sorted(column_periods, key=lambda x: x[1], reverse=True)
        return (
            sorted_periods[0][0],
            sorted_periods[1][0],
            sorted_periods[0][1],
            sorted_periods[1][1],
        )
    elif len(column_periods) == 1:
        return column_periods[0][0], None, column_periods[0][1], None

    # Fallback: use first non-label column as current
    return 1 if len(headers) > 1 else None, None, None, None


# ---------- Main flattening ----------

def flatten_tables(tables: list[ExtractedTable]) -> list[FlatMetric]:
    """Extract canonical metrics from a list of parsed tables."""
    metrics: list[FlatMetric] = []

    for table in tables:
        if not table.quality_ok:
            continue

        current_idx, prior_idx, current_period, prior_period = _classify_columns(table.headers)
        if current_idx is None:
            continue

        # Convert column index to header key (rows are dicts keyed by header name)
        value_keys = list(table.headers[1:])  # skip label column
        if not value_keys:
            continue

        current_key = table.headers[current_idx] if current_idx < len(table.headers) else None
        prior_key = table.headers[prior_idx] if prior_idx is not None and prior_idx < len(table.headers) else None

        for row in table.rows:
            label = row.get("label", "")
            metric_name = _match_metric(label)
            if not metric_name:
                continue

            values_dict = row.get("values", {})
            current_val = parse_number(values_dict.get(current_key)) if current_key else None
            prior_val = parse_number(values_dict.get(prior_key)) if prior_key else None

            change_pct = None
            if current_val is not None and prior_val is not None and prior_val != 0:
                change_pct = ((current_val - prior_val) / abs(prior_val)) * 100

            metrics.append(FlatMetric(
                metric_name=metric_name,
                value=current_val,
                prior_value=prior_val,
                change_pct=change_pct,
                unit="millions USD",  # Phase 3 will detect this from headers
                period=current_period,
                prior_period=prior_period,
                page_num=table.page_num,
                table_type=table.table_type,
            ))

    # Deduplicate: keep first occurrence of each (metric_name, period)
    seen = set()
    deduped = []
    for m in metrics:
        key = (m.metric_name, m.period)
        if key not in seen:
            seen.add(key)
            deduped.append(m)

    return deduped
