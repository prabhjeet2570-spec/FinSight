"""Tests for Phase 5 query pipeline components.

Tests the parts that don't require a live Gemini API or database:
  - Classifier: response parsing, jargon enrichment
  - Generation: context assembly, citation building, confidence assessment
  - Models: request/response serialization

Run from backend dir: python -m scripts.test_query
"""
import sys
from uuid import uuid4

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


# ============================================================
# Classifier: response parsing
# ============================================================
section("classifier — response parsing")

from app.services.classifier import _parse_classifier_response

# Valid JSON
parsed = _parse_classifier_response('{"query_type": "NUMERICAL", "metrics": ["revenue"], "section_hint": "Financial Statements", "reasoning": "test"}')
check("valid JSON parse", parsed["query_type"], "NUMERICAL")
check("metrics extracted", parsed["metrics"], ["revenue"])
check("section_hint extracted", parsed["section_hint"], "Financial Statements")

# JSON wrapped in markdown code fence
parsed2 = _parse_classifier_response('```json\n{"query_type": "NARRATIVE", "metrics": [], "section_hint": "Risk Factors", "reasoning": "test"}\n```')
check("strips markdown fence", parsed2["query_type"], "NARRATIVE")
check("section from fenced JSON", parsed2["section_hint"], "Risk Factors")

# Invalid JSON -> graceful fallback
parsed3 = _parse_classifier_response("This is not valid JSON at all")
check("invalid JSON defaults to MIXED", parsed3["query_type"], "MIXED")
check("invalid JSON has empty metrics", parsed3["metrics"], [])

# Unknown query_type -> defaults to MIXED
parsed4 = _parse_classifier_response('{"query_type": "UNKNOWN_TYPE", "metrics": []}')
check("unknown type defaults to MIXED", parsed4["query_type"], "MIXED")


# ============================================================
# Classifier: jargon enrichment
# ============================================================
section("classifier — jargon enrichment")

from app.services.classifier import _apply_jargon_resolution

# "top line" -> revenue
base = {"metrics": [], "query_type": "NUMERICAL"}
enriched = _apply_jargon_resolution("How's the top line looking?", base.copy())
check_true("top line resolves to revenue", "revenue" in enriched["metrics"])

# "margins" -> special concept with multiple metrics
base2 = {"metrics": [], "query_type": "NUMERICAL"}
enriched2 = _apply_jargon_resolution("What are the margins?", base2.copy())
check_true("margins adds gross_profit", "gross_profit" in enriched2["metrics"])
check_true("margins adds revenue", "revenue" in enriched2["metrics"])
check_true("margins adds operating_income", "operating_income" in enriched2["metrics"])
check_true("margins adds net_income", "net_income" in enriched2["metrics"])
check_true("margins triggers ratios_needed", "ratios_needed" in enriched2)
check_true("gross_margin in ratios_needed", "gross_margin" in enriched2.get("ratios_needed", []))

# "bottom line" -> net_income
base3 = {"metrics": ["revenue"], "query_type": "MIXED"}
enriched3 = _apply_jargon_resolution("What's the bottom line?", base3.copy())
check_true("bottom line adds net_income", "net_income" in enriched3["metrics"])
check_true("preserves existing revenue", "revenue" in enriched3["metrics"])

# "leverage" -> special concept (debt + equity)
base4 = {"metrics": [], "query_type": "NUMERICAL"}
enriched4 = _apply_jargon_resolution("What's the leverage situation?", base4.copy())
check_true("leverage adds total_debt", "total_debt" in enriched4["metrics"])
check_true("leverage adds stockholders_equity", "stockholders_equity" in enriched4["metrics"])
check_true("leverage triggers debt_to_equity", "debt_to_equity" in enriched4.get("ratios_needed", []))

# "eps" -> eps_diluted
base5 = {"metrics": [], "query_type": "NUMERICAL"}
enriched5 = _apply_jargon_resolution("What was eps last quarter?", base5.copy())
check_true("eps resolves to eps_diluted", "eps_diluted" in enriched5["metrics"])

