"""Query classifier via OpenAI-compatible LLM endpoint.

Takes a user question and classifies it into a query type, extracts
target metric names, and identifies any financial jargon. This drives
the retrieval routing — NUMERICAL questions go to structured SQL,
NARRATIVE questions go to vector search, MIXED uses both.
"""
import asyncio
import json
import logging

from openai import AsyncOpenAI, RateLimitError

from app.config import get_settings
from app.finance.jargon import is_special_concept, get_special_concept

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

Important: There is NO Q4 10-Q filing. Q4 results are reported in the annual 10-K.
So to cover a full year you need the 10-K (has Q4/annual data) PLUS the 10-Qs (Q1-Q3).

### Available filing types on EDGAR

- **10-K**: Annual report — full financial statements, MD&A, risk factors, business overview, segment data. Most comprehensive.
- **10-Q**: Quarterly report — quarterly financials, condensed MD&A, updated risk factors. Filed for Q1-Q3 only (Q4 is in 10-K).
- **8-K**: Current event report — material events like acquisitions, CEO changes, earnings releases, restructurings, lawsuits, guidance updates.
- **DEF 14A**: Proxy statement — executive compensation, board of directors, shareholder proposals, governance.
- **20-F**: Annual report for foreign companies listed in the US (replaces 10-K for foreign issuers like Alibaba, Toyota, SAP, Shell).
- **S-1**: IPO registration statement — business overview, financials, risk factors, use of proceeds. Filed before going public.
- **4**: Insider trading form — stock purchases/sales by executives and directors.

### Rules of thumb

- Latest snapshot / single-quarter question -> [{"form": "10-Q", "count": 1}]
- Annual overview, risk factors, business description -> [{"form": "10-K", "count": 1}]
- Trend / growth / "past year" / "over time" / multi-period -> [{"form": "10-K", "count": 1}, {"form": "10-Q", "count": 4}] to cover all quarters including Q4
- Recent news / events / acquisitions / leadership changes -> [{"form": "8-K", "count": 5}]
- "How is X doing" / general performance -> [{"form": "10-K", "count": 1}, {"form": "10-Q", "count": 2}] for recent + annual context
- Executive pay / board / governance / proxy -> [{"form": "DEF 14A", "count": 1}]
- Foreign companies (Alibaba, Toyota, SAP, etc.) -> use "20-F" instead of "10-K" for annual reports
- IPO / "when did X go public" / S-1 -> [{"form": "S-1", "count": 1}]
- Insider buying/selling -> [{"form": "4", "count": 10}]
- Multi-year comparisons -> [{"form": "10-K", "count": 3}] for 3 years of annual data
- When unsure, default to [{"form": "10-Q", "count": 1}]

## Output Format

