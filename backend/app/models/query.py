"""Request/response schemas for the query endpoint."""
from uuid import UUID

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)


class CompanyResolved(BaseModel):
    """A company detected from the question and resolved against EDGAR."""
    ticker: str
    name: str
    cik: str


class FilingUsed(BaseModel):
    """A filing that was retrieved over for this query."""
    filing_id: UUID
    ticker: str
    filing_type: str           # '10-K', '10-Q', '8-K', etc.
    period_label: str | None   # 'Q3 2025', 'FY 2024'
    accession_number: str


class Citation(BaseModel):
    """A source reference for a claim in the answer."""
    source_type: str  # "text_chunk", "metric", "ratio"
    filing_id: UUID | None = None
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
    companies_resolved: list[CompanyResolved] = []
    filings_used: list[FilingUsed] = []
    metrics_used: list[dict] | None = None
    ratios_computed: list[dict] | None = None
    sentiment: SentimentResponse | None = None


class QueryJobAccepted(BaseModel):
    """Returned (with HTTP 202) when /api/query needs to ingest filings.

    The frontend should poll GET /api/query/jobs/{job_id} until status is
    'ready' or 'failed'.
    """
    job_id: str
    status: str = "processing"
    progress: str | None = None


class QueryJobStatus(BaseModel):
    """GET /api/query/jobs/{id} response."""
    job_id: str
    status: str  # 'pending' | 'processing' | 'ready' | 'failed'
    progress: str | None = None
    result: QueryResponse | None = None
    error: str | None = None