# No jargon -> no change
base6 = {"metrics": ["revenue"], "query_type": "NUMERICAL"}
enriched6 = _apply_jargon_resolution("Tell me about cloud infrastructure strategy", base6.copy())
check("no jargon leaves metrics unchanged", enriched6["metrics"], ["revenue"])

# "capex" -> capital_expenditures
base7 = {"metrics": [], "query_type": "NUMERICAL"}
enriched7 = _apply_jargon_resolution("How much capex?", base7.copy())
check_true("capex resolves", "capital_expenditures" in enriched7["metrics"])


# ============================================================
# Generation: context assembly
# ============================================================
section("generation — context assembly")

from app.services.generation import _build_context, _build_citations, _assess_confidence
from app.services.retrieval import ChunkResult, MetricResult, RetrievalResult
from app.finance.ratios import ComputedRatio

doc_id = uuid4()

# Build a RetrievalResult with all three types
test_result = RetrievalResult(
    chunks=[
        ChunkResult(
            chunk_id=uuid4(), document_id=doc_id,
            text="Revenue increased 15% driven by strong iPhone demand.",
            page_num=5, section="MD&A", similarity=0.85,
        ),
    ],
    metrics=[
        MetricResult(
            metric_name="revenue", value=94000.0, prior_value=85800.0,
            change_pct=9.56, unit="millions USD", period="Q3 2025",
            prior_period="Q3 2024", page_num=2, table_type="income_statement",
            document_id=doc_id,
        ),
    ],
    ratios=[
        ComputedRatio(
            name="gross_margin", display_name="Gross Margin",
            value=46.81, prior_value=44.13, change_pct=6.07,
            format="percentage", description="Percentage of revenue retained after COGS",
        ),
    ],
)

context = _build_context(test_result, {"query_type": "MIXED"})
check_true("context has metrics section", "## Extracted Metrics" in context)
check_true("context has revenue", "revenue" in context)
check_true("context has 94000" , "94000" in context)
check_true("context has ratios section", "## Computed Ratios" in context)
check_true("context has gross margin value", "46.81" in context)
check_true("context has excerpts section", "## Relevant Document Excerpts" in context)
check_true("context has chunk text", "Revenue increased 15%" in context)
check_true("context has page ref", "Page 5" in context)
check_true("context has section ref", "MD&A" in context)

# Empty result
empty_result = RetrievalResult()
empty_context = _build_context(empty_result, {"query_type": "NARRATIVE"})
check_true("empty result returns no-info message", "No relevant information" in empty_context)


# ============================================================
# Generation: citation building
# ============================================================
section("generation — citation building")

citations = _build_citations(test_result)
check("3 citations total", len(citations), 3)

metric_cites = [c for c in citations if c.source_type == "metric"]
check("1 metric citation", len(metric_cites), 1)
check("metric cite name", metric_cites[0].metric_name, "revenue")
check_true("metric cite has detail", "94000" in metric_cites[0].detail)

ratio_cites = [c for c in citations if c.source_type == "ratio"]
check("1 ratio citation", len(ratio_cites), 1)
check("ratio cite name", ratio_cites[0].metric_name, "gross_margin")
check_true("ratio cite has value", "46.81" in ratio_cites[0].detail)

chunk_cites = [c for c in citations if c.source_type == "text_chunk"]
check("1 chunk citation", len(chunk_cites), 1)
check("chunk cite page", chunk_cites[0].page_num, 5)
check("chunk cite section", chunk_cites[0].section, "MD&A")

# Empty -> no citations
empty_cites = _build_citations(RetrievalResult())
check("empty result -> 0 citations", len(empty_cites), 0)


# ============================================================
# Generation: confidence assessment
# ============================================================
section("generation — confidence assessment")

