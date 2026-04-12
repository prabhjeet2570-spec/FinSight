"""Query endpoint — the core RAG pipeline.

Pipeline: question -> classify -> retrieve -> generate -> respond

1. Classify the query (Gemini Flash) -> type + target metrics + section hint
2. Resolve financial jargon -> expand metric names via synonym dict
3. Retrieve context (hybrid: vector search + structured SQL + ratio computation)
4. Generate grounded answer (Gemini Flash) with citations
"""
import logging

from fastapi import APIRouter, HTTPException

from app.db.connection import get_pool
from app.models.query import QueryRequest, QueryResponse
from app.services.classifier import classify_query
from app.services.generation import generate_answer
from app.services.retrieval import hybrid_retrieve
from app.services.sentiment import analyze_sentiment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query_documents(req: QueryRequest):
    """Ask a question about uploaded documents.

    The pipeline:
      1. Classify the query (what type? what metrics? what section?)
      2. Run hybrid retrieval (vector search + structured metric lookup)
      3. Compute financial ratios from retrieved metrics
      4. Generate a grounded answer with Gemini Flash
      5. Return answer + citations + metadata
    """
    pool = await get_pool()

    # Validate that requested documents exist (if specific IDs provided)
    if req.document_ids:
        async with pool.acquire() as conn:
            placeholders = ", ".join(f"${i+1}" for i in range(len(req.document_ids)))
            count = await conn.fetchval(
                f"SELECT count(*) FROM documents WHERE id IN ({placeholders})",
                *req.document_ids,
            )
            if count != len(req.document_ids):
                raise HTTPException(
                    status_code=404,
                    detail="One or more document IDs not found",
                )
            # Check if any are still processing
            processing = await conn.fetchval(
                f"SELECT count(*) FROM documents WHERE id IN ({placeholders}) AND status = 'processing'",
                *req.document_ids,
            )
            if processing > 0:
                raise HTTPException(
                    status_code=409,
                    detail=f"{processing} document(s) still processing. Please wait.",
                )

    # Step 1: Classify
    logger.info(f"Classifying query: {req.question[:80]}...")
    classification = await classify_query(req.question)

    # Step 2: Determine retrieval parameters from classification
    metric_names = classification.get("metrics") or None
    section_hint = classification.get("section_hint")

    # For NUMERICAL queries, we want more metrics and fewer chunks
    # For NARRATIVE queries, we want more chunks and skip metrics
    query_type = classification["query_type"]
    top_k = 5
    if query_type == "NUMERICAL":
        top_k = 2  # still get some text context
    elif query_type == "NARRATIVE":
        metric_names = None  # skip structured lookup
        top_k = 8
    elif query_type == "SENTIMENT":
        top_k = 8  # sentiment needs more text passages
        section_hint = section_hint or "MD&A"

    # Step 3: Retrieve
    logger.info(
        f"Retrieving: type={query_type}, metrics={metric_names}, "
        f"section={section_hint}, top_k={top_k}"
    )
    retrieval_result = await hybrid_retrieve(
        query=req.question,
        document_ids=req.document_ids,
        metric_names=metric_names,
        section_filter=section_hint,
        top_k_chunks=top_k,
    )
    logger.info(
        f"Retrieved: {len(retrieval_result.chunks)} chunks, "
        f"{len(retrieval_result.metrics)} metrics, "
        f"{len(retrieval_result.ratios)} ratios"
    )

    # Step 4: Sentiment analysis (for SENTIMENT queries)
    sentiment_result = None
    if query_type == "SENTIMENT" and retrieval_result.chunks:
        chunk_texts = [c.text for c in retrieval_result.chunks]
        sentiment_result = analyze_sentiment(chunk_texts)
        logger.info(
            f"Sentiment: {sentiment_result.overall} "
            f"(pos={sentiment_result.positive_score:.2f}, "
            f"neg={sentiment_result.negative_score:.2f}, "
            f"neu={sentiment_result.neutral_score:.2f}) "
            f"over {sentiment_result.analyzed_chunks} chunks"
        )

    # Step 5: Generate
    result = await generate_answer(
        question=req.question,
        retrieval_result=retrieval_result,
        classification=classification,
        sentiment=sentiment_result,
    )

    return QueryResponse(**result)
