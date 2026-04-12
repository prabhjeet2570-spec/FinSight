"""US-GAAP XBRL concept tags → canonical metric names.

The XBRL extraction layer queries each concept in this map. The first one
that returns a fact for the current period wins (concepts are listed in
preference order — modern revenue recognition concepts before legacy ones).

These are the concept tags US-listed companies use under us-gaap:* in their
financial reports. The map covers the income statement, balance sheet, and
cash flow statement metrics referenced by the synonym dictionary.
"""

# Canonical metric name -> ordered list of us-gaap concepts to try.
# Local name only (no namespace prefix) — the XBRL fact dicts give us
# 'us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax' but the
# query API matches on the local name.
XBRL_CONCEPT_MAP: dict[str, list[str]] = {
    # ---------- Income Statement ----------
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "cost_of_revenue": [
        "CostOfGoodsAndServicesSold",
        "CostOfRevenue",
        "CostOfGoodsSold",
        "CostOfServices",
    ],
    "gross_profit": [
        "GrossProfit",
    ],
    "research_and_development": [
        "ResearchAndDevelopmentExpense",
    ],
    "selling_general_admin": [
        "SellingGeneralAndAdministrativeExpense",
    ],
    "operating_expenses": [
        "OperatingExpenses",
        "CostsAndExpenses",
    ],
    "operating_income": [
        "OperatingIncomeLoss",
    ],
    "interest_expense": [
        "InterestExpense",
    ],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
    ],
    "income_tax_expense": [
        "IncomeTaxExpenseBenefit",
    ],
    "net_income": [
        "NetIncomeLoss",
        "ProfitLoss",
    ],

    # ---------- Per-Share ----------
    "eps_basic": [
        "EarningsPerShareBasic",
    ],
    "eps_diluted": [
        "EarningsPerShareDiluted",
    ],
    "dividends_per_share": [
        "CommonStockDividendsPerShareDeclared",
        "CommonStockDividendsPerShareCashPaid",
    ],
    "shares_outstanding_basic": [
        "WeightedAverageNumberOfSharesOutstandingBasic",
    ],
    "shares_outstanding_diluted": [
        "WeightedAverageNumberOfDilutedSharesOutstanding",
    ],

    # ---------- Balance Sheet — Assets ----------
    "cash_and_equivalents": [
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
    ],
    "short_term_investments": [
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
    ],
    "accounts_receivable": [
        "AccountsReceivableNetCurrent",
    ],
    "inventories": [
        "InventoryNet",
    ],
    "current_assets": [
        "AssetsCurrent",
    ],
    "property_plant_equipment": [
        "PropertyPlantAndEquipmentNet",
    ],
    "goodwill": [
        "Goodwill",
    ],
    "intangible_assets": [
        "IntangibleAssetsNetExcludingGoodwill",
        "FiniteLivedIntangibleAssetsNet",
    ],
    "total_assets": [
        "Assets",
    ],

    # ---------- Balance Sheet — Liabilities ----------
    "accounts_payable": [
        "AccountsPayableCurrent",
    ],
    "short_term_debt": [
        "LongTermDebtCurrent",
        "ShortTermBorrowings",
        "CommercialPaper",
    ],
    "current_liabilities": [
        "LiabilitiesCurrent",
    ],
    "long_term_debt": [
        "LongTermDebtNoncurrent",
        "LongTermDebt",
    ],
    "total_liabilities": [
        "Liabilities",
    ],
    "stockholders_equity": [
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ],
    "retained_earnings": [
        "RetainedEarningsAccumulatedDeficit",
    ],

    # ---------- Cash Flow Statement ----------
    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
    ],
    "capital_expenditures": [
        "PaymentsToAcquirePropertyPlantAndEquipment",
    ],
    "investing_cash_flow": [
        "NetCashProvidedByUsedInInvestingActivities",
    ],
    "financing_cash_flow": [
        "NetCashProvidedByUsedInFinancingActivities",
    ],
    "depreciation_amortization": [
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "Depreciation",
    ],
    "stock_based_compensation": [
        "ShareBasedCompensation",
    ],
    "dividends_paid": [
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
    ],
    "share_repurchases": [
        "PaymentsForRepurchaseOfCommonStock",
    ],
}


def all_concepts() -> list[tuple[str, str]]:
    """Flatten the map to (canonical_metric, concept_name) pairs."""
    return [
        (metric, concept)
        for metric, concepts in XBRL_CONCEPT_MAP.items()
        for concept in concepts
    ]
