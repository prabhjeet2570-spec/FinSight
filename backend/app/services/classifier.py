"""Query classifier using Groq (Llama 3.3 70B).

Takes a user question and classifies it into a query type, extracts
target metric names, and identifies any financial jargon. This drives
the retrieval routing — NUMERICAL questions go to structured SQL,
NARRATIVE questions go to vector search, MIXED uses both.

Uses few-shot prompting with Llama 3.3 70B via Groq's OpenAI-compatible API.
"""
import asyncio
import json
import logging

from openai import AsyncOpenAI, RateLimitError

from app.config import get_settings
from app.finance.jargon import resolve_jargon, is_special_concept, get_special_concept

logger = logging.getLogger(__name__)

QUERY_TYPES = {"NUMERICAL", "NARRATIVE", "MIXED", "SENTIMENT"}

CLASSIFIER_PROMPT = """\
You are a financial query classifier for FinSight, an SEC filings analysis system.
The user asks questions about US public companies. The system fetches the relevant
filings from SEC EDGAR on demand.

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

## Company Extraction

You MUST also extract the US public companies the question is about. Output them as
their stock ticker symbols (uppercase) — you know them. Examples:
  - "Apple" -> "AAPL"
  - "Microsoft" -> "MSFT"
  - "Google" / "Alphabet" -> "GOOGL"
  - "Meta" / "Facebook" -> "META"
  - "NVIDIA" -> "NVDA"
  - "Tesla" -> "TSLA"
  - "Berkshire Hathaway" -> "BRK-B"
If the user already wrote a ticker (e.g. "AAPL"), pass it through unchanged.
If the question mentions multiple companies (comparison), include all of them.
If no specific public company is mentioned, return an empty list.

## Filing Strategy

You MUST also decide which SEC filings are needed to answer the question.
Output a `filings_needed` array — each entry has a `form` (filing type) and
`count` (how many of that type, most recent first).

Rules of thumb:
- Latest snapshot / single-quarter question -> [{"form": "10-Q", "count": 1}]
- Annual overview, risk factors, business description -> [{"form": "10-K", "count": 1}]
- Trend / growth / YoY / multi-period -> [{"form": "10-Q", "count": 4}] (or add a 10-K)
- Recent news / events -> [{"form": "8-K", "count": 5}]
- Mix of narrative + numbers -> combine, e.g. [{"form": "10-K", "count": 1}, {"form": "10-Q", "count": 1}]
- When unsure, default to [{"form": "10-Q", "count": 1}]

## Output Format

Return ONLY valid JSON (no markdown, no backticks):
{
  "query_type": "NUMERICAL|NARRATIVE|MIXED|SENTIMENT",
  "companies": ["TICKER1", "TICKER2"],
  "metrics": ["list of canonical metric names the question is about"],
  "section_hint": "MD&A|Risk Factors|Financial Statements|Notes|null",
  "filings_needed": [{"form": "10-Q|10-K|8-K", "count": 1}],
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
{"query_type": "NUMERICAL", "companies": ["AAPL"], "metrics": ["revenue"], "section_hint": "Financial Statements", "filings_needed": [{"form": "10-Q", "count": 1}], "reasoning": "Asks for a specific financial metric from the latest quarter"}

User: "What are NVIDIA's main risk factors?"
{"query_type": "NARRATIVE", "companies": ["NVDA"], "metrics": [], "section_hint": "Risk Factors", "filings_needed": [{"form": "10-K", "count": 1}], "reasoning": "Risk factors are detailed in the annual 10-K filing"}

User: "Why did Microsoft's gross margin improve?"
{"query_type": "MIXED", "companies": ["MSFT"], "metrics": ["gross_profit", "revenue", "cost_of_revenue"], "section_hint": "MD&A", "filings_needed": [{"form": "10-Q", "count": 1}], "reasoning": "Asks for margin metric AND explanation from the latest quarter"}

User: "Is Tesla management optimistic about next year?"
{"query_type": "SENTIMENT", "companies": ["TSLA"], "metrics": [], "section_hint": "MD&A", "filings_needed": [{"form": "10-Q", "count": 1}], "reasoning": "Management outlook is in the latest quarterly MD&A"}

User: "How is Apple's revenue trending over the past year?"
{"query_type": "NUMERICAL", "companies": ["AAPL"], "metrics": ["revenue"], "section_hint": "Financial Statements", "filings_needed": [{"form": "10-Q", "count": 4}], "reasoning": "Trend question needs multiple quarters to show the trajectory"}

User: "Compare Microsoft and Google operating margins"
{"query_type": "NUMERICAL", "companies": ["MSFT", "GOOGL"], "metrics": ["operating_income", "revenue"], "section_hint": "Financial Statements", "filings_needed": [{"form": "10-Q", "count": 1}], "reasoning": "Cross-company comparison using latest quarterly data for each"}

User: "What did Meta say about AI in their last 10-Q?"
{"query_type": "NARRATIVE", "companies": ["META"], "metrics": [], "section_hint": "MD&A", "filings_needed": [{"form": "10-Q", "count": 1}], "reasoning": "Qualitative question about Meta's AI commentary in their latest 10-Q"}

User: "What's Tesla's business overview and latest earnings?"
{"query_type": "MIXED", "companies": ["TSLA"], "metrics": ["revenue", "net_income", "eps_diluted"], "section_hint": null, "filings_needed": [{"form": "10-K", "count": 1}, {"form": "10-Q", "count": 1}], "reasoning": "Business overview is in 10-K, latest earnings in recent 10-Q — need both"}

User: "Any recent news about NVIDIA?"
{"query_type": "NARRATIVE", "companies": ["NVDA"], "metrics": [], "section_hint": null, "filings_needed": [{"form": "8-K", "count": 5}], "reasoning": "Recent events and news are reported in 8-K filings"}

User: "How is AMZN's bottom line?"
{"query_type": "NUMERICAL", "companies": ["AMZN"], "metrics": ["net_income"], "section_hint": "Financial Statements", "filings_needed": [{"form": "10-Q", "count": 1}], "reasoning": "Bottom line is jargon for net income, latest quarter"}

User: "How is the economy doing?"
{"query_type": "NARRATIVE", "companies": [], "metrics": [], "section_hint": null, "filings_needed": [], "reasoning": "No specific public company mentioned"}

Now classify this query:
"""