# NUMERICAL with metrics = high
conf1 = _assess_confidence(test_result, {"query_type": "NUMERICAL"})
check("NUMERICAL + metrics = high", conf1, "high")

# NUMERICAL with only chunks = medium
chunks_only = RetrievalResult(
    chunks=[ChunkResult(
        chunk_id=uuid4(), document_id=doc_id,
        text="test", page_num=1, section=None, similarity=0.6,
    )]
)
conf2 = _assess_confidence(chunks_only, {"query_type": "NUMERICAL"})
check("NUMERICAL + chunks only = medium", conf2, "medium")

# NUMERICAL with nothing = low
conf3 = _assess_confidence(RetrievalResult(), {"query_type": "NUMERICAL"})
check("NUMERICAL + nothing = low", conf3, "low")

# NARRATIVE with high similarity = high
high_sim = RetrievalResult(
    chunks=[ChunkResult(
        chunk_id=uuid4(), document_id=doc_id,
        text="test", page_num=1, section=None, similarity=0.75,
    )]
)
conf4 = _assess_confidence(high_sim, {"query_type": "NARRATIVE"})
check("NARRATIVE + sim>0.5 = high", conf4, "high")

# NARRATIVE with medium similarity
med_sim = RetrievalResult(
    chunks=[ChunkResult(
        chunk_id=uuid4(), document_id=doc_id,
        text="test", page_num=1, section=None, similarity=0.35,
    )]
)
conf5 = _assess_confidence(med_sim, {"query_type": "NARRATIVE"})
check("NARRATIVE + sim 0.3-0.5 = medium", conf5, "medium")

# SENTIMENT with both = high
conf6 = _assess_confidence(test_result, {"query_type": "SENTIMENT"})
check("SENTIMENT + metrics + chunks = high", conf6, "high")

# MIXED with both = high
conf7 = _assess_confidence(test_result, {"query_type": "MIXED"})
check("MIXED + metrics + chunks = high", conf7, "high")

# MIXED with only metrics = medium
metrics_only = RetrievalResult(
    metrics=[MetricResult(
        metric_name="revenue", value=94000.0, prior_value=None,
        change_pct=None, unit="millions USD", period=None,
        prior_period=None, page_num=None, table_type=None,
        document_id=doc_id,
    )]
)
conf8 = _assess_confidence(metrics_only, {"query_type": "MIXED"})
check("MIXED + metrics only = medium", conf8, "medium")


# ============================================================
# Models: query request/response serialization
# ============================================================
section("models — query serialization")

from app.models.query import QueryRequest, QueryResponse, Citation as CitationModel

# QueryRequest validation
req = QueryRequest(question="What was revenue?")
check("request question", req.question, "What was revenue?")
check("request doc_ids default None", req.document_ids, None)

req2 = QueryRequest(question="test", document_ids=[doc_id])
check("request with doc_ids", req2.document_ids, [doc_id])

# QueryRequest rejects empty question
try:
    QueryRequest(question="")
    check_true("empty question rejected", False, "should have raised")
except Exception:
    check_true("empty question rejected", True)

# QueryResponse serialization
resp = QueryResponse(
    answer="Revenue was $94B",
    citations=[CitationModel(source_type="metric", metric_name="revenue", detail="94000")],
    query_type="NUMERICAL",
    confidence="high",
    metrics_used=[{"name": "revenue", "value": 94000}],
    ratios_computed=None,
)
check("response answer", resp.answer, "Revenue was $94B")
check("response type", resp.query_type, "NUMERICAL")
check("response confidence", resp.confidence, "high")
check("response has 1 citation", len(resp.citations), 1)
check("response metrics_used", resp.metrics_used[0]["name"], "revenue")
check("response ratios_computed", resp.ratios_computed, None)


# ============================================================
# Summary
# ============================================================
print()
total = len(results)
passed = sum(results)
print(f"{passed}/{total} tests passed")
sys.exit(0 if passed == total else 1)