Return ONLY valid JSON (no markdown, no backticks):
{
  "query_type": "NUMERICAL|NARRATIVE|MIXED|SENTIMENT",
  "companies": ["TICKER1", "TICKER2"],
  "metrics": ["list of canonical metric names the question is about"],
  "section_hint": "MD&A|Risk Factors|Financial Statements|Notes|null",
  "filings_needed": [{"form": "10-K|10-Q|8-K|DEF 14A|20-F|S-1|4", "count": 1}],
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
{"query_type": "SENTIMENT", "companies": ["TSLA"], "metrics": [], "section_hint": "MD&A", "filings_needed": [{"form": "10-K", "count": 1}, {"form": "10-Q", "count": 1}], "reasoning": "Management outlook needs the latest 10-K (most comprehensive MD&A) plus latest 10-Q for recent updates"}

User: "How is Apple's revenue trending over the past year?"
{"query_type": "NUMERICAL", "companies": ["AAPL"], "metrics": ["revenue"], "section_hint": "Financial Statements", "filings_needed": [{"form": "10-K", "count": 1}, {"form": "10-Q", "count": 4}], "reasoning": "Past year trend needs the 10-K for Q4/annual data plus recent 10-Qs — there is no Q4 10-Q"}

User: "Compare Microsoft and Google operating margins"
{"query_type": "NUMERICAL", "companies": ["MSFT", "GOOGL"], "metrics": ["operating_income", "revenue"], "section_hint": "Financial Statements", "filings_needed": [{"form": "10-Q", "count": 1}], "reasoning": "Cross-company comparison using latest quarterly data for each"}

User: "What did Meta say about AI in their last 10-Q?"
{"query_type": "NARRATIVE", "companies": ["META"], "metrics": [], "section_hint": "MD&A", "filings_needed": [{"form": "10-Q", "count": 1}], "reasoning": "Qualitative question about Meta's AI commentary in their latest 10-Q"}

User: "Any recent news about NVIDIA?"
{"query_type": "NARRATIVE", "companies": ["NVDA"], "metrics": [], "section_hint": null, "filings_needed": [{"form": "8-K", "count": 5}], "reasoning": "Recent events and news are reported in 8-K filings"}

User: "How is Netflix doing in past 1 year?"
{"query_type": "MIXED", "companies": ["NFLX"], "metrics": ["revenue", "net_income", "eps_diluted"], "section_hint": null, "filings_needed": [{"form": "10-K", "count": 1}, {"form": "10-Q", "count": 4}], "reasoning": "Past year overview needs the annual 10-K for Q4 data plus quarterly 10-Qs for the full picture"}

User: "How much does Tim Cook get paid? What's Apple's executive compensation?"
{"query_type": "NARRATIVE", "companies": ["AAPL"], "metrics": [], "section_hint": null, "filings_needed": [{"form": "DEF 14A", "count": 1}], "reasoning": "Executive compensation details are in the proxy statement (DEF 14A), not in 10-K/10-Q"}

User: "Who is on NVIDIA's board of directors?"
{"query_type": "NARRATIVE", "companies": ["NVDA"], "metrics": [], "section_hint": null, "filings_needed": [{"form": "DEF 14A", "count": 1}], "reasoning": "Board composition and governance info is in the proxy statement"}

User: "What are Alibaba's risk factors and revenue?"
{"query_type": "MIXED", "companies": ["BABA"], "metrics": ["revenue"], "section_hint": "Risk Factors", "filings_needed": [{"form": "20-F", "count": 1}], "reasoning": "Alibaba is a foreign private issuer — uses 20-F instead of 10-K for annual reports"}

User: "How much debt does AT&T have?"
{"query_type": "NUMERICAL", "companies": ["T"], "metrics": ["long_term_debt", "total_debt", "current_liabilities"], "section_hint": "Financial Statements", "filings_needed": [{"form": "10-Q", "count": 1}], "reasoning": "Balance sheet debt metrics from latest quarterly filing"}

User: "What's Amazon's free cash flow and capex spending?"
{"query_type": "NUMERICAL", "companies": ["AMZN"], "metrics": ["free_cash_flow", "capital_expenditures", "operating_cash_flow"], "section_hint": "Financial Statements", "filings_needed": [{"form": "10-Q", "count": 1}], "reasoning": "Cash flow statement metrics from the latest quarter"}

User: "How much did Apple spend on share buybacks last year?"
{"query_type": "NUMERICAL", "companies": ["AAPL"], "metrics": ["share_repurchases"], "section_hint": "Financial Statements", "filings_needed": [{"form": "10-K", "count": 1}], "reasoning": "Annual buyback total is in the 10-K"}

User: "Break down Microsoft's revenue by segment"
{"query_type": "MIXED", "companies": ["MSFT"], "metrics": ["revenue"], "section_hint": "Notes", "filings_needed": [{"form": "10-K", "count": 1}], "reasoning": "Segment breakdowns are in the Notes to Financial Statements in the annual report"}

User: "How much does Coca-Cola pay in dividends?"
{"query_type": "NUMERICAL", "companies": ["KO"], "metrics": ["dividends_per_share", "dividends_paid"], "section_hint": "Financial Statements", "filings_needed": [{"form": "10-Q", "count": 1}], "reasoning": "Latest dividend data from the most recent quarterly filing"}

User: "Did Disney make any acquisitions recently?"
{"query_type": "NARRATIVE", "companies": ["DIS"], "metrics": [], "section_hint": null, "filings_needed": [{"form": "8-K", "count": 10}], "reasoning": "Acquisitions are reported as material events in 8-K filings"}

User: "TSLA eps"
{"query_type": "NUMERICAL", "companies": ["TSLA"], "metrics": ["eps_basic", "eps_diluted"], "section_hint": "Financial Statements", "filings_needed": [{"form": "10-Q", "count": 1}], "reasoning": "User gave a ticker directly — latest EPS from the most recent 10-Q"}

User: "Compare profit margins and revenue growth of Apple, Microsoft, and Amazon"
{"query_type": "NUMERICAL", "companies": ["AAPL", "MSFT", "AMZN"], "metrics": ["revenue", "gross_profit", "operating_income", "net_income"], "section_hint": "Financial Statements", "filings_needed": [{"form": "10-Q", "count": 2}], "reasoning": "Three-way comparison needs latest quarter plus prior quarter to compute growth — applied per company"}

User: "How much does Google spend on R&D?"
{"query_type": "NUMERICAL", "companies": ["GOOGL"], "metrics": ["research_and_development"], "section_hint": "Financial Statements", "filings_needed": [{"form": "10-Q", "count": 1}], "reasoning": "R&D spending is a line item on the income statement"}

User: "What drove the increase in JPMorgan's operating expenses?"
{"query_type": "MIXED", "companies": ["JPM"], "metrics": ["operating_expenses", "selling_general_admin"], "section_hint": "MD&A", "filings_needed": [{"form": "10-Q", "count": 1}], "reasoning": "Needs the number (metric) plus management's explanation (MD&A)"}

User: "How has Tesla's stock-based compensation changed over the last 3 years?"
{"query_type": "NUMERICAL", "companies": ["TSLA"], "metrics": ["stock_based_compensation"], "section_hint": "Financial Statements", "filings_needed": [{"form": "10-K", "count": 3}], "reasoning": "Multi-year trend — need 3 annual reports to compare"}

User: "What is Toyota's business overview?"
{"query_type": "NARRATIVE", "companies": ["TM"], "metrics": [], "section_hint": null, "filings_needed": [{"form": "20-F", "count": 1}], "reasoning": "Toyota is a foreign issuer — uses 20-F instead of 10-K"}

User: "Are there any insider trades at Palantir recently?"
{"query_type": "NARRATIVE", "companies": ["PLTR"], "metrics": [], "section_hint": null, "filings_needed": [{"form": "4", "count": 10}], "reasoning": "Insider buy/sell transactions are reported on Form 4"}

User: "What's Uber's latest guidance and outlook?"
{"query_type": "SENTIMENT", "companies": ["UBER"], "metrics": [], "section_hint": "MD&A", "filings_needed": [{"form": "10-K", "count": 1}, {"form": "10-Q", "count": 1}, {"form": "8-K", "count": 3}], "reasoning": "Guidance needs the latest 10-K for comprehensive MD&A, latest 10-Q for recent updates, plus recent 8-Ks for earnings guidance"}

User: "How is the economy doing?"
{"query_type": "NARRATIVE", "companies": [], "metrics": [], "section_hint": null, "filings_needed": [], "reasoning": "No specific public company mentioned — cannot look up SEC filings"}

User: "What's the best stock to buy?"
{"query_type": "NARRATIVE", "companies": [], "metrics": [], "section_hint": null, "filings_needed": [], "reasoning": "No specific company and asking for investment advice — cannot answer from SEC filings"}

Now classify this query:
"""


def _get_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
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


def _enrich_filings_needed(question: str, classification: dict) -> dict:
    """Rule-based safety net for filing types the LLM might miss.

    Scans the question for keywords that strongly imply a specific filing
    type and ensures it's present in filings_needed. Does NOT remove
    anything the LLM already chose — only adds missing types.
    """
    q = question.lower()
    filings = classification.get("filings_needed", [])
    existing_forms = {f.get("form", "").upper() for f in filings}

    # 8-K: recent events, news, acquisitions, earnings release
    _8k_keywords = [
        "recent news", "recent event", "acquisition", "acquir",
        "merger", "leadership change", "ceo change", "restructur",
        "earnings release", "guidance update", "material event",
        "any news", "any event", "what happened", "latest news",
    ]
    if any(kw in q for kw in _8k_keywords) and "8-K" not in existing_forms:
        filings.append({"form": "8-K", "count": 5})

    # DEF 14A: executive compensation, board, proxy, governance
    _proxy_keywords = [
        "compensation", "paid", "pay", "salary", "executive comp",
        "board of director", "proxy", "governance", "shareholder proposal",
        "how much does", "how much do",
    ]
    if any(kw in q for kw in _proxy_keywords) and "DEF 14A" not in existing_forms:
        filings.append({"form": "DEF 14A", "count": 1})

    # 20-F: known foreign issuers
    _foreign_tickers = {
        "BABA", "TSM", "TM", "SAP", "NVO", "ASML", "SHOP", "SE",
        "SONY", "NIO", "XPEV", "LI", "JD", "PDD", "BIDU",
    }
    companies = classification.get("companies", [])
    if any(t in _foreign_tickers for t in companies):
        if "20-F" not in existing_forms:
            # Replace 10-K with 20-F for foreign issuers
            classification["filings_needed"] = [
                {"form": "20-F" if f.get("form") == "10-K" else f.get("form"), "count": f.get("count", 1)}
                for f in filings
            ]
            filings = classification["filings_needed"]
            if "20-F" not in {f.get("form") for f in filings}:
                filings.append({"form": "20-F", "count": 1})

    # Form 4: insider trading
    _insider_keywords = [
        "insider trad", "insider buy", "insider sell", "insider transaction",
        "form 4", "insider ownership",
    ]
    if any(kw in q for kw in _insider_keywords) and "4" not in existing_forms:
        filings.append({"form": "4", "count": 10})

    # S-1: IPO
    _ipo_keywords = ["ipo", "s-1", "went public", "go public", "going public"]
    if any(kw in q for kw in _ipo_keywords) and "S-1" not in existing_forms:
        filings.append({"form": "S-1", "count": 1})

    classification["filings_needed"] = filings
    return classification


async def classify_query(question: str) -> dict:
    """Classify a user question using the configured LLM + jargon resolution.

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
    max_retries = 5
    for attempt in range(max_retries):
        try:
            settings = get_settings()
            response = await client.chat.completions.create(
                model=settings.llm_model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=0,
            )
            classification = _parse_classifier_response(response.choices[0].message.content)
            break
        except RateLimitError:
            if attempt < max_retries - 1:
                wait = min(5 * (2 ** attempt), 60)
                logger.warning(f"Classifier rate limited (attempt {attempt + 1}), retrying in {wait}s...")
                await asyncio.sleep(wait)
                continue
            logger.error("LLM classifier rate limited after retries")
            break
        except Exception as e:
            logger.error(f"LLM classifier call failed: {e}")
            break

    if classification is None:
        classification = {
            "query_type": "MIXED",
            "companies": [],
            "metrics": [],
            "section_hint": None,
            "filings_needed": [{"form": "10-Q", "count": 1}],
            "reasoning": "Classifier unavailable — defaulting to MIXED",
            "_classifier_failed": True,
        }

    # Enrich with jargon resolution
    classification = _apply_jargon_resolution(question, classification)

    # Rule-based filing type safety net — catch keywords the LLM might miss
    classification = _enrich_filings_needed(question, classification)

    logger.info(
        f"Classified query: type={classification['query_type']}, "
        f"companies={classification.get('companies')}, "
        f"metrics={classification['metrics']}, "
        f"section={classification.get('section_hint')}, "
        f"filings={classification.get('filings_needed')}"
    )

    return classification
