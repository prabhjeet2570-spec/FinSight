# FinSight API

The local FastAPI application serves the built interface, evidence queries, filing imports, and persistent history. See the [main setup instructions](../README.md#try-the-complete-local-workflow).

```bash
.venv/bin/python -m pytest
```

Run API commands from the repository root:

```bash
backend/.venv/bin/python scripts/prepare.py
backend/.venv/bin/python scripts/run.py
```

One API process owns one durable import worker. SQLite and cached ONNX models live in `.local/`. Financial arithmetic is deterministic, with explicit units, periods, and operand references. Numerical intent does not call the local language model.

[Architecture and API contracts](../docs/architecture.md) · [Evaluation methodology](../docs/evaluation.md)
