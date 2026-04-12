"""Hybrid retrieval: vector search + structured metric lookup.

Combines two retrieval paths:
  1. Vector search — embed the query with FinBERT, find similar text chunks
     in pgvector using cosine similarity. Best for narrative questions
     ("what did management say about AI?").
  2. Structured lookup — search the metrics table by canonical metric name
     with synonym expansion. Best for numerical questions ("what was revenue?").

The hybrid_retrieve function merges both paths, deduplicates, and ranks
results for downstream generation.
"""
import logging
from dataclasses import dataclass, field
from uuid import UUID

from app.db.connection import get_pool
from app.finance.ratios import compute_all_ratios, ComputedRatio
from app.finance.synonyms import get_synonyms_for_metric
from app.services.embedding import embed_query

logger = logging.getLogger(__name__)


@dataclass
class ChunkResult:
    """A text chunk retrieved via vector similarity."""
    chunk_id: UUID
    document_id: UUID
    text: str
    page_num: int
    section: str | None
    similarity: float  # cosine similarity score (0-1)

    @property
    def source_type(self) -> str:
        return "text_chunk"


@dataclass
class MetricResult:
    """A metric retrieved via structured lookup."""
    metric_name: str
    value: float | None
    prior_value: float | None
    change_pct: float | None
    unit: str
    period: str | None
    prior_period: str | None
    page_num: int | None
    table_type: str | None
    document_id: UUID

    @property
    def source_type(self) -> str:
        return "metric"


@dataclass
class RetrievalResult:
    """Combined retrieval result from all paths."""
    chunks: list[ChunkResult] = field(default_factory=list)
    metrics: list[MetricResult] = field(default_factory=list)
    ratios: list[ComputedRatio] = field(default_factory=list)


# ---------- Vector search ----------

async def search_chunks(
    query: str,
    document_ids: list[UUID] | None = None,
    section_filter: str | None = None,
    top_k: int = 5,
) -> list[ChunkResult]:
    """Find the most similar text chunks to a query using pgvector.

    Embeds the query with FinBERT, then finds nearest neighbors in the
    text_chunks table using cosine distance.

    Args:
        query: natural language question
        document_ids: restrict to specific documents (None = search all)
        section_filter: restrict to a SEC filing section (e.g., "MD&A")
        top_k: number of results to return
    """
    pool = await get_pool()
    query_embedding = embed_query(query)

    # Build WHERE clause dynamically
    conditions = ["tc.embedding IS NOT NULL"]
    params: list = [query_embedding, top_k]
    param_idx = 3  # $1 = embedding, $2 = top_k

    if document_ids:
        placeholders = ", ".join(f"${param_idx + i}" for i in range(len(document_ids)))
        conditions.append(f"tc.document_id IN ({placeholders})")
        params.extend(document_ids)
        param_idx += len(document_ids)

    if section_filter:
        conditions.append(f"tc.section = ${param_idx}")
        params.append(section_filter)
        param_idx += 1

    where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT tc.id, tc.document_id, tc.chunk_text, tc.page_num, tc.section,
               1 - (tc.embedding <=> $1::vector) AS similarity
        FROM text_chunks tc
        WHERE {where_clause}
        ORDER BY tc.embedding <=> $1::vector
        LIMIT $2
    """

    async with pool.acquire() as conn:
        from pgvector.asyncpg import register_vector
        await register_vector(conn)
        rows = await conn.fetch(sql, *params)

    return [
        ChunkResult(
            chunk_id=row["id"],
            document_id=row["document_id"],
            text=row["chunk_text"],
            page_num=row["page_num"],
            section=row["section"],
            similarity=float(row["similarity"]),
        )
        for row in rows
    ]


# ---------- Structured metric lookup ----------

async def search_metrics(
    metric_names: list[str],
    document_ids: list[UUID] | None = None,
) -> list[MetricResult]:
    """Look up metrics by canonical name with synonym expansion.

    Searches the metrics table for exact matches on metric_name.
    The caller should resolve jargon and expand synonyms before calling this.

    Args:
        metric_names: canonical metric names to search for
        document_ids: restrict to specific documents (None = search all)
    """
    if not metric_names:
        return []

    pool = await get_pool()

    conditions = []
    params: list = []
    param_idx = 1

    # metric_name IN (...)
    placeholders = ", ".join(f"${param_idx + i}" for i in range(len(metric_names)))
    conditions.append(f"m.metric_name IN ({placeholders})")
    params.extend(metric_names)
    param_idx += len(metric_names)

    if document_ids:
        doc_placeholders = ", ".join(f"${param_idx + i}" for i in range(len(document_ids)))
        conditions.append(f"m.document_id IN ({doc_placeholders})")
        params.extend(document_ids)
        param_idx += len(document_ids)

    where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT m.metric_name, m.value, m.prior_value, m.change_pct, m.unit,
               m.period, m.prior_period, m.page_num, m.table_type, m.document_id
        FROM metrics m
        WHERE {where_clause}
        ORDER BY m.metric_name
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    return [
        MetricResult(
            metric_name=row["metric_name"],
            value=float(row["value"]) if row["value"] is not None else None,
            prior_value=float(row["prior_value"]) if row["prior_value"] is not None else None,
            change_pct=float(row["change_pct"]) if row["change_pct"] is not None else None,
            unit=row["unit"],
            period=row["period"],
            prior_period=row["prior_period"],
            page_num=row["page_num"],
            table_type=row["table_type"],
            document_id=row["document_id"],
        )
        for row in rows
    ]


# ---------- Ratio computation from retrieved metrics ----------

def compute_ratios_from_metrics(metrics: list[MetricResult]) -> list[ComputedRatio]:
    """Compute all possible financial ratios from retrieved metrics.

    Builds the metrics dict expected by ratios.compute_all_ratios from
    the MetricResult list.
    """
    if not metrics:
        return []

    # Build dict: metric_name -> (current_value, prior_value)
    metrics_dict: dict[str, tuple[float | None, float | None]] = {}
    for m in metrics:
        if m.metric_name not in metrics_dict:
            metrics_dict[m.metric_name] = (m.value, m.prior_value)

    return compute_all_ratios(metrics_dict)


# ---------- Hybrid retrieval ----------

async def hybrid_retrieve(
    query: str,
    document_ids: list[UUID] | None = None,
    metric_names: list[str] | None = None,
    section_filter: str | None = None,
    top_k_chunks: int = 5,
) -> RetrievalResult:
    """Combined retrieval: vector search + structured metric lookup + ratios.

    This is the main entry point for the retrieval layer. The query pipeline
    (Phase 5) calls this after resolving jargon and expanding synonyms.

    Args:
        query: natural language question (for vector search)
        document_ids: restrict to specific documents
        metric_names: canonical metric names to look up (None = skip structured)
        section_filter: restrict vector search to a SEC section
        top_k_chunks: how many text chunks to return

    Returns:
        RetrievalResult with chunks, metrics, and computed ratios.
    """
    # Run vector search
    chunks = await search_chunks(
        query=query,
        document_ids=document_ids,
        section_filter=section_filter,
        top_k=top_k_chunks,
    )

    # Run structured metric lookup if metric names provided
    metrics: list[MetricResult] = []
    if metric_names:
        metrics = await search_metrics(
            metric_names=metric_names,
            document_ids=document_ids,
        )

    # Compute ratios from whatever metrics we found
    ratios = compute_ratios_from_metrics(metrics)

    return RetrievalResult(
        chunks=chunks,
        metrics=metrics,
        ratios=ratios,
    )
