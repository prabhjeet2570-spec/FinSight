from decimal import Decimal

import pytest
from app.contracts import Fact
from app.financial import Unsupported, comparable, numeric_intent, selected_fact


def fact(
    value="100",
    concept="us-gaap:Revenues",
    start="2024-01-01",
    end="2024-12-31",
    unit="USD",
    dims=None,
):
    return Fact(
        id=value + concept,
        filing_id="f",
        concept=concept,
        value=Decimal(value),
        unit=unit,
        start=start,
        end=end,
        decimals="0",
        context_id="c",
        dimensions=dims or {},
    )


def test_annual_selection_excludes_ytd_and_segments():
    quarter = fact("20", start="2024-10-01")
    segment = fact("50", dims={"Region": "US"})
    annual = fact("100")
    assert selected_fact([quarter, segment, annual], "revenue", 2024) == annual


def test_conflicts_are_visible_and_units_not_guessed():
    with pytest.raises(Unsupported, match="Conflicting"):
        selected_fact([fact("100"), fact("101")], "revenue", 2024)
    with pytest.raises(Unsupported, match="no supported"):
        selected_fact([fact(unit="shares")], "revenue", 2024)


def test_margin_zero_denominator_period_mismatch_and_precision():
    with pytest.raises(Unsupported, match="zero"):
        comparable(fact("1"), fact("0"))
    with pytest.raises(Unsupported, match="same reporting"):
        comparable(fact("1"), fact("10", start="2023-01-01", end="2023-12-31"))
    assert Decimal(1) / Decimal(3) * 100 != Decimal("33.33")


def test_growth_duration_and_adjacency():
    comparable(fact(), fact("90", start="2023-01-01", end="2023-12-31"), growth=True)
    with pytest.raises(Unsupported, match="adjacent"):
        comparable(fact(), fact("90", start="2022-01-01", end="2022-12-31"), growth=True)


def test_narrative_risks_do_not_turn_into_numeric_lookup():
    assert numeric_intent("What risks could affect Apple revenue?") == ([], [])
    assert numeric_intent("Compare operating margin")[1] == ["operating_margin"]
