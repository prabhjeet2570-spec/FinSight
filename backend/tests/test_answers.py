import pytest
from app.answers import AnswerEngine, SynthesisError, validate_claims
from app.config import REPO
from app.contracts import QueryRequest
from app.main import app
from app.store import Store
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    s = Store(tmp_path_factory.mktemp("corpus") / "test.db")
    s.bundle(REPO / "data/manifest.json")
    return s


def test_real_filing_calculations_have_operand_provenance(store):
    result = AnswerEngine(store).answer(
        QueryRequest(question="Apple operating margin and revenue growth", tickers=["AAPL"])
    )
    values = {c["label"]: c["display_value"] for c in result["calculations"]}
    assert values == {"Operating margin": "31.51%", "Revenue growth": "2.02%"}
    assert result["status"] == "supported"
    ids = {s["id"] for s in result["sources"]}
    assert all(set(c["operands"]) <= ids for c in result["calculations"])
    assert all(s["accession"] == "0000320193-24-000123" for s in result["sources"])


def test_cross_issuer_fiscal_calendars_disclosed(store):
    result = AnswerEngine(store).answer(
        QueryRequest(
            question="Compare Apple and Microsoft operating margin",
            tickers=["AAPL", "MSFT"],
        )
    )
    assert len(result["calculations"]) == 2
    assert any("different fiscal year ends" in x for x in result["issues"])


def test_missing_issuer_prediction_quarter_and_filter_mismatch(store):
    engine = AnswerEngine(store)
    for q in [
        "Tesla revenue",
        "Predict Apple stock price",
        "Apple Q1 revenue",
        "Apple revenue 2028",
    ]:
        r = engine.answer(QueryRequest(question=q, tickers=["AAPL"]))
        assert r["status"] == "insufficient_evidence" and not r["claims"]
    assert (
        engine.answer(QueryRequest(question="Microsoft revenue", tickers=["AAPL"]))["status"]
        == "insufficient_evidence"
    )


def test_citation_validation_rejects_fabricated_quote_id_and_number():
    src = [
        {
            "id": "s",
            "text": "Revenue increased as demand for cloud services expanded across the company.",
        }
    ]
    good = {
        "text": "Cloud services demand expanded.",
        "quote": src[0]["text"],
        "source_id": "s",
    }
    assert validate_claims({"claims": [good]}, src)[0]["source_ids"] == ["s"]
    for bad in [
        good | {"source_id": "missing"},
        good | {"quote": "An invented quote that never occurred in the supplied source."},
        good | {"text": "Revenue increased 50%."},
    ]:
        with pytest.raises(SynthesisError):
            validate_claims({"claims": [bad]}, src)


def test_narrative_source_excerpt_integrity(store):
    r = AnswerEngine(store).answer(
        QueryRequest(
            question="Apple supply chain manufacturing disruptions",
            tickers=["AAPL"],
            retrieval="bm25",
            rerank=False,
        )
    )
    assert r["claims"]
    lookup = {s["id"]: s for s in r["sources"]}
    assert all(c["quote"] in lookup[c["source_ids"][0]]["text"] for c in r["claims"])


def test_api_history_sources_and_validation(store):
    with TestClient(app) as client:
        app.state.store = store
        app.state.engine = AnswerEngine(store)
        r = client.post("/api/query", json={"question": "Apple revenue", "tickers": ["AAPL"]})
        assert r.status_code == 200
        source_id = r.json()["sources"][0]["id"]
        assert (
            client.get("/api/sources/" + source_id)
            .json()["source"]["concept"]
            .startswith("us-gaap:")
        )
        assert client.get("/api/history").json()[0]["id"] == r.json()["id"]
        assert client.post("/api/query", json={"question": "   "}).status_code == 422
        assert (
            client.post("/api/query", json={"question": "Apple revenue", "top_k": 50}).status_code
            == 422
        )
        assert client.get("/api/imports/missing").status_code == 404
        assert client.get("/api/sources/missing").status_code == 404


def test_mixed_unsupported_metric_does_not_silently_substitute(store):
    result = AnswerEngine(store).answer(
        QueryRequest(question="Apple revenue and EBITDA", tickers=["AAPL"])
    )
    assert result["status"] == "insufficient_evidence"
    assert not result["claims"]


def test_extractive_answers_do_not_quote_truncated_sentences(store):
    r = AnswerEngine(store).answer(
        QueryRequest(
            question="Apple supply chain manufacturing disruptions",
            tickers=["AAPL"],
            retrieval="bm25",
            rerank=False,
        )
    )
    assert r["claims"]
    assert all(c["text"].endswith((".", "!", "?")) for c in r["claims"])
