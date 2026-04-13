"""Hybrid retrieval: vector search + structured metric lookup.

Combines two retrieval paths:
  1. Vector search — embed the query with FinBERT, find similar text chunks
     in pgvector using cosine similarity. Best for narrative questions
     ("what did management say about AI?").
  2. Structured lookup — search the metrics table by canonical metric name
     with synonym expansion. Best for numerical questions ("what was revenue?").

Both paths are scoped to a list of filing_ids — the caller (filing_resolver,
Phase 10) decides which filings the query should run over.
"""
import logging
from dataclasses import dataclass, field
from uuid import UUID

from app.db.connection import get_pool
from app.finance.ratios import compute_all_ratios, ComputedRatio
from app.services.embedding import embed_query

logger = logging.getLogger(__name__)


@dataclass
class ChunkResult:
    """A text chunk retrieved via vector similarity."""
    chunk_id: UUID
    filing_id: UUID
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
    filing_id: UUID

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
    filing_ids: list[UUID] | None = None,
    section_filter: str | None = None,
    top_k: int = 5,
) -> list[ChunkResult]:
    """Find the most similar text chunks to a query using pgvector.

    Embeds the query with FinBERT, then finds nearest neighbors in the
    text_chunks table using cosine distance.

    Args:
        query: natural language question
        filing_ids: restrict to specific filings (None = search all)
        section_filter: restrict to a SEC filing section (e.g., "MD&A")
        top_k: number of results to return
    """
    pool = await get_pool()
    query_embedding = embed_query(query)

    conditions = ["tc.embedding IS NOT NULL"]
    params: list = [query_embedding, top_k]
    param_idx = 3  # $1 = embedding, $2 = top_k

    if filing_ids:
        placeholders = ", ".join(f"${param_idx + i}" for i in range(len(filing_ids)))
        conditions.append(f"tc.filing_id IN ({placeholders})")
        params.extend(filing_ids)
        param_idx += len(filing_ids)

    if section_filter:
        conditions.append(f"tc.section = ${param_idx}")
        params.append(section_filter)
        param_idx += 1

    where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT tc.id, tc.filing_id, tc.chunk_text, tc.page_num, tc.section,
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
            filing_id=row["filing_id"],
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
    filing_ids: list[UUID] | None = None,
) -> list[MetricResult]:
    """Look up metrics by canonical name.

    Searches the metrics table for exact matches on metric_name.
    The caller should resolve jargon and expand synonyms before calling this.

    Args:
        metric_names: canonical metric names to search for
        filing_ids: restrict to specific filings (None = search all)
    """
    if not metric_names:
        return []

    pool = await get_pool()

    conditions = []
    params: list = []
    param_idx = 1

    placeholders = ", ".join(f"${param_idx + i}" for i in range(len(metric_names)))
    conditions.append(f"m.metric_name IN ({placeholders})")
    params.extend(metric_names)
    param_idx += len(metric_names)

    if filing_ids:
        f_placeholders = ", ".join(f"${param_idx + i}" for i in range(len(filing_ids)))
        conditions.append(f"m.filing_id IN ({f_placeholders})")
        params.extend(filing_ids)
        param_idx += len(filing_ids)

    where_clause = " AND ".join(conditions)

    sql = f"""
        SELECT m.metric_name, m.value, m.prior_value, m.change_pct, m.unit,
               m.period, m.prior_period, m.page_num, m.table_type, m.filing_id
        FROM metrics m
        JOIN filings f ON m.filing_id = f.id
        WHERE {where_clause}
        ORDER BY m.metric_name, f.filing_date ASC
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
            filing_id=row["filing_id"],
        )
        for row in rows
    ]


# ---------- Table search ----------

async def search_tables(
    query: str,
    filing_ids: list[UUID] | None = None,
    max_tables: int = 3,
) -> list[ChunkResult]:
    """Search extracted HTML tables by keyword matching.

    Converts matching tables into ChunkResult objects so they flow through
    the same context-building pipeline as text chunks. Useful for data
    that lives in tables (e.g., compensation tables in DEF 14A) that
    vector search over text chunks might miss.
    """
    if not filing_ids:
        return []

    # Extract keywords from the query (simple: words > 3 chars, lowered)
    stop_words = {
        "what", "which", "where", "when", "does", "that", "this", "have",
        "from", "their", "about", "with", "they", "been", "were", "will",
        "much", "many", "some", "than", "them", "into", "also", "most",
        "last", "how", "the", "and", "for", "are", "but", "not", "you",
    }
    words = [
        w.strip("?.,!\"'") for w in query.lower().split()
        if len(w.strip("?.,!\"'")) > 2 and w.strip("?.,!\"'") not in stop_words
    ]
    if not words:
        return []

    pool = await get_pool()

    f_placeholders = ", ".join(f"${i}" for i in range(1, len(filing_ids) + 1))
    params: list = list(filing_ids)

    # Build keyword match: rows::text matches ANY keyword (case-insensitive)
    keyword_conditions = []
    for w in words:
        idx = len(params) + 1
        keyword_conditions.append(f"(rows::text ILIKE '%' || ${idx} || '%' OR headers::text ILIKE '%' || ${idx} || '%')")
        params.append(w)

    keyword_clause = " OR ".join(keyword_conditions)

    sql = f"""
        SELECT id, filing_id, headers, rows, page_num
        FROM extracted_tables
        WHERE filing_id IN ({f_placeholders})
          AND ({keyword_clause})
        LIMIT {max_tables}
    """

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)

    results: list[ChunkResult] = []
    for row in rows:
        # Convert table to readable text
        import json
        headers = row["headers"] if isinstance(row["headers"], list) else json.loads(row["headers"]) if row["headers"] else []
        table_rows = row["rows"] if isinstance(row["rows"], list) else json.loads(row["rows"]) if row["rows"] else []

        lines = []
        if headers:
            lines.append(" | ".join(str(h) for h in headers))
            lines.append("-" * 40)
        for tr in table_rows:
            if isinstance(tr, list):
                lines.append(" | ".join(str(cell) for cell in tr))

        if not lines:
            continue

        text = "[Table]\n" + "\n".join(lines)

        results.append(ChunkResult(
            chunk_id=row["id"],
            filing_id=row["filing_id"],
            text=text,
            page_num=row["page_num"] or 0,
            section="Table",
            similarity=0.5,  # not a vector match, fixed score
        ))

    if results:
        logger.info(f"Table search found {len(results)} matching tables")

    return results


# ---------- Ratio computation from retrieved metrics ----------

def compute_ratios_from_metrics(metrics: list[MetricResult]) -> list[ComputedRatio]:
    """Compute all possible financial ratios from retrieved metrics.

    When metrics come from multiple filings (multi-company query), ratios
    are computed per-filing so each company gets its own set of ratios
    tagged with the filing_id.
    """
    if not metrics:
        return []

    # Group metrics by filing_id so ratios are per-company
    from collections import defaultdict
    by_filing: dict[UUID, dict[str, tuple[float | None, float | None]]] = defaultdict(dict)
    for m in metrics:
        if m.metric_name not in by_filing[m.filing_id]:
            by_filing[m.filing_id][m.metric_name] = (m.value, m.prior_value)

    all_ratios: list[ComputedRatio] = []
    for filing_id, metrics_dict in by_filing.items():
        for r in compute_all_ratios(metrics_dict):
            r.filing_id = filing_id
            all_ratios.append(r)

    return all_ratios


# ---------- Hybrid retrieval ----------

async def hybrid_retrieve(
    query: str,
    filing_ids: list[UUID] | None = None,
    metric_names: list[str] | None = None,
    section_filter: str | None = None,
    top_k_chunks: int = 5,
) -> RetrievalResult:
    """Combined retrieval: vector search + structured metric lookup + ratios.

    Main entry point for the retrieval layer. The query pipeline calls this
    after resolving jargon, expanding synonyms, and resolving filings.

    Args:
        query: natural language question (for vector search)
        filing_ids: restrict to specific filings (set by filing_resolver)
        metric_names: canonical metric names to look up (None = skip structured)
        section_filter: restrict vector search to a SEC section
        top_k_chunks: how many text chunks to return
    """
    chunks = await search_chunks(
        query=query,
        filing_ids=filing_ids,
        section_filter=section_filter,
        top_k=top_k_chunks,
    )

    # If section filter yielded no results, retry without it
    if not chunks and section_filter:
        logger.info(f"No chunks found with section='{section_filter}', retrying without filter")
        chunks = await search_chunks(
            query=query,
            filing_ids=filing_ids,
            section_filter=None,
            top_k=top_k_chunks,
        )

    metrics: list[MetricResult] = []
    if metric_names:
        metrics = await search_metrics(
            metric_names=metric_names,
            filing_ids=filing_ids,
        )

    ratios = compute_ratios_from_metrics(metrics)

    # Search extracted tables for keywords from the query.
    # This catches data in HTML tables (e.g., compensation tables in DEF 14A)
    # that text chunks may reference but don't contain as numbers.
    table_chunks = await search_tables(query=query, filing_ids=filing_ids)
    if table_chunks:
        chunks.extend(table_chunks)

    return RetrievalResult(
        chunks=chunks,
        metrics=metrics,
        ratios=ratios,
    )
