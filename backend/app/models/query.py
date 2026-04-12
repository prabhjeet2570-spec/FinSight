"""Request/response schemas for the query endpoint."""
from uuid import UUID

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    document_ids: list[UUID] | None = None  # None = search all uploaded docs


class Citation(BaseModel):
    """A source reference for a claim in the answer."""
    source_type: str  # "text_chunk", "metric", "ratio"
    document_id: UUID | None = None
    page_num: int | None = None
    section: str | None = None
    metric_name: str | None = None
    detail: str | None = None  # e.g. "gross_margin = 46.81%"


class SentimentResponse(BaseModel):
    overall: str  # "positive", "negative", "neutral"
    positive_score: float
    negative_score: float
    neutral_score: float
    analyzed_chunks: int


class QueryResponse(BaseModel):
    answer: str
    citations: list[Citation] = []
    query_type: str  # NUMERICAL, NARRATIVE, MIXED, SENTIMENT
    confidence: str  # "high", "medium", "low"
    metrics_used: list[dict] | None = None  # key metrics referenced
    ratios_computed: list[dict] | None = None  # ratios computed for the answer
    sentiment: SentimentResponse | None = None  # FinBERT sentiment (SENTIMENT queries)
