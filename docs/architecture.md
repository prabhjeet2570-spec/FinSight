# Architecture and decisions

## One local application

FastAPI serves the JSON API and the built React interface on loopback. SQLite stores immutable filing metadata, text chunks, local dense vectors, XBRL facts, import jobs, and research history. There is one API process and one background import worker. No cloud database, model endpoint, analytics SDK, or deployment service is required.

The checked-in source corpus is complete public SEC filing HTML, not shortened invented summaries. A manifest pins accession, CIK, issuer, fiscal metadata, source URL, and the content hash. Python dependencies are pinned with package hashes; frontend dependencies use the npm lockfile.

## Ingestion and provenance

`Store.ingest` parses before starting the write transaction. The filing, its chunks, and its financial facts become visible in one commit. Identical bytes and metadata are idempotent. An accession cannot be silently reimported as another filing ID. Different content or metadata under the same immutable identity is a conflict.

Inline-XBRL facts retain concept, unit, value, context ID, dimensions, start/end periods, original decimal precision, and source anchor. Scale and sign transformations are explicit. Unknown numeric transformations are skipped. HTML table values never receive a guessed USD unit.

Text extraction avoids duplicating nested blocks, keeps tables as source material, and tracks detected SEC sections. Chunks retain their normalized text offsets, ordinal, kind, and available HTML anchor. These offsets describe normalized extraction rather than original HTML byte positions. Section recognition is a heading heuristic, not a universal filing-layout parser.

## Search and answer contracts

Issuer scope and reporting year are selected before retrieval. BM25 emphasizes literal financial vocabulary; MiniLM contributes semantic similarity. Reciprocal rank fusion combines rankings rather than incompatible raw score scales. The default pipeline reranks its candidate set with a local cross-encoder. All three simpler retrieval paths remain selectable.

Dense vectors are stored as float32 blobs with an index version. Incomplete or incompatible indexes produce an explicit preparation error. The encoder represents long passages in overlapping token windows and pools their embeddings, instead of truncating the remaining text. Models load from `.local/models` with `local_files_only=True` during normal operation; the preparation command enables downloads explicitly.

Near-identical candidates are suppressed before filling the context. The evidence gate checks query overlap, retrieval signals, and reranking scores. It is a bounded heuristic that can decline relevant questions or admit superficially related passages. Its scores are not calibrated confidence probabilities.

The default narrative answer extracts complete source sentences. Citation IDs resolve to stored passages, and quotes must occur exactly in the cited text. Numerical intent bypasses narrative generation and uses the structured fact contract.

## Financial correctness

The registry contains ten metrics: revenue, operating income, net income, gross profit, cost of revenue, assets, liabilities, cash and cash equivalents, operating cash flow, and research and development.

Five formulas are supported: operating margin, net margin, gross margin, operating cash flow margin, and revenue growth. Facts are selected for consolidated USD reporting. Duration metrics must span an annual reporting window; balance-sheet metrics must be instant facts. Segment facts are preserved but are not mixed into consolidated results.

Conflicting values, dimensions, units, incompatible periods, missing operands, or zero denominators cause explicit unsupported outcomes. Growth compares adjacent annual periods from the same filing. Cross-issuer results expose differing fiscal calendars; the application does not assert they cover identical calendar windows.

`Decimal` preserves arithmetic semantics. The UI formats display values separately and exposes original reported values, periods, and precision. A nested metric alias must not turn “cost of revenue” into a separate request for revenue; this has a dedicated regression check.

## Durable imports and recovery

Imports are staged locally with content-addressed job IDs, saved before processing, and polled through the API. A SQLite write lock claims one pending job. After a restart, interrupted jobs return to pending, ingestion checks immutable identity again, and indexing resumes incomplete batches. Completed jobs and query history survive process exit.

This is a single-process worker contract. Multiple API processes would require lease-based ownership and a different restart protocol. The application deliberately avoids implying support for that topology.

The import UI accepts public inline-XBRL HTML plus issuer metadata. The source URL is constrained to a SEC archive path matching CIK and accession. User-supplied file authenticity is not independently verified through a network fetch. Unsupported financial concepts remain outside the numerical registry even if their raw facts are stored.

## Optional local-model synthesis

Install and run Ollama separately, then load a model of your choice. The application never pulls or starts an Ollama model automatically.

```bash
ollama pull qwen2.5:3b
export FINSIGHT_ALLOW_OLLAMA=true
export OLLAMA_URL=http://127.0.0.1:11434
export OLLAMA_MODEL=qwen2.5:3b
backend/.venv/bin/python scripts/run.py
```

Select **Local model synthesis** in Research settings. Only loopback URLs are accepted. The adapter supplies retrieved evidence as untrusted data, requests bounded structured claims, and has no tools or execution privileges. Request time, output tokens, and response size are bounded.

A generated claim needs a known source ID, an exact supporting quote, and numerical tokens present in that quote. Invalid output is surfaced as an unsupported answer; it is not silently replaced with a success message. These checks do not prove semantic entailment. Users must inspect the evidence, and the raw response labels this limitation.

The adapter is tested with a controlled HTTP response. Live Ollama synthesis has not been scored in the checked-in evaluation. Extractive and deterministic modes are fully exercised with the real local retrieval models and public corpus.

## API and local development

| Endpoint | Purpose |
|---|---|
| `GET /health` | Corpus and vector-index readiness |
| `GET /api/corpus` | Filing metadata and available sections |
| `POST /api/query` | Evidence-backed answer, calculations, issues, and execution trail |
| `GET /api/sources/{id}` | Stored source and original filing metadata |
| `GET /api/history` | Persisted answers and original research settings |
| `POST /api/imports` | Multipart HTML and validated metadata import |
| `GET /api/imports/{id}` | Durable job state |
| `POST /api/imports/{id}/retry` | Retry an explicitly failed import |
| `GET /api/evaluation` | Checked-in raw evaluation artifact |

For frontend development, run the API and `npm --prefix frontend run dev`. Vite proxies API requests to the local backend. The built UI uses same-origin requests.
