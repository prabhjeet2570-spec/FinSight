"""FinBERT embedding service with lazy model loading.

Uses ProsusAI/finbert as a sentence encoder for finance-specific embeddings.
The model is lazy-loaded on first call to keep cold starts fast and RAM
usage low when embeddings aren't needed.

Output: 768-dimensional vectors matching the pgvector column in text_chunks.
"""
import logging
from typing import Sequence

import numpy as np

logger = logging.getLogger(__name__)

# Model state — lazy loaded
_model = None
_tokenizer = None

MODEL_NAME = "ProsusAI/finbert"
EMBEDDING_DIM = 768
MAX_LENGTH = 512  # FinBERT's max token length


def _load_model():
    """Load FinBERT model and tokenizer on first use."""
    global _model, _tokenizer
    if _model is not None:
        return

    logger.info(f"Loading FinBERT model ({MODEL_NAME})...")
    from transformers import AutoModel, AutoTokenizer

    _tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    _model = AutoModel.from_pretrained(MODEL_NAME)
    _model.eval()  # inference mode — no dropout
    logger.info("FinBERT model loaded")


def embed_texts(texts: Sequence[str], batch_size: int = 8) -> list[list[float]]:
    """Generate embeddings for a list of texts using FinBERT.

    Uses mean pooling over token embeddings (with attention mask) to
    produce a single 768-dim vector per text.

    Args:
        texts: list of strings to embed
        batch_size: number of texts to process at once (controls peak RAM)

    Returns:
        list of 768-dimensional embedding vectors (as Python lists of floats)
    """
    if not texts:
        return []

    import torch

    _load_model()

    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = list(texts[i : i + batch_size])

        inputs = _tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=MAX_LENGTH,
            return_tensors="pt",
        )

        with torch.no_grad():
            outputs = _model(**inputs)

        # Mean pooling: average token embeddings weighted by attention mask
        attention_mask = inputs["attention_mask"]
        token_embeddings = outputs.last_hidden_state
        mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
        sum_embeddings = torch.sum(token_embeddings * mask_expanded, dim=1)
        sum_mask = torch.clamp(mask_expanded.sum(dim=1), min=1e-9)
        mean_embeddings = sum_embeddings / sum_mask

        # L2 normalize for cosine similarity
        norms = torch.nn.functional.normalize(mean_embeddings, p=2, dim=1)

        batch_result = norms.numpy().tolist()
        all_embeddings.extend(batch_result)

    return all_embeddings


def embed_query(text: str) -> list[float]:
    """Embed a single query text. Convenience wrapper around embed_texts."""
    result = embed_texts([text])
    return result[0] if result else [0.0] * EMBEDDING_DIM


def is_model_loaded() -> bool:
    """Check if the FinBERT model is currently loaded in memory."""
    return _model is not None
