"""Reproduce retrieval baselines and end-to-end financial/evidence contract checks."""

import hashlib
import json
import platform
import statistics
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.answers import AnswerEngine
from app.config import REPO, settings
from app.contracts import QueryRequest
from app.financial import METRICS
from app.search import Retriever
from app.store import Store


def fingerprint(paths):
    h = hashlib.sha256()
    for path in sorted(paths):
        h.update(str(path.relative_to(REPO)).encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def evaluate():
    store = Store(settings.database)
    retriever = Retriever(store)
    engine = AnswerEngine(store)
    labels = json.loads((REPO / "evaluation/retrieval-cases.json").read_text())["cases"]
    results = {
        "scope": "Curated local evaluation on three public filings. Evidence anchors are author-labeled, not exhaustive judgments. NVIDIA is held out from development. Extractive and deterministic modes are evaluated; live local-model synthesis is not scored.",
        "corpus": {
            "filings": len(store.list_filings()),
            "chunks": len(store.chunks()),
            "sha256": fingerprint([REPO / "data/manifest.json"]),
        },
        "models": {
            "embedding": settings.embedding_model,
            "reranker": "Xenova/ms-marco-MiniLM-L-6-v2",
        },
        "environment": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "git_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=REPO, text=True
        ).strip(),
        "source_sha256": fingerprint(
            list((REPO / "backend/app").glob("*.py")) + [REPO / "scripts/evaluate.py"]
        ),
        "labels_sha256": fingerprint(
            list((REPO / "evaluation").glob("*labels.json"))
            + [REPO / "evaluation/retrieval-cases.json"]
        ),
        "retrieval": {},
        "financial": {"passed": 0, "total": 0, "failures": []},
        "abstention": {"passed": 0, "total": 0, "failures": []},
        "citation": {"passed": 0, "total": 0},
        "cases": [],
    }
    # Warm every model once. Latencies below exclude model download and initialization.
    retriever.search("supply chain manufacturing", ["aapl-2024"], rerank=True)
    for method, mode, rerank in [
        ("bm25", "bm25", False),
        ("dense", "dense", False),
        ("hybrid", "hybrid", False),
        ("hybrid_reranked", "hybrid", True),
    ]:
        outcomes = []
        for case in labels:
            t = time.perf_counter()
            hits = retriever.search(
                case["question"], [case["filing_id"]], mode=mode, top_k=5, rerank=rerank
            )
            elapsed = (time.perf_counter() - t) * 1000
            ids = [h["id"] for h in hits]
            gold = set(case["relevant_ids"])
            ranks = [i + 1 for i, sid in enumerate(ids) if sid in gold]
            recall = len(gold & set(ids)) / len(gold)
            mrr = 1 / min(ranks) if ranks else 0
            outcome = {
                "id": case["id"],
                "question": case["question"],
                "split": case["split"],
                "method": method,
                "retrieved": ids,
                "expected": sorted(gold),
                "recall": recall,
                "mrr": mrr,
                "elapsed_ms": round(elapsed, 2),
                "scores": hits,
            }
            results["cases"].append(outcome)
            outcomes.append(outcome)
        latency = sorted(o["elapsed_ms"] for o in outcomes)
        results["retrieval"][method] = {
            "cases": len(outcomes),
            "recall_at_5": statistics.mean(o["recall"] for o in outcomes),
            "mrr_at_5": statistics.mean(o["mrr"] for o in outcomes),
            "hit_count": sum(o["mrr"] > 0 for o in outcomes),
            "latency_median_ms": statistics.median(latency),
            "latency_p95_ms": latency[min(len(latency) - 1, int(0.95 * len(latency)))],
            "failures": [
                {"id": o["id"], "question": o["question"], "retrieved": o["retrieved"]}
                for o in outcomes
                if not o["mrr"]
            ],
            "splits": {
                split: {
                    "cases": sum(o["split"] == split for o in outcomes),
                    "recall_at_5": statistics.mean(
                        o["recall"] for o in outcomes if o["split"] == split
                    ),
                    "mrr_at_5": statistics.mean(o["mrr"] for o in outcomes if o["split"] == split),
                }
                for split in ("development", "held_out_issuer")
            },
        }
        print(
            method,
            {
                k: v
                for k, v in results["retrieval"][method].items()
                if k not in ("failures", "splits")
            },
            flush=True,
        )
    expected = json.loads((REPO / "evaluation/financial-labels.json").read_text())["companies"]
    for ticker, values in expected.items():
        for metric, (label, _) in METRICS.items():
            r = engine.answer(
                QueryRequest(question=f"{ticker} {label}", tickers=[ticker]), persist=False
            )
            got = [s["value"] for s in r["sources"] if s["type"] == "fact"]
            passed = (
                bool(got)
                and Decimal(got[0]) == Decimal(values[metric])
                and r["status"] == "supported"
            )
            results["financial"]["total"] += 1
            results["financial"]["passed"] += passed
            if not passed:
                results["financial"]["failures"].append(
                    {
                        "ticker": ticker,
                        "metric": metric,
                        "expected": values[metric],
                        "actual": got,
                        "status": r["status"],
                    }
                )
            results["cases"].append(
                {
                    "kind": "financial_fact",
                    "ticker": ticker,
                    "metric": metric,
                    "passed": passed,
                    "response": r,
                }
            )
        revenue = Decimal(values["revenue"])
        formulas = {
            "Operating margin": Decimal(values["operating_income"]) / revenue * 100,
            "Net margin": Decimal(values["net_income"]) / revenue * 100,
            "Gross margin": Decimal(values["gross_profit"]) / revenue * 100,
            "Operating cash flow margin": Decimal(values["operating_cash_flow"]) / revenue * 100,
            "Revenue growth": (revenue - Decimal(values["prior_revenue"]))
            / Decimal(values["prior_revenue"])
            * 100,
        }
        for label, value in formulas.items():
            question = f"{ticker} " + label.replace(
                "Operating cash flow margin", "cash flow margin"
            )
            r = engine.answer(QueryRequest(question=question, tickers=[ticker]), persist=False)
            calc = next((c for c in r["calculations"] if c["label"] == label), None)
            passed = calc is not None and abs(Decimal(calc["value"]) - value) <= Decimal(".000001")
            results["financial"]["total"] += 1
            results["financial"]["passed"] += passed
            if not passed:
                results["financial"]["failures"].append(
                    {"ticker": ticker, "formula": label, "expected": str(value), "actual": calc}
                )
            results["cases"].append(
                {
                    "kind": "financial_formula",
                    "ticker": ticker,
                    "formula": label,
                    "passed": passed,
                    "response": r,
                }
            )
    unsupported = [
        "Tesla revenue",
        "Apple revenue 2028",
        "Apple Q1 revenue",
        "Microsoft quarterly operating margin",
        "Apple year-to-date revenue",
        "Predict Apple stock price next year",
        "Should I buy NVIDIA shares?",
        "Apple EBITDA",
        "Microsoft earnings per share",
        "Apple revenue and EBITDA",
        "NVIDIA free cash flow",
        "Apple stock price tomorrow",
        "Apple revenue 1999",
        "Apple operating margin 2026",
    ]
    for question in unsupported:
        r = engine.answer(
            QueryRequest(question=question, tickers=["AAPL", "MSFT", "NVDA"]), persist=False
        )
        passed = r["status"] == "insufficient_evidence" and not r["claims"]
        results["abstention"]["total"] += 1
        results["abstention"]["passed"] += passed
        if not passed:
            results["abstention"]["failures"].append({"question": question, "response": r})
        results["cases"].append(
            {"kind": "abstention", "question": question, "passed": passed, "response": r}
        )
    for question, ticker in [
        ("What supply chain manufacturing disruption risks does Apple disclose?", "AAPL"),
        ("What is Microsoft OpenAI Azure partnership?", "MSFT"),
        ("What foundries and manufacturing suppliers does NVIDIA depend on?", "NVDA"),
    ]:
        r = engine.answer(QueryRequest(question=question, tickers=[ticker]), persist=False)
        lookup = {s["id"]: s for s in r["sources"]}
        for claim in r["claims"]:
            passed = (
                all(sid in lookup for sid in claim["source_ids"])
                and claim["quote"] in lookup[claim["source_ids"][0]]["text"]
            )
            results["citation"]["total"] += 1
            results["citation"]["passed"] += passed
        results["cases"].append({"kind": "citation", "question": question, "response": r})
    path = REPO / "evaluation/results.json"
    path.write_text(json.dumps(results, indent=2) + "\n")
    for key in ("financial", "abstention", "citation"):
        print(key, results[key], flush=True)
    # Misses remain in the report; retrieval results are not an acceptance threshold.
    if (
        results["financial"]["passed"] != results["financial"]["total"]
        or results["abstention"]["passed"] != results["abstention"]["total"]
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(evaluate())
