"""Text chunking using LangChain's RecursiveCharacterTextSplitter.

We use just this one utility from LangChain — not the whole framework.
Chunks preserve page numbers and section context for citation purposes.
"""
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.services.extraction import ExtractedPage


@dataclass
class TextChunk:
    text: str
    page_num: int
    section: str | None
    chunk_index: int


# Tuned for FinBERT (512 token max) — keep chunks well under that to leave
# room for special tokens and to allow some semantic overlap.
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150

_splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
    length_function=len,
)


def chunk_pages(pages: list[ExtractedPage]) -> list[TextChunk]:
    """Split each page's text into chunks while preserving page/section metadata."""
    all_chunks: list[TextChunk] = []
    chunk_idx = 0

    for page in pages:
        if not page.text or not page.text.strip():
            continue

        page_chunks = _splitter.split_text(page.text)
        for chunk_text in page_chunks:
            if not chunk_text.strip():
                continue
            all_chunks.append(TextChunk(
                text=chunk_text,
                page_num=page.page_num,
                section=page.section,
                chunk_index=chunk_idx,
            ))
            chunk_idx += 1

    return all_chunks
