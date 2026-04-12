"""Computable financial ratio definitions.

Standard financial ratios computed from extracted metrics. When a user
asks "what's the gross margin?", we don't ask the LLM — we look up
gross_profit and revenue, compute the ratio, and present the result.

Each ratio definition specifies:
  - numerator/denominator metric names (must match canonical names from synonyms.py)
  - display format (percentage, ratio, currency, etc.)
  - how to interpret the result
"""
from dataclasses import dataclass


@dataclass
class RatioDefinition:
    name: str
    display_name: str
    numerator: str           # canonical metric name
    denominator: str         # canonical metric name
    format: str              # "percentage", "ratio", "currency", "multiple"
    description: str
    invert_is_better: bool = False  # True if lower is better (e.g., debt ratios)


@dataclass
class ComputedRatio:
    name: str
    display_name: str
    value: float | None
    prior_value: float | None
    change_pct: float | None
    format: str
    description: str


# ---------- Ratio definitions ----------

RATIO_DEFINITIONS: dict[str, RatioDefinition] = {
    # Profitability
    "gross_margin": RatioDefinition(
        name="gross_margin",
        display_name="Gross Margin",
        numerator="gross_profit",
        denominator="revenue",
        format="percentage",
        description="Percentage of revenue retained after cost of goods sold",
    ),
    "operating_margin": RatioDefinition(
        name="operating_margin",
        display_name="Operating Margin",
        numerator="operating_income",
        denominator="revenue",
        format="percentage",
        description="Percentage of revenue retained after operating expenses",
    ),
    "net_margin": RatioDefinition(
        name="net_margin",
        display_name="Net Margin",
        numerator="net_income",
        denominator="revenue",
        format="percentage",
        description="Percentage of revenue retained as net profit",
    ),
    "r_and_d_margin": RatioDefinition(
        name="r_and_d_margin",
        display_name="R&D as % of Revenue",
        numerator="research_and_development",
        denominator="revenue",
        format="percentage",
        description="R&D spending as a percentage of revenue",
    ),
    "sga_margin": RatioDefinition(
        name="sga_margin",
        display_name="SG&A as % of Revenue",
        numerator="selling_general_admin",
        denominator="revenue",
        format="percentage",
        description="SG&A spending as a percentage of revenue",
    ),

    # Leverage
    "debt_to_equity": RatioDefinition(
        name="debt_to_equity",
        display_name="Debt-to-Equity",
        numerator="total_debt",
        denominator="stockholders_equity",
        format="ratio",
        description="Total debt relative to shareholders' equity",
        invert_is_better=True,
    ),
    "debt_to_assets": RatioDefinition(
        name="debt_to_assets",
        display_name="Debt-to-Assets",
        numerator="total_liabilities",
        denominator="total_assets",
        format="ratio",
        description="Total liabilities relative to total assets",
        invert_is_better=True,
    ),
    "equity_ratio": RatioDefinition(
        name="equity_ratio",
        display_name="Equity Ratio",
        numerator="stockholders_equity",
        denominator="total_assets",
        format="percentage",
        description="Shareholders' equity as a percentage of total assets",
    ),

    # Liquidity
    "current_ratio": RatioDefinition(
        name="current_ratio",
        display_name="Current Ratio",
        numerator="current_assets",
        denominator="current_liabilities",
        format="ratio",
        description="Ability to pay short-term obligations (>1.0 is healthy)",
    ),

    # Efficiency
    "asset_turnover": RatioDefinition(
        name="asset_turnover",
        display_name="Asset Turnover",
        numerator="revenue",
        denominator="total_assets",
        format="ratio",
        description="Revenue generated per dollar of assets",
    ),

    # Cash flow
    "operating_cash_flow_margin": RatioDefinition(
        name="operating_cash_flow_margin",
        display_name="Operating Cash Flow Margin",
        numerator="operating_cash_flow",
        denominator="revenue",
        format="percentage",
        description="Cash generated from operations as percentage of revenue",
    ),
    "capex_to_revenue": RatioDefinition(
        name="capex_to_revenue",
        display_name="Capex as % of Revenue",
        numerator="capital_expenditures",
        denominator="revenue",
        format="percentage",
        description="Capital spending intensity relative to revenue",
    ),
    "fcf_margin": RatioDefinition(
        name="fcf_margin",
        display_name="Free Cash Flow Margin",
        numerator="free_cash_flow",
        denominator="revenue",
        format="percentage",
        description="Free cash flow as a percentage of revenue",
    ),

    # Returns
    "return_on_equity": RatioDefinition(
        name="return_on_equity",
        display_name="Return on Equity (ROE)",
        numerator="net_income",
        denominator="stockholders_equity",
        format="percentage",
        description="Net income as a percentage of shareholders' equity",
    ),
    "return_on_assets": RatioDefinition(
        name="return_on_assets",
        display_name="Return on Assets (ROA)",
        numerator="net_income",
        denominator="total_assets",
        format="percentage",
        description="Net income as a percentage of total assets",
    ),

    # Growth (special — uses change_pct from the metric itself)
    "revenue_growth": RatioDefinition(
        name="revenue_growth",
        display_name="Revenue Growth (YoY)",
        numerator="revenue",
        denominator="revenue",  # signals: use change_pct from the metric
        format="percentage",
        description="Year-over-year revenue growth rate",
    ),
    "earnings_growth": RatioDefinition(
        name="earnings_growth",
        display_name="Earnings Growth (YoY)",
        numerator="net_income",
        denominator="net_income",
        format="percentage",
        description="Year-over-year net income growth rate",
    ),
}

