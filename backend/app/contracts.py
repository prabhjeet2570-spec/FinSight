"""Explicit source, financial and query contracts shared by API and evaluation."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class Filing(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$", max_length=80)
    ticker: str = Field(pattern=r"^[A-Z.]{1,10}$")
    company: str = Field(min_length=1, max_length=200)
    cik: str = Field(pattern=r"^\d{10}$")
    form: Literal["10-K", "10-K/A", "10-Q", "10-Q/A"]
    fiscal_year: int = Field(ge=1990, le=2100)
    period_end: date
    accession: str = Field(pattern=r"^\d{10}-\d{2}-\d{6}$")
    source_url: str
    path: str | None = None

    @field_validator("source_url")
    @classmethod
    def public_sec_source(cls, value):
        from urllib.parse import urlparse

        u = urlparse(value)
        if (
            u.scheme != "https"
            or u.netloc != "www.sec.gov"
            or not u.path.startswith("/Archives/edgar/data/")
        ):
            raise ValueError("Use a public SEC archive URL")
        return value


class Fact(BaseModel):
    id: str
    filing_id: str
    concept: str
    value: Decimal
    unit: str
    start: date | None = None
    end: date
    decimals: str
    context_id: str
    source_anchor: str | None = None
    dimensions: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_period(self):
        if not self.value.is_finite():
            raise ValueError("Financial facts must be finite")
        if self.start and self.start > self.end:
            raise ValueError("Start must precede end")
        return self


class Chunk(BaseModel):
    id: str
    filing_id: str
    section: str
    text: str
    ordinal: int
    start_offset: int
    end_offset: int
    source_anchor: str | None = None
    kind: Literal["passage", "table"] = "passage"


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1500)
    tickers: list[str] = Field(default_factory=list, max_length=5)
    fiscal_year: int | None = Field(default=None, ge=1990, le=2100)
    section: str | None = Field(default=None, max_length=100)
    retrieval: Literal["hybrid", "bm25", "dense"] = "hybrid"
    answer_mode: Literal["extractive", "ollama"] = "extractive"
    top_k: int = Field(default=5, ge=1, le=10)
    rerank: bool = True

    @field_validator("question")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Enter a question")
        return value.strip()

    @field_validator("tickers")
    @classmethod
    def tickers_normalized(cls, value):
        import re

        result = list(dict.fromkeys(t.strip().upper() for t in value))
        if any(not re.fullmatch(r"[A-Z.]{1,10}", t) for t in result):
            raise ValueError("Invalid ticker")
        return result
