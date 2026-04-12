"""Orchestrates the full processing pipeline for an uploaded document.

Pipeline:
  1. Read PDF and extract text + tables (page by page)
  2. Detect company/filing/period metadata from first page
  3. Update document row with metadata
  4. Persist text chunks (without embeddings — Phase 4 adds those)
  5. Persist extracted tables as JSONB
  6. Flatten and persist metrics
  7. Mark document as 'ready' (or 'failed' on error)
"""
import json
import logging
from uuid import UUID

import asyncpg

from app.db.connection import get_pool
from app.services.chunking import chunk_pages
from app.services.embedding import embed_texts
from app.services.extraction import extract_pdf
from app.services.metadata_detection import detect_metadata
from app.services.metric_flattening import flatten_tables

logger = logging.getLogger(__name__)


async def process_document(document_id: UUID, pdf_path: str, filename: str) -> None:
    """Run the full extraction pipeline and persist results.

    On any failure, marks the document as 'failed'. Designed to run in
    a background task — caller should not await the result for the user request.
    """
    pool = await get_pool()
    try:
        logger.info(f"Processing document {document_id} ({filename})")

        # 1. Extract
        result = extract_pdf(pdf_path)
        logger.info(
            f"Extracted {result.page_count} pages, "
            f"{len(result.all_tables)} tables from {filename}"
        )

        # 2. Detect metadata from first page
        first_page_text = result.pages[0].text if result.pages else ""
        metadata = detect_metadata(filename, first_page_text)

        # 3. Chunk text
        chunks = chunk_pages(result.pages)
        logger.info(f"Generated {len(chunks)} text chunks")

        # 4. Flatten metrics
        metrics = flatten_tables(result.all_tables)
        logger.info(f"Flattened {len(metrics)} metrics")

        # 5. Generate embeddings for text chunks (FinBERT, lazy-loaded)
        embeddings: list[list[float]] = []
        if chunks:
            chunk_texts = [c.text for c in chunks]
            logger.info(f"Generating embeddings for {len(chunk_texts)} chunks...")
            embeddings = embed_texts(chunk_texts)
            logger.info(f"Generated {len(embeddings)} embeddings")

        # 6. Persist everything in one transaction
        async with pool.acquire() as conn:
            async with conn.transaction():
                # Update document row with metadata + page count
                await conn.execute(
                    """
                    UPDATE documents
                    SET company = $1,
                        filing_type = $2,
                        period = $3,
                        page_count = $4
                    WHERE id = $5
                    """,
                    metadata.company,
                    metadata.filing_type,
                    metadata.period,
                    result.page_count,
                    document_id,
                )

                # Insert text chunks with embeddings
                if chunks:
                    from pgvector.asyncpg import register_vector
                    await register_vector(conn)

                    chunk_rows = [
                        (
                            document_id,
                            chunk.text,
                            chunk.page_num,
                            chunk.section,
                            chunk.chunk_index,
                            embeddings[i] if i < len(embeddings) else None,
                        )
                        for i, chunk in enumerate(chunks)
                    ]
                    await conn.executemany(
                        """
                        INSERT INTO text_chunks
                            (document_id, chunk_text, page_num, section, chunk_index, embedding)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        """,
                        chunk_rows,
                    )

                # Insert extracted tables
                if result.all_tables:
                    table_rows = [
                        (
                            document_id,
                            table.page_num,
                            table.table_type,
                            json.dumps(table.headers),
                            json.dumps(table.rows),
                        )
                        for table in result.all_tables
                    ]
                    await conn.executemany(
                        """
                        INSERT INTO extracted_tables
                            (document_id, page_num, table_type, headers, rows)
                        VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
                        """,
                        table_rows,
                    )

                # Insert metrics
                if metrics:
                    metric_rows = [
                        (
                            document_id,
                            m.metric_name,
                            m.value,
                            m.prior_value,
                            m.change_pct,
                            m.unit,
                            m.period,
                            m.prior_period,
                            m.page_num,
                            m.table_type,
                        )
                        for m in metrics
                    ]
                    await conn.executemany(
                        """
                        INSERT INTO metrics
                            (document_id, metric_name, value, prior_value, change_pct,
                             unit, period, prior_period, page_num, table_type)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                        """,
                        metric_rows,
                    )

                # Mark ready
                await conn.execute(
                    "UPDATE documents SET status = 'ready' WHERE id = $1",
                    document_id,
                )

        logger.info(f"Document {document_id} processed successfully")

    except Exception as e:
        logger.exception(f"Failed to process document {document_id}: {e}")
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE documents SET status = 'failed' WHERE id = $1",
                    document_id,
                )
        except Exception:
            logger.exception(f"Failed to mark document {document_id} as failed")
