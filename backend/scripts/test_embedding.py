"""Tests for FinBERT embedding service and retrieval helpers (Phase 4).

Tests embedding generation, vector properties, and retrieval helper functions.
Note: vector search against pgvector is tested separately (needs a live DB).

Run from backend dir: python -m scripts.test_embedding
"""
import sys
import numpy as np

from app.services.embedding import embed_texts, embed_query, EMBEDDING_DIM, is_model_loaded
from app.services.retrieval import compute_ratios_from_metrics, MetricResult

PASS = "\033[92m\u2713\033[0m"
FAIL = "\033[91m\u2717\033[0m"

results = []


def check(name: str, actual, expected):
    ok = actual == expected
    results.append(ok)
    marker = PASS if ok else FAIL
    print(f"  {marker} {name}")
    if not ok:
        print(f"      expected: {expected!r}")
        print(f"      actual:   {actual!r}")


def check_true(name: str, condition: bool, detail: str = ""):
    results.append(condition)
    marker = PASS if condition else FAIL
    suffix = f" ({detail})" if detail else ""
    print(f"  {marker} {name}{suffix}")


def section(title: str):
    print(f"\n{title}")
    print("-" * len(title))


# ---------- Embedding basics ----------
section("FinBERT embedding basics")

check("model not loaded before first call", is_model_loaded(), False)

# Embed a single financial sentence
embeddings = embed_texts(["Revenue increased 15% year over year"])
check("returns 1 embedding", len(embeddings), 1)
check("embedding dim is 768", len(embeddings[0]), EMBEDDING_DIM)

check("model loaded after first call", is_model_loaded(), True)

# Verify it's a valid vector (not all zeros)
vec = np.array(embeddings[0])
check_true("not all zeros", np.any(vec != 0))
check_true("finite values", np.all(np.isfinite(vec)))

# L2 normalized (unit vector)
norm = np.linalg.norm(vec)
check_true("L2 normalized (norm ~1.0)", abs(norm - 1.0) < 0.01, f"norm={norm:.4f}")


# ---------- Batch embedding ----------
section("batch embedding")

texts = [
    "Apple reported strong iPhone sales this quarter",
    "Net income decreased due to restructuring charges",
    "The board approved a new share repurchase program",
]
batch_embeddings = embed_texts(texts)
check("batch returns 3 embeddings", len(batch_embeddings), 3)
check("all have correct dim", all(len(e) == EMBEDDING_DIM for e in batch_embeddings), True)

# Vectors should be different from each other
v1, v2, v3 = [np.array(e) for e in batch_embeddings]
sim_12 = float(np.dot(v1, v2))
sim_13 = float(np.dot(v1, v3))
check_true("different texts produce different vectors", abs(sim_12 - sim_13) > 0.001,
           f"sim(1,2)={sim_12:.3f}, sim(1,3)={sim_13:.3f}")


# ---------- Financial semantic similarity ----------
section("financial semantic similarity")

# FinBERT should understand that these finance concepts are related
finance_pairs = embed_texts([
    "Revenue grew 10% driven by strong product demand",     # 0
    "Net sales increased significantly this quarter",        # 1
    "The company faces supply chain disruption risks",       # 2
    "Risk factors include geopolitical uncertainty",          # 3
])

fp = [np.array(e) for e in finance_pairs]

# Revenue/sales should be more similar to each other than to risk factors
sim_revenue = float(np.dot(fp[0], fp[1]))
sim_cross = float(np.dot(fp[0], fp[2]))
check_true(
    "revenue sentences more similar than revenue vs risk",
    sim_revenue > sim_cross,
    f"revenue-sales={sim_revenue:.3f}, revenue-risk={sim_cross:.3f}",
)

sim_risk = float(np.dot(fp[2], fp[3]))
check_true(
    "risk sentences more similar than risk vs revenue",
    sim_risk > sim_cross,
    f"risk-risk={sim_risk:.3f}, risk-revenue={sim_cross:.3f}",
)


# ---------- embed_query convenience ----------
section("embed_query")

q = embed_query("What is Apple's gross margin?")
check("returns list", isinstance(q, list), True)
check("correct dim", len(q), EMBEDDING_DIM)
q_norm = np.linalg.norm(np.array(q))
check_true("L2 normalized", abs(q_norm - 1.0) < 0.01)


# ---------- Empty input ----------
section("edge cases")

empty = embed_texts([])
check("empty input returns empty", empty, [])


# ---------- Ratio computation from MetricResults ----------
section("compute_ratios_from_metrics")

from uuid import uuid4
doc_id = uuid4()

mock_metrics = [
    MetricResult(metric_name="revenue", value=94000.0, prior_value=85800.0,
                 change_pct=9.56, unit="millions USD", period="2025",
                 prior_period="2024", page_num=2, table_type="income_statement",
                 document_id=doc_id),
    MetricResult(metric_name="gross_profit", value=44000.0, prior_value=38800.0,
                 change_pct=13.4, unit="millions USD", period="2025",
                 prior_period="2024", page_num=2, table_type="income_statement",
                 document_id=doc_id),
    MetricResult(metric_name="net_income", value=23400.0, prior_value=21400.0,
                 change_pct=9.3, unit="millions USD", period="2025",
                 prior_period="2024", page_num=2, table_type="income_statement",
                 document_id=doc_id),
    MetricResult(metric_name="operating_income", value=30000.0, prior_value=25000.0,
                 change_pct=20.0, unit="millions USD", period="2025",
                 prior_period="2024", page_num=2, table_type="income_statement",
                 document_id=doc_id),
]

ratios = compute_ratios_from_metrics(mock_metrics)
ratio_names = {r.name for r in ratios}
check_true("gross_margin computed", "gross_margin" in ratio_names, f"got {ratio_names}")
check_true("operating_margin computed", "operating_margin" in ratio_names)
check_true("net_margin computed", "net_margin" in ratio_names)

gm = next(r for r in ratios if r.name == "gross_margin")
check("gross_margin = 46.81%", gm.value, 46.81)

# Empty metrics -> empty ratios
empty_ratios = compute_ratios_from_metrics([])
check("empty metrics -> no ratios", len(empty_ratios), 0)


# ---------- Summary ----------
print()
total = len(results)
passed = sum(results)
print(f"{passed}/{total} tests passed")
sys.exit(0 if passed == total else 1)