RATIO_COUNT = len(RATIO_DEFINITIONS)


def compute_ratio(
    ratio_name: str,
    metrics: dict[str, "tuple[float | None, float | None]"],
) -> ComputedRatio | None:
    """Compute a financial ratio from available metrics.

    Args:
        ratio_name: key from RATIO_DEFINITIONS
        metrics: dict mapping canonical metric name -> (current_value, prior_value)

    Returns ComputedRatio or None if required metrics are missing.
    """
    defn = RATIO_DEFINITIONS.get(ratio_name)
    if not defn:
        return None

    # Growth ratios are special — they use the metric's own change_pct
    if defn.numerator == defn.denominator:
        current, prior = metrics.get(defn.numerator, (None, None))
        if current is None:
            return None
        if prior is not None and prior != 0:
            value = ((current - prior) / abs(prior)) * 100
        else:
            value = None
        return ComputedRatio(
            name=defn.name,
            display_name=defn.display_name,
            value=value,
            prior_value=None,
            change_pct=None,
            format=defn.format,
            description=defn.description,
        )

    # Standard ratio: numerator / denominator
    num_current, num_prior = metrics.get(defn.numerator, (None, None))
    den_current, den_prior = metrics.get(defn.denominator, (None, None))

    if num_current is None or den_current is None or den_current == 0:
        return None

    current_value = num_current / den_current
    if defn.format == "percentage":
        current_value *= 100

    prior_value = None
    if num_prior is not None and den_prior is not None and den_prior != 0:
        prior_value = num_prior / den_prior
        if defn.format == "percentage":
            prior_value *= 100

    change_pct = None
    if current_value is not None and prior_value is not None and prior_value != 0:
        change_pct = ((current_value - prior_value) / abs(prior_value)) * 100

    return ComputedRatio(
        name=defn.name,
        display_name=defn.display_name,
        value=round(current_value, 2),
        prior_value=round(prior_value, 2) if prior_value is not None else None,
        change_pct=round(change_pct, 2) if change_pct is not None else None,
        format=defn.format,
        description=defn.description,
    )


def compute_all_ratios(
    metrics: dict[str, "tuple[float | None, float | None]"],
) -> list[ComputedRatio]:
    """Compute all possible ratios from the available metrics."""
    results = []
    for ratio_name in RATIO_DEFINITIONS:
        computed = compute_ratio(ratio_name, metrics)
        if computed is not None and computed.value is not None:
            results.append(computed)
    return results
