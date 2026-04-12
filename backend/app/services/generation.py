"""Grounded answer generation using Gemini Flash.

Takes retrieval results (text chunks, metrics, computed ratios) and
generates a strictly grounded answer. The system prompt enforces:
  - Answer ONLY from the provided context
  - Cite sources (page numbers, metric names)
  - Say "I don't have this information" if context is insufficient
  - Never hallucinate or speculate beyond the data
"""
import logging

from google import genai

from app.config import get_settings
from app.models.query import Citation
from app.services.retrieval import RetrievalResult
from app.services.sentiment import AggregatedSentiment

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are FinSight, a financial analysis assistant. You answer questions about \
SEC filings (10-Q, 10-K) that users have uploaded.

## Rules — follow these strictly:

1. Answer ONLY from the context provided below. Do not use outside knowledge.
2. If the context does not contain enough information to answer, say: \
"I don't have enough information in the uploaded documents to answer this."
3. Cite your sources inline using [Page N] for text references and \
[Metric: name] for numerical data.
4. When presenting numbers, include the unit (e.g., "$94.0 billion", "46.8%").
5. When a computed ratio is available, present it with its formula context \
(e.g., "Gross margin is 46.8% (gross profit / revenue)").
6. For sentiment or outlook questions, ground your assessment in specific \
quotes or metric trends from the documents. Never speculate.
7. Be concise. Lead with the direct answer, then supporting detail.
8. If the user asks about data from documents they haven't uploaded, tell them \
specifically what to upload for that analysis.
"""


def _build_context(
    result: RetrievalResult,
    classification: dict,
    sentiment: AggregatedSentiment | None = None,
) -> str:
    """Assemble retrieval results into a context block for the LLM."""
    sections = []

    # Metrics
    if result.metrics:
        lines = ["## Extracted Metrics"]
        for m in result.metrics:
            parts = [f"**{m.metric_name}**: {m.value}"]
            if m.unit:
                parts.append(f"({m.unit})")
            if m.prior_value is not None:
                parts.append(f"| Prior: {m.prior_value}")
            if m.change_pct is not None:
                direction = "+" if m.change_pct > 0 else ""
                parts.append(f"| Change: {direction}{m.change_pct}%")
            if m.period:
                parts.append(f"| Period: {m.period}")
            if m.page_num is not None:
                parts.append(f"[Page {m.page_num}]")
            lines.append(" ".join(parts))
        sections.append("\n".join(lines))

    # Computed ratios
    if result.ratios:
        lines = ["## Computed Ratios"]
        for r in result.ratios:
            val_str = f"{r.value:.2f}%" if r.format == "percentage" else f"{r.value:.2f}"
            parts = [f"**{r.display_name}**: {val_str}"]
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
        lines = ["## Relevant Document Excerpts"]
        for i, chunk in enumerate(result.chunks, 1):
            header = f"### Excerpt {i}"
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
        return "No relevant information found in the uploaded documents."

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
            document_id=m.document_id,
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
            document_id=chunk.document_id,
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


def _get_client() -> genai.Client:
    settings = get_settings()
    return genai.Client(api_key=settings.gemini_api_key)


async def generate_answer(
    question: str,
    retrieval_result: RetrievalResult,
    classification: dict,
    sentiment: AggregatedSentiment | None = None,
) -> dict:
    """Generate a grounded answer from retrieval results using Gemini Flash.

    Args:
        question: the user's original question
        retrieval_result: chunks + metrics + ratios from hybrid retrieval
        classification: output from classify_query
        sentiment: FinBERT sentiment analysis results (for SENTIMENT queries)

    Returns:
        dict with keys: answer, citations, query_type, confidence,
        metrics_used, ratios_computed, sentiment
    """
    context = _build_context(retrieval_result, classification, sentiment)
    citations = _build_citations(retrieval_result)
    confidence = _assess_confidence(retrieval_result, classification)

    # If nothing was retrieved, skip the LLM call
    if not retrieval_result.chunks and not retrieval_result.metrics:
        return {
            "answer": (
                "I don't have enough information in the uploaded documents to answer this. "
                "Make sure you've uploaded relevant SEC filings (10-Q or 10-K) and that "
                "they've finished processing."
            ),
            "citations": [],
            "query_type": classification.get("query_type", "MIXED"),
            "confidence": "low",
            "metrics_used": None,
            "ratios_computed": None,
            "sentiment": None,
        }

    user_prompt = f"""## Context from uploaded documents

{context}

## Question

{question}

Answer the question using ONLY the context above. Cite sources with [Page N] or [Metric: name]."""

    client = _get_client()

    try:
        response = await client.aio.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                {"role": "user", "parts": [{"text": SYSTEM_PROMPT + "\n\n" + user_prompt}]},
            ],
        )
        answer = response.text.strip()
    except Exception as e:
        logger.error(f"Gemini generation failed: {e}")
        answer = (
            "I encountered an error generating the answer. "
            "The retrieval was successful — here's what I found:\n\n"
            + context
        )

    # Build response payload
    metrics_used = None
    if retrieval_result.metrics:
        metrics_used = [
            {
                "name": m.metric_name,
                "value": m.value,
                "prior_value": m.prior_value,
                "change_pct": m.change_pct,
                "unit": m.unit,
                "period": m.period,
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
