"""Document upload + retrieval endpoints."""
import json
import logging
import tempfile
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile

from app.config import get_settings
from app.db.connection import get_pool
from app.models.document import (
    DocumentResponse,
    DocumentStatusResponse,
    ExtractedTableResponse,
    MetricResponse,
    UploadResponse,
)
from app.services.document_processor import process_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])


@router.post("/upload", response_model=UploadResponse)
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
):
    """Upload 1-4 PDFs. Each must be <= 10MB. Total <= 40MB.

    Saves to a temp file, inserts a 'processing' document row, and kicks off
    extraction in the background. Returns document IDs immediately so the
    client can poll /status.
    """
    settings = get_settings()
    pool = await get_pool()

    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > settings.max_files:
        raise HTTPException(
            status_code=400,
            detail=f"Too many files (max {settings.max_files})",
        )

    # Read all bytes upfront so we can validate sizes before processing.
    # PDFs are small (<= 10MB each), so this is fine.
    file_data: list[tuple[str, bytes]] = []
    total_bytes = 0
    max_per_file = settings.max_file_size_mb * 1024 * 1024
    max_total = settings.max_total_size_mb * 1024 * 1024

    for f in files:
        if not f.filename or not f.filename.lower().endswith(".pdf"):
            raise HTTPException(
                status_code=400,
                detail=f"Only PDF files allowed: {f.filename}",
            )
        contents = await f.read()
        if len(contents) > max_per_file:
            raise HTTPException(
                status_code=400,
                detail=f"{f.filename} exceeds {settings.max_file_size_mb}MB limit",
            )
        total_bytes += len(contents)
        if total_bytes > max_total:
            raise HTTPException(
                status_code=400,
                detail=f"Total upload exceeds {settings.max_total_size_mb}MB limit",
            )
        file_data.append((f.filename, contents))

    # Persist files to temp storage and insert document rows
    documents: list[DocumentResponse] = []
    async with pool.acquire() as conn:
        for filename, contents in file_data:
            tmp = tempfile.NamedTemporaryFile(
                delete=False,
                suffix=".pdf",
                prefix="finsight_",
            )
            tmp.write(contents)
            tmp.close()
            tmp_path = tmp.name

            row = await conn.fetchrow(
                """
                INSERT INTO documents (filename, company, source, status)
                VALUES ($1, $2, 'upload', 'processing')
                RETURNING id, filename, company, ticker, filing_type, period,
                          fiscal_year, source, uploaded_at, page_count, status
                """,
                filename,
                "Unknown",  # placeholder until extraction detects company
            )

            documents.append(DocumentResponse(**dict(row)))

            # Schedule background processing — runs after the response is sent
            background_tasks.add_task(
                process_document,
                row["id"],
                tmp_path,
                filename,
            )

    return UploadResponse(
        documents=documents,
        message=f"Uploaded {len(documents)} document(s); processing in background",
    )


@router.get("", response_model=list[DocumentResponse])
async def list_documents():
    """List all uploaded documents (most recent first)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, filename, company, ticker, filing_type, period,
                   fiscal_year, source, uploaded_at, page_count, status
            FROM documents
            ORDER BY uploaded_at DESC
            """
        )
    return [DocumentResponse(**dict(r)) for r in rows]


@router.get("/{document_id}/status", response_model=DocumentStatusResponse)
async def get_document_status(document_id: UUID):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, status, filename, company, page_count
            FROM documents WHERE id = $1
            """,
            document_id,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentStatusResponse(**dict(row))


@router.get("/{document_id}/tables", response_model=list[ExtractedTableResponse])
async def get_document_tables(document_id: UUID):
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Make sure document exists
        exists = await conn.fetchval(
            "SELECT 1 FROM documents WHERE id = $1", document_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Document not found")

        rows = await conn.fetch(
            """
            SELECT id, page_num, table_type, period, headers, rows
            FROM extracted_tables
            WHERE document_id = $1
            ORDER BY page_num
            """,
            document_id,
        )
    return [
        ExtractedTableResponse(
            id=r["id"],
            page_num=r["page_num"],
            table_type=r["table_type"],
            period=r["period"],
            headers=json.loads(r["headers"]) if r["headers"] else None,
            rows=json.loads(r["rows"]) if r["rows"] else [],
        )
        for r in rows
    ]


@router.get("/{document_id}/metrics", response_model=list[MetricResponse])
async def get_document_metrics(document_id: UUID):
    pool = await get_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval(
            "SELECT 1 FROM documents WHERE id = $1", document_id
        )
        if not exists:
            raise HTTPException(status_code=404, detail="Document not found")

        rows = await conn.fetch(
            """
            SELECT id, metric_name, value, prior_value, change_pct, unit,
                   period, prior_period, page_num, table_type, source, verified
            FROM metrics
            WHERE document_id = $1
            ORDER BY metric_name
            """,
            document_id,
        )
    return [
        MetricResponse(
            id=r["id"],
            metric_name=r["metric_name"],
            value=float(r["value"]) if r["value"] is not None else None,
            prior_value=float(r["prior_value"]) if r["prior_value"] is not None else None,
            change_pct=float(r["change_pct"]) if r["change_pct"] is not None else None,
            unit=r["unit"],
            period=r["period"],
            prior_period=r["prior_period"],
            page_num=r["page_num"],
            table_type=r["table_type"],
            source=r["source"],
            verified=r["verified"],
        )
        for r in rows
    ]


@router.delete("/{document_id}")
async def delete_document(document_id: UUID):
    """Delete a document and all derived data (chunks, tables, metrics).

    Uses ON DELETE CASCADE so a single DELETE on documents removes everything.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM documents WHERE id = $1", document_id
        )
    # result is 'DELETE N' where N is rows affected
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Document not found")
    return {"detail": "Document deleted"}
