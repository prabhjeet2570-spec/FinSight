from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentMetadata(BaseModel):
    company: str = "Unknown"
    ticker: str | None = None
    filing_type: str | None = None
    period: str | None = None
    fiscal_year: str | None = None


class DocumentResponse(BaseModel):
    id: UUID
    filename: str | None
    company: str
    ticker: str | None
    filing_type: str | None
    period: str | None
    fiscal_year: str | None
    source: str
    uploaded_at: datetime
    page_count: int | None
    status: str


class DocumentStatusResponse(BaseModel):
    id: UUID
    status: str
    filename: str | None
    company: str
    page_count: int | None


class UploadResponse(BaseModel):
    documents: list[DocumentResponse]
    message: str


class ExtractedTableRow(BaseModel):
    label: str
    values: dict[str, str | float | None]


class ExtractedTableResponse(BaseModel):
    id: UUID
    page_num: int | None
    table_type: str | None
    period: str | None
    headers: list[str] | None
    rows: list[dict]


class MetricResponse(BaseModel):
    id: UUID
    metric_name: str
    value: float | None
    prior_value: float | None
    change_pct: float | None
    unit: str | None
    period: str | None
    prior_period: str | None
    page_num: int | None
    table_type: str | None
    source: str
    verified: bool
