"""XBRL fact extraction → metric rows.

Walks the XBRL_CONCEPT_MAP and queries the filing's XBRL fact store for
each canonical metric. The first concept in the preference list that
returns a non-dimensioned fact for the current period wins.

For each metric we find:
  - current period value
  - prior-year same-period value (Q1 2026 -> Q1 2025) for change_pct
  - the original us-gaap concept tag (for traceability)

Output: list of XbrlMetric records ready to insert into the metrics table
with source='xbrl'.

The edgartools XBRL object's facts query API is sync; we wrap the whole
extraction in asyncio.to_thread from the caller (filing_ingestion).
"""
import logging
from dataclasses import dataclass
from typing import Any

from app.finance.xbrl_concepts import XBRL_CONCEPT_MAP

logger = logging.getLogger(__name__)


@dataclass
class XbrlMetric:
    metric_name: str             # canonical e.g. 'revenue'
    value: float
    prior_value: float | None
    change_pct: float | None
    unit: str
    period: str | None           # period_key e.g. 'duration_2025-09-28_2025-12-27'
    prior_period: str | None
    xbrl_concept: str            # 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax'


def _query_facts_for_concept(xbrl: Any, concept: str) -> list[dict]:
    """Run facts.query().by_concept() and return non-dimensioned fact dicts.

    edgartools' by_concept() does substring matching (e.g. 'Assets' also
    matches 'AssetsCurrent'), so we filter to an exact local-name match
    against 'us-gaap:<concept>'. Dimensioned facts (revenue by product line)
    are also dropped — we only want the totals.
    """
    try:
        results = xbrl.facts.query().by_concept(concept).execute()
    except Exception as e:
        logger.debug(f"XBRL query failed for {concept}: {e}")
        return []
    if not results:
        return []
    target = f"us-gaap:{concept}"
    return [
        f for f in results
        if f.get("concept") == target and not f.get("is_dimensioned")
    ]


def _dedupe_by_period(facts: list[dict]) -> dict[str, dict]:
    """Collapse duplicate facts (same concept, same period) into one per period.

    XBRL filings often reference the same fact from multiple statements, so
    the query returns the same value 2-3x. Keyed by period_key.
    """
    by_period: dict[str, dict] = {}
    for f in facts:
        key = f.get("period_key")
        if not key:
            continue
        if key not in by_period:
            by_period[key] = f
    return by_period


def _pick_current_and_prior(by_period: dict[str, dict]) -> tuple[dict | None, dict | None]:
    """Choose the latest period (current) and the same-period prior year (prior).

    We prefer matching by (fiscal_period, fiscal_year) — Q1 2026's prior is
    Q1 2025. For balance sheet items (instant facts), we just take the two
    most recent dates.
    """
    if not by_period:
        return None, None

    facts = list(by_period.values())

    instants = [f for f in facts if f.get("period_type") == "instant"]
    durations = [f for f in facts if f.get("period_type") == "duration"]

    if durations:
        # Find latest by (fiscal_year, fiscal_period sort key)
        def _sort_key(f: dict) -> tuple:
            return (
                f.get("fiscal_year") or 0,
                _fiscal_period_order(f.get("fiscal_period")),
                f.get("period_end") or "",
            )
        durations.sort(key=_sort_key, reverse=True)
        current = durations[0]
        # Prior: same fiscal_period, fiscal_year - 1
        cur_fy = current.get("fiscal_year")
        cur_fp = current.get("fiscal_period")
        prior = None
        if cur_fy is not None:
            for f in durations[1:]:
                if f.get("fiscal_year") == cur_fy - 1 and f.get("fiscal_period") == cur_fp:
                    prior = f
                    break
        return current, prior

    if instants:
        instants.sort(key=lambda f: f.get("period_end") or "", reverse=True)
        current = instants[0]
        prior = instants[1] if len(instants) > 1 else None
        return current, prior

    return None, None


def _fiscal_period_order(fp: str | None) -> int:
    """Sort key for fiscal_period strings (Q1 < Q2 < Q3 < FY)."""
    if not fp:
        return 0
    order = {"Q1": 1, "Q2": 2, "Q3": 3, "Q4": 4, "FY": 5}
    return order.get(fp, 0)


def _format_period(fact: dict) -> str | None:
    """Build a human-readable period label from a fact's fiscal info."""
    fp = fact.get("fiscal_period")
    fy = fact.get("fiscal_year")
    if fp and fy:
        return f"{fp} {fy}"
    end = fact.get("period_end")
    if end:
        return str(end)
    return None


def extract_xbrl_metrics(xbrl: Any) -> list[XbrlMetric]:
    """Extract canonical metrics from an edgartools XBRL object.

    Returns one XbrlMetric per canonical metric for which we found a
    current-period fact. Metrics with no fact for the current period
    are simply omitted (HTML table fallback may fill them in).
    """
    if xbrl is None:
        return []

    metrics: list[XbrlMetric] = []

    for canonical, concept_list in XBRL_CONCEPT_MAP.items():
        for concept in concept_list:
            facts = _query_facts_for_concept(xbrl, concept)
            if not facts:
                continue

            by_period = _dedupe_by_period(facts)
            current, prior = _pick_current_and_prior(by_period)
            if current is None:
                continue

            cur_val = current.get("numeric_value")
            if cur_val is None:
                continue

            try:
                cur_val_f = float(cur_val)
            except (TypeError, ValueError):
                continue

            prior_val_f: float | None = None
            change_pct: float | None = None
            if prior is not None:
                pv = prior.get("numeric_value")
                if pv is not None:
                    try:
                        prior_val_f = float(pv)
                        if prior_val_f != 0:
                            change_pct = round(
                                (cur_val_f - prior_val_f) / abs(prior_val_f) * 100, 2
                            )
                    except (TypeError, ValueError):
                        pass

            unit = current.get("unit_ref") or "USD"
            unit = str(unit).upper()

            metrics.append(XbrlMetric(
                metric_name=canonical,
                value=cur_val_f,
                prior_value=prior_val_f,
                change_pct=change_pct,
                unit=unit,
                period=_format_period(current),
                prior_period=_format_period(prior) if prior else None,
                xbrl_concept=current.get("concept", concept),
            ))
            break  # First concept that hit wins; skip remaining concepts for this metric

    return metrics
