"""Query classifier using Gemini Flash.

Takes a user question and classifies it into a query type, extracts
target metric names, and identifies any financial jargon. This drives
the retrieval routing — NUMERICAL questions go to structured SQL,
NARRATIVE questions go to vector search, MIXED uses both.

Uses few-shot prompting with Gemini 2.0 Flash (free tier: 15 RPM).
"""
import json
import logging

from google import genai

from app.config import get_settings
from app.finance.jargon import resolve_jargon, is_special_concept, get_special_concept

logger = logging.getLogger(__name__)

QUERY_TYPES = {"NUMERICAL", "NARRATIVE", "MIXED", "SENTIMENT"}

CLASSIFIER_PROMPT = """\
You are a financial query classifier for a document analysis system.
The user has uploaded SEC filings (10-Q, 10-K) and is asking questions about them.

Classify the query and extract structured information.

## Query Types

- NUMERICAL: Asks for specific numbers, metrics, or ratios.
  Examples: "What was revenue?", "What's the gross margin?", "How much debt?"
- NARRATIVE: Asks about qualitative information, management commentary, risks, strategy.
  Examples: "What did management say about AI?", "What are the risk factors?", "What's the outlook?"
- MIXED: Needs both numbers AND narrative context.
  Examples: "Why did revenue decline?", "What drove margin expansion?", "How is the business performing?"
- SENTIMENT: Asks about outlook, tone, or directional assessment.
  Examples: "Is the outlook positive?", "How confident is management?", "What's the overall sentiment?"

## Output Format

Return ONLY valid JSON (no markdown, no backticks):
{
  "query_type": "NUMERICAL|NARRATIVE|MIXED|SENTIMENT",
  "metrics": ["list of canonical metric names the question is about"],
  "section_hint": "MD&A|Risk Factors|Financial Statements|Notes|null",
  "reasoning": "one sentence explaining classification"
}

## Canonical Metric Names

Use these exact names when the question references financial metrics:
revenue, cost_of_revenue, gross_profit, operating_income, net_income,
eps_basic, eps_diluted, ebitda, operating_expenses,
research_and_development, selling_general_admin,
cash_and_equivalents, accounts_receivable, inventories,
current_assets, total_assets, accounts_payable, current_liabilities,
long_term_debt, total_debt, total_liabilities, stockholders_equity,
operating_cash_flow, capital_expenditures, free_cash_flow,
depreciation_amortization, stock_based_compensation,
dividends_per_share, dividends_paid, share_repurchases

## Examples

User: "What was Apple's revenue last quarter?"
{"query_type": "NUMERICAL", "metrics": ["revenue"], "section_hint": "Financial Statements", "reasoning": "Asks for a specific financial metric"}

User: "What are the main risk factors?"
{"query_type": "NARRATIVE", "metrics": [], "section_hint": "Risk Factors", "reasoning": "Asks about qualitative risk discussion"}

User: "Why did gross margin improve?"
{"query_type": "MIXED", "metrics": ["gross_profit", "revenue", "cost_of_revenue"], "section_hint": "MD&A", "reasoning": "Asks for margin metric AND explanation of the change"}

User: "Is management optimistic about next year?"
{"query_type": "SENTIMENT", "metrics": [], "section_hint": "MD&A", "reasoning": "Asks about management tone and outlook"}

User: "What's the debt situation?"
{"query_type": "NUMERICAL", "metrics": ["total_debt", "long_term_debt", "current_liabilities", "stockholders_equity"], "section_hint": "Financial Statements", "reasoning": "Asks about debt metrics and leverage"}

User: "How much is the company spending on R&D and why?"
{"query_type": "MIXED", "metrics": ["research_and_development", "revenue"], "section_hint": "MD&A", "reasoning": "Asks for R&D spending figure AND strategic reasoning"}

User: "What's the bottom line?"
{"query_type": "NUMERICAL", "metrics": ["net_income"], "section_hint": "Financial Statements", "reasoning": "Financial jargon for net income"}

Now classify this query:
"""


def _get_client() -> genai.Client:
    settings = get_settings()
    return genai.Client(api_key=settings.gemini_api_key)


def _parse_classifier_response(text: str) -> dict:
    """Parse the JSON response from Gemini, handling common formatting issues."""
    text = text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[: text.rfind("```")]
    text = text.strip()
    if text.startswith("json"):
        text = text[4:].strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        logger.warning(f"Failed to parse classifier response: {text[:200]}")
        return {
            "query_type": "MIXED",
            "metrics": [],
            "section_hint": None,
            "reasoning": "Failed to parse classifier output — defaulting to MIXED",
        }

    # Validate query_type
    if result.get("query_type") not in QUERY_TYPES:
        result["query_type"] = "MIXED"
    result.setdefault("metrics", [])
    result.setdefault("section_hint", None)
    result.setdefault("reasoning", "")

    return result


def _apply_jargon_resolution(question: str, classification: dict) -> dict:
    """Enrich classification with jargon resolution results.

    Scans the question for known financial jargon and adds the resolved
    canonical metrics / special concepts to the classification.
    """
    words = question.lower()
    resolved_metrics: list[str] = list(classification.get("metrics", []))
    ratios_needed: list[str] = []

    # Check each jargon term against the question text
    from app.finance.jargon import JARGON_MAP
    for jargon_term, canonical in JARGON_MAP.items():
        if jargon_term in words:
            if is_special_concept(canonical):
                concept = get_special_concept(canonical)
                if concept:
                    for m in concept["metrics"]:
                        if m not in resolved_metrics:
                            resolved_metrics.append(m)
                    ratios_needed.extend(concept.get("ratios", []))
            else:
                if canonical not in resolved_metrics:
                    resolved_metrics.append(canonical)

    classification["metrics"] = resolved_metrics
    if ratios_needed:
        classification["ratios_needed"] = list(set(ratios_needed))

    return classification


async def classify_query(question: str) -> dict:
    """Classify a user question using Gemini Flash + jargon resolution.

    Returns dict with keys:
        query_type: NUMERICAL | NARRATIVE | MIXED | SENTIMENT
        metrics: list of canonical metric names
        section_hint: suggested SEC filing section or None
        ratios_needed: list of ratio names to compute (if jargon triggered)
        reasoning: one-sentence explanation
    """
    client = _get_client()

    prompt = CLASSIFIER_PROMPT + f'User: "{question}"'

    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        classification = _parse_classifier_response(response.text)
    except Exception as e:
        logger.error(f"Gemini classifier call failed: {e}")
        classification = {
            "query_type": "MIXED",
            "metrics": [],
            "section_hint": None,
            "reasoning": f"Classifier error: {e}",
        }

    # Enrich with jargon resolution
    classification = _apply_jargon_resolution(question, classification)

    logger.info(
        f"Classified query: type={classification['query_type']}, "
        f"metrics={classification['metrics']}, "
        f"section={classification.get('section_hint')}"
    )

    return classification
