# Evaluation and limitations

## Reproduce the run

Prepare the local corpus and cached models, then run:

```bash
backend/.venv/bin/python scripts/evaluate.py
```

The script overwrites `evaluation/results.json` with raw results. It exits unsuccessfully if a financial or unsupported-question contract check fails. Retrieval misses remain visible but are not a hidden acceptance threshold. The source corpus is unchanged during evaluation.

## Retrieval labels

There are 24 question/evidence-anchor cases: 16 development cases on Apple and Microsoft, and 8 held-out issuer cases on NVIDIA. Labels identify explicit source substrings and every chunk containing that anchor. They were committed before the baseline run.

These are author-curated reference anchors, not an exhaustive collection of every relevant passage. A retrieved passage may be useful without matching the narrow label. No external annotator has validated the judgments. The small sample and specific language favor lexical retrieval. Held-out issuer status means NVIDIA was not used as a development issuer; it is still a public document that was inspected to construct the test labels.

The same query, issuer filter, candidate budget, and top-five output budget are used for each method. Methods are BM25, dense MiniLM, hybrid reciprocal rank fusion, and hybrid plus cross-encoder reranking. Duplicate suppression applies to every method.

Recall is the fraction of labeled relevant chunks retrieved. MRR is the reciprocal rank of the first labeled relevant chunk. Aggregate results and per-split results are both retained. There is no LLM judge and no unsupported claim that retrieval presence proves answer accuracy.

## Current observations

| Method | Recall @ 5 | MRR @ 5 |
|---|---:|---:|
| BM25 | 1.000 | 0.958 |
| Dense | 0.917 | 0.710 |
| Hybrid | 0.979 | 0.927 |
| Hybrid + reranking | 1.000 | 0.938 |

BM25 is the strongest first-result baseline in this set. Reranking restores the hybrid pipeline's full anchor recall but uses additional inference. The dense-only miss remains in the raw report. More diverse paraphrases and independently reviewed labels are needed before selecting a pipeline for a broader corpus.

Latency is measured after model warm-up and excludes downloads, ingestion, and initial model loading. The report includes median and p95 observed query latency. These are local machine measurements, not a throughput or service availability benchmark.

## Financial and unsupported-question checks

Thirty direct fact cases and fifteen formula cases use independent constants from the bundled consolidated XBRL statements. The final run passes all 45. Fourteen questions check unavailable issuers, unavailable reporting periods, quarterly/YTD calculations, unsupported metrics, and predictions; all are declined without invented claims.

Ten extracted claim/citation pairs were checked for exact membership in their supplied source passages. This establishes citation integrity for those pairs, not completeness of the answer or truth of an arbitrary generated paraphrase. Live local-model synthesis is outside the measured run.

Unit and integration tests add synthetic coverage for scale, unit handling, segment exclusion, period alignment, zero denominators, conflicts, immutable identity, concurrent imports, persistent jobs, request validation, and source lookup. Synthetic financial fixtures are not represented as SEC facts.

The [preserved initial run](../evaluation/runs/initial.json) contains three failed financial checks. “Cost of revenue” also matched the broader “revenue” alias. The correction narrows alias matching and has an independent regression test. Those failures are retained rather than removed from the project history.

## Interpretation limits

- The same three annual documents are used for financial checks; coverage is declared and bounded.
- Evidence labels are narrow and author-curated. They are not independently reviewed gold annotations.
- Automatic abstention gates remain heuristic. No claim of calibrated confidence or universal hallucination prevention is made.
- Exact quote membership does not prove a synthesized claim is entailed by its source.
- All latency measurements depend on local hardware, cache state, and query scope.
- Filing-section heuristics and supported XBRL transformations may not cover a new issuer's document structure.
- Original/amended filings are immutable separate records. There is no general reconciliation policy across amended filings or custom segment taxonomies.