def _get_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )


def _parse_classifier_response(text: str) -> dict:
    """Parse the JSON response from the LLM, handling common formatting issues."""
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
            "companies": [],
            "metrics": [],
            "section_hint": None,
            "reasoning": "Failed to parse classifier output — defaulting to MIXED",
        }

    # Validate query_type
    if result.get("query_type") not in QUERY_TYPES:
        result["query_type"] = "MIXED"
    result.setdefault("companies", [])
    result.setdefault("metrics", [])
    result.setdefault("section_hint", None)
    result.setdefault("reasoning", "")

    # Validate filings_needed — default to one 10-Q if missing/malformed
    filings_needed = result.get("filings_needed")
    if not isinstance(filings_needed, list):
        filings_needed = [{"form": "10-Q", "count": 1}]
    validated: list[dict] = []
    for entry in filings_needed:
        if isinstance(entry, dict) and "form" in entry:
            form = str(entry["form"]).upper()
            count = int(entry.get("count", 1))
            count = max(1, min(count, 10))
            validated.append({"form": form, "count": count})
    result["filings_needed"] = validated if validated else [{"form": "10-Q", "count": 1}]

    # Normalize tickers — strip whitespace, uppercase, drop empty
    companies = result.get("companies") or []
    if isinstance(companies, str):
        companies = [companies]
    result["companies"] = [
        str(c).strip().upper() for c in companies if c and str(c).strip()
    ]

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
    """Classify a user question using Llama 3.3 70B (Groq) + jargon resolution.

    Returns dict with keys:
        query_type: NUMERICAL | NARRATIVE | MIXED | SENTIMENT
        metrics: list of canonical metric names
        section_hint: suggested SEC filing section or None
        ratios_needed: list of ratio names to compute (if jargon triggered)
        reasoning: one-sentence explanation
    """
    client = _get_client()

    prompt = CLASSIFIER_PROMPT + f'User: "{question}"'

    classification = None
    for attempt in range(3):
        try:
            response = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
            )
            classification = _parse_classifier_response(response.choices[0].message.content)
            break
        except RateLimitError:
            if attempt < 2:
                logger.warning(f"Classifier rate limited (attempt {attempt + 1}), retrying...")
                await asyncio.sleep(2 * (attempt + 1))
                continue
            logger.error("Groq classifier rate limited after retries")
            break
        except Exception as e:
            logger.error(f"Groq classifier call failed: {e}")
            break

    if classification is None:
        classification = {
            "query_type": "MIXED",
            "companies": [],
            "metrics": [],
            "section_hint": None,
            "filings_needed": [{"form": "10-Q", "count": 1}],
            "reasoning": "Classifier unavailable — defaulting to MIXED",
        }

    # Enrich with jargon resolution
    classification = _apply_jargon_resolution(question, classification)

    logger.info(
        f"Classified query: type={classification['query_type']}, "
        f"companies={classification.get('companies')}, "
        f"metrics={classification['metrics']}, "
        f"section={classification.get('section_hint')}, "
        f"filings={classification.get('filings_needed')}"
    )

    return classification
