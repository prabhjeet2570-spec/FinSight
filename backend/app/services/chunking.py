"""Text chunking using LangChain's RecursiveCharacterTextSplitter.

We use just this one utility from LangChain — not the whole framework.
Chunks preserve the SEC section name and synthetic page number for citations.
"""
from dataclasses import dataclass

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.services.html_extraction import ExtractedSection


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


def chunk_sections(sections: list[ExtractedSection]) -> list[TextChunk]:
    """Split each extracted section's text into chunks, preserving metadata."""
    all_chunks: list[TextChunk] = []
    chunk_idx = 0

    for sec in sections:
        if not sec.text or not sec.text.strip():
            continue

        for chunk_text in _splitter.split_text(sec.text):
            if not chunk_text.strip():
                continue
            all_chunks.append(TextChunk(
                text=chunk_text,
                page_num=sec.page_num,
                section=sec.section,
                chunk_index=chunk_idx,
            ))
            chunk_idx += 1

    return all_chunks
