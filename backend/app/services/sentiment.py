"""FinBERT sentiment analysis on financial text.

Uses ProsusAI/finbert with AutoModelForSequenceClassification to classify
text chunks as positive / negative / neutral. Designed for MD&A sections
of SEC filings.

The model is lazy-loaded on first call and shares the tokenizer cache with
the embedding service (same base model).
"""
import logging
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)

_sentiment_model = None
_sentiment_tokenizer = None

MODEL_NAME = "ProsusAI/finbert"
LABELS = ["positive", "negative", "neutral"]


@dataclass
class SentimentScore:
    """Sentiment scores for a single text chunk."""
    positive: float
    negative: float
    neutral: float
    label: str  # highest-scoring label
    text_preview: str  # first 120 chars for debugging


@dataclass
class AggregatedSentiment:
    """Aggregated sentiment across multiple chunks."""
    overall: str  # positive / negative / neutral
    positive_score: float  # average across chunks
    negative_score: float
    neutral_score: float
    analyzed_chunks: int
    chunk_scores: list[SentimentScore]


def _load_sentiment_model():
    global _sentiment_model, _sentiment_tokenizer
    if _sentiment_model is not None:
        return

    logger.info(f"Loading FinBERT sentiment model ({MODEL_NAME})...")
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    _sentiment_tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    _sentiment_model = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
    _sentiment_model.eval()
    logger.info("FinBERT sentiment model loaded")


def analyze_sentiment(texts: list[str], batch_size: int = 16) -> AggregatedSentiment:
    """Run FinBERT sentiment on a list of text chunks.

    Args:
        texts: list of text passages (typically MD&A chunks)
        batch_size: process this many texts at once

    Returns:
        AggregatedSentiment with per-chunk and average scores
    """
    if not texts:
        return AggregatedSentiment(
            overall="neutral",
            positive_score=0.0,
            negative_score=0.0,
            neutral_score=0.0,
            analyzed_chunks=0,
            chunk_scores=[],
        )

    import torch

    _load_sentiment_model()

    all_scores: list[SentimentScore] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]

        inputs = _sentiment_tokenizer(
            batch,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )

        with torch.no_grad():
            outputs = _sentiment_model(**inputs)

        probs = torch.nn.functional.softmax(outputs.logits, dim=-1).numpy()

        for j, text in enumerate(batch):
            scores = probs[j]
            label = LABELS[int(np.argmax(scores))]
            all_scores.append(SentimentScore(
                positive=round(float(scores[0]), 4),
                negative=round(float(scores[1]), 4),
                neutral=round(float(scores[2]), 4),
                label=label,
                text_preview=text[:120],
            ))

    avg_pos = sum(s.positive for s in all_scores) / len(all_scores)
    avg_neg = sum(s.negative for s in all_scores) / len(all_scores)
    avg_neu = sum(s.neutral for s in all_scores) / len(all_scores)

    # Overall label from averaged scores
    avg_scores = {"positive": avg_pos, "negative": avg_neg, "neutral": avg_neu}
    overall = max(avg_scores, key=avg_scores.get)

    return AggregatedSentiment(
        overall=overall,
        positive_score=round(avg_pos, 4),
        negative_score=round(avg_neg, 4),
        neutral_score=round(avg_neu, 4),
        analyzed_chunks=len(all_scores),
        chunk_scores=all_scores,
    )
