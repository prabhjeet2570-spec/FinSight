"""Grounded answer generation via OpenAI-compatible LLM endpoint.

Takes retrieval results (text chunks, metrics, computed ratios) and
generates a strictly grounded answer. The system prompt enforces:
  - Answer ONLY from the provided context
  - Cite sources (page numbers, metric names)
  - Say "I don't have this information" if context is insufficient
  - Never hallucinate or speculate beyond the data
"""
import asyncio
import logging

from openai import AsyncOpenAI, RateLimitError

from app.config import get_settings
from app.models.query import Citation
from app.services.retrieval import RetrievalResult
from app.services.sentiment import AggregatedSentiment

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are FinSight, a financial analysis assistant. You answer questions about \
SEC filings (10-Q, 10-K) fetched on demand from SEC EDGAR.

## Rules — follow these strictly:

1. Answer ONLY from the context provided below. Do not use outside knowledge.
2. If the context does not contain enough information to answer, say: \
"I don't have enough information in this filing to answer that."
3. Do NOT add inline citations like [Page N] or [Metric: name] in your answer. \
Citations are handled separately by the system.
4. When presenting numbers, include the unit (e.g., "$94.0 billion", "46.8%").
5. For sentiment or outlook questions, ground your assessment in specific \
quotes or metric trends from the filing. Never speculate.
6. If the user asks about a metric that isn't present in the filing, say so \
plainly — don't infer or estimate.

## How to write your answer:

Write a natural, flowing analysis. Do NOT use rigid section headers or a \
fixed template. Just answer the question thoroughly using the data.

- Start your answer by stating exactly which filing(s) the data comes from, using \
the period labels from the "Filings used" section in the context. For example: \
"Based on the latest available filing — Apple's 10-Q for Q3 2025 — ..." or \
"Using Microsoft's 10-Q (Q4 2025) and Alphabet's 10-Q (Q3 2025), ...". \
Use the EXACT period labels from the context — do NOT convert to fiscal quarters.
- For comparison queries where companies have different filing periods, explicitly \
flag it: "Note: these filings cover different periods (MSFT Q4 2025 vs GOOGL Q3 2025), \
so the comparison is not perfectly apples-to-apples."
- Lead with the direct answer and key numbers.
- ALWAYS mention the explicit time period (quarter and year) when presenting any number. \
Never say "in the current period" or "in the latest quarter" — say the actual period. \
IMPORTANT: Some companies (like Apple) have fiscal years that differ from the calendar \
year. The "Filings used" section lists the canonical period labels (e.g., "Q4 2025"). \
Always use THOSE labels in your answer — do NOT use the company's internal fiscal \
quarter naming (e.g., do NOT say "Q1 FY2026" if the filing is labeled "Q4 2025").
- Include relevant trends, YoY changes, and comparisons where the data supports it.
- If the context includes management commentary or forward-looking statements, \
weave those in naturally (e.g., "Management noted that...").
- End with a brief concluding take — is the picture positive, negative, or mixed?
- For comparison queries, clearly call out which company leads and by how much.
- Use **bold** for emphasis on key numbers or takeaways, not as section headers.
- Use bullet points only when listing several data points — not for every sentence.
- Keep it concise but thorough. Don't repeat the same point in different words.
"""


def _build_context(
    result: RetrievalResult,
    classification: dict,
    sentiment: AggregatedSentiment | None = None,
    filing_ticker_map: dict | None = None,
    filing_period_map: dict | None = None,
) -> str:
    """Assemble retrieval results into a context block for the LLM.

    When filing_ticker_map is provided and has 2+ companies, metrics,
    ratios, and chunks are grouped by company ticker so the LLM can
    attribute data correctly in comparison queries.
    """
    ftm = filing_ticker_map or {}
    fpm = filing_period_map or {}
    multi_company = len(set(ftm.values())) >= 2
    sections = []

    def _ticker_tag(filing_id) -> str:
        """Return '[AAPL] ' prefix when in multi-company mode."""
        if not multi_company or filing_id is None:
            return ""
        ticker = ftm.get(filing_id, "")
        return f"[{ticker}] " if ticker else ""

    def _period_for(filing_id, fallback_period) -> str | None:
        """Use filing-level period_label, falling back to raw XBRL period."""
        return fpm.get(filing_id) or fallback_period

    # Metrics
    if result.metrics:
        lines = ["## Extracted Metrics"]
        for m in result.metrics:
            tag = _ticker_tag(m.filing_id)
            period = _period_for(m.filing_id, m.period)
            period_tag = f" ({period})" if period else ""
            parts = [f"{tag}**{m.metric_name}**{period_tag}: {m.value}"]
            if m.unit:
                parts.append(f"({m.unit})")
            if m.prior_value is not None:
                parts.append(f"| Prior: {m.prior_value}")
            if m.change_pct is not None:
                direction = "+" if m.change_pct > 0 else ""
                parts.append(f"| Change: {direction}{m.change_pct}%")
            if m.page_num is not None:
                parts.append(f"[Page {m.page_num}]")
            lines.append(" ".join(parts))
        sections.append("\n".join(lines))

    # Computed ratios
    if result.ratios:
        lines = ["## Computed Ratios"]
        for r in result.ratios:
            tag = _ticker_tag(r.filing_id)
            val_str = f"{r.value:.2f}%" if r.format == "percentage" else f"{r.value:.2f}"
            parts = [f"{tag}**{r.display_name}**: {val_str}"]
            if r.prior_value is not None:
                prior_str = f"{r.prior_value:.2f}%" if r.format == "percentage" else f"{r.prior_value:.2f}"
                parts.append(f"| Prior: {prior_str}")
            if r.change_pct is not None:
                direction = "+" if r.change_pct > 0 else ""
                parts.append(f"| Change: {direction}{r.change_pct:.1f}%")
            parts.append(f"({r.description})")
            lines.append(" ".join(parts))
        sections.append("\n".join(lines))

    # Sentiment analysis
    if sentiment and sentiment.analyzed_chunks > 0:
        lines = ["## FinBERT Sentiment Analysis (MD&A)"]
        lines.append(
            f"Overall tone: **{sentiment.overall}** "
            f"(positive: {sentiment.positive_score:.1%}, "
            f"negative: {sentiment.negative_score:.1%}, "
            f"neutral: {sentiment.neutral_score:.1%}) "
            f"— analyzed {sentiment.analyzed_chunks} text passages"
        )
        # Show per-chunk breakdown for the most opinionated passages
        notable = sorted(
            sentiment.chunk_scores,
            key=lambda s: max(s.positive, s.negative),
            reverse=True,
        )[:5]
        if notable:
            lines.append("")
            lines.append("Notable passages:")
            for s in notable:
                lines.append(
                    f"- [{s.label}] (pos={s.positive:.0%} neg={s.negative:.0%}) "
                    f'"{s.text_preview}..."'
                )
        sections.append("\n".join(lines))

    # Text chunks
    if result.chunks:
        lines = ["## Relevant Filing Excerpts"]
        for i, chunk in enumerate(result.chunks, 1):
            tag = _ticker_tag(chunk.filing_id)
            period = _period_for(chunk.filing_id, None)
            header = f"### {tag}Excerpt {i}"
            if period:
                header += f" [{period}]"
            if chunk.page_num is not None:
                header += f" [Page {chunk.page_num}]"
            if chunk.section:
                header += f" ({chunk.section})"
            header += f" — similarity: {chunk.similarity:.3f}"
            lines.append(header)
            lines.append(chunk.text)
            lines.append("")
        sections.append("\n".join(lines))

    if not sections:
        return "No relevant information found in the fetched filings."

    return "\n\n".join(sections)


def _build_citations(result: RetrievalResult) -> list[Citation]:
    """Build citation objects from retrieval results."""
    citations = []

    for m in result.metrics:
        detail = f"{m.metric_name} = {m.value}"
        if m.unit:
            detail += f" {m.unit}"
        citations.append(Citation(
            source_type="metric",
            filing_id=m.filing_id,
            page_num=m.page_num,
            metric_name=m.metric_name,
            detail=detail,
        ))

    for r in result.ratios:
        val_str = f"{r.value:.2f}%" if r.format == "percentage" else f"{r.value:.2f}"
        citations.append(Citation(
            source_type="ratio",
            metric_name=r.name,
            detail=f"{r.display_name} = {val_str}",
        ))

    for chunk in result.chunks:
        citations.append(Citation(
            source_type="text_chunk",
            filing_id=chunk.filing_id,
            page_num=chunk.page_num,
            section=chunk.section,
            detail=chunk.text[:120] + "..." if len(chunk.text) > 120 else chunk.text,
        ))

    return citations


def _assess_confidence(result: RetrievalResult, classification: dict) -> str:
    """Assess answer confidence based on retrieval quality."""
    query_type = classification.get("query_type", "MIXED")

    if query_type == "NUMERICAL":
        if result.metrics:
            return "high"
        if result.chunks:
            return "medium"
        return "low"

    if query_type == "NARRATIVE":
        if result.chunks and result.chunks[0].similarity > 0.5:
            return "high"
        if result.chunks and result.chunks[0].similarity > 0.3:
            return "medium"
        return "low"

    if query_type == "SENTIMENT":
        has_metrics = bool(result.metrics)
        has_chunks = bool(result.chunks)
        if has_metrics and has_chunks:
            return "high"
        if has_metrics or has_chunks:
            return "medium"
        return "low"

    # MIXED
    has_metrics = bool(result.metrics)
    has_chunks = bool(result.chunks)
    if has_metrics and has_chunks:
        return "high"
    if has_metrics or has_chunks:
        return "medium"
    return "low"


def _get_client() -> AsyncOpenAI:
    settings = get_settings()
    return AsyncOpenAI(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
    )


async def generate_answer(
    question: str,
    retrieval_result: RetrievalResult,
    classification: dict,
    sentiment: AggregatedSentiment | None = None,
    filing_ticker_map: dict | None = None,
    filing_period_map: dict | None = None,
    filings_used: list[dict] | None = None,
) -> dict:
    """Generate a grounded answer from retrieval results.

    Args:
        question: the user's original question
        retrieval_result: chunks + metrics + ratios from hybrid retrieval
        classification: output from classify_query
        sentiment: FinBERT sentiment analysis results (for SENTIMENT queries)
        filing_ticker_map: {filing_id: ticker} for multi-company attribution
        filings_used: list of filing metadata dicts for source attribution

    Returns:
        dict with keys: answer, citations, query_type, confidence,
        metrics_used, ratios_computed, sentiment
    """
    context = _build_context(retrieval_result, classification, sentiment, filing_ticker_map, filing_period_map)
    citations = _build_citations(retrieval_result)
    confidence = _assess_confidence(retrieval_result, classification)

    # If nothing was retrieved, skip the LLM call
    if not retrieval_result.chunks and not retrieval_result.metrics:
        return {
            "answer": (
                "I couldn't find anything relevant in the SEC filings I fetched for "
                "this question. Try rephrasing — for example, ask about a specific "
                "metric, section (Risk Factors, MD&A), or time period."
            ),
            "citations": [],
            "query_type": classification.get("query_type", "MIXED"),
            "confidence": "low",
            "metrics_used": None,
            "ratios_computed": None,
            "sentiment": None,
        }

    # Build filing source summary for the LLM
    filing_source_lines = ""
    if filings_used:
        parts = []
        for f in filings_used:
            label = " ".join(filter(None, [f.get("ticker"), f.get("filing_type"), f.get("period_label")]))
            if label:
                parts.append(label)
        if parts:
            filing_source_lines = (
                "\n\n## Filings used — USE THESE period labels in your answer\n"
                + ", ".join(parts)
                + "\n\nIMPORTANT: The filing text may use the company's fiscal calendar "
                "(e.g., Apple calls calendar Q4 2025 as 'fiscal Q1 2026'). "
                "IGNORE the fiscal naming. Use ONLY the period labels listed above "
                "(e.g., say 'Q4 2025', NOT 'Q1 2026'). The user sees a table with "
                "these labels — your text MUST match."
            )

    user_prompt = f"""## Context from SEC filings
{filing_source_lines}

{context}

## Question

{question}

Answer the question using ONLY the context above. Do not add inline citations."""

    client = _get_client()

    answer = None
    max_retries = 5
    for attempt in range(max_retries):
        try:
            settings = get_settings()
            response = await client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
            )
            answer = response.choices[0].message.content.strip()
            break
        except RateLimitError:
            if attempt < max_retries - 1:
                wait = min(5 * (2 ** attempt), 60)
                logger.warning(f"LLM rate limited (attempt {attempt + 1}), retrying in {wait}s...")
                await asyncio.sleep(wait)
                continue
            logger.error("LLM generation rate limited after retries")
            break
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            break

    if answer is None:
        answer = (
            "I encountered an error generating the answer. "
            "The retrieval was successful — here's what I found:\n\n"
            + context
        )

    # Build response payload
    ftm = filing_ticker_map or {}
    fpm = filing_period_map or {}
    metrics_used = None
    if retrieval_result.metrics:
        metrics_used = [
            {
                "name": m.metric_name,
                "value": m.value,
                "prior_value": m.prior_value,
                "change_pct": m.change_pct,
                "unit": m.unit,
                "period": fpm.get(m.filing_id) or m.period,
                "ticker": ftm.get(m.filing_id),
            }
            for m in retrieval_result.metrics
        ]

    ratios_computed = None
    if retrieval_result.ratios:
        ratios_computed = [
            {
                "name": r.name,
                "display_name": r.display_name,
                "value": r.value,
                "prior_value": r.prior_value,
                "change_pct": r.change_pct,
                "format": r.format,
                "ticker": ftm.get(r.filing_id) if r.filing_id else None,
                "period": fpm.get(r.filing_id) if r.filing_id else None,
            }
            for r in retrieval_result.ratios
        ]

    sentiment_data = None
    if sentiment and sentiment.analyzed_chunks > 0:
        sentiment_data = {
            "overall": sentiment.overall,
            "positive_score": sentiment.positive_score,
            "negative_score": sentiment.negative_score,
            "neutral_score": sentiment.neutral_score,
            "analyzed_chunks": sentiment.analyzed_chunks,
        }

    return {
        "answer": answer,
        "citations": citations,
        "query_type": classification.get("query_type", "MIXED"),
        "confidence": confidence,
        "metrics_used": metrics_used,
        "ratios_computed": ratios_computed,
        "sentiment": sentiment_data,
    }
