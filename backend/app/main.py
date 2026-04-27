"""Local API for filing evidence, financial calculations, imports and query history."""

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError

from app.answers import AnswerEngine
from app.config import REPO, settings
from app.contracts import Filing, QueryRequest
from app.import_jobs import ImportWorker
from app.search import INDEX_ID
from app.store import Store


@asynccontextmanager
async def lifespan(app):
    store = Store(settings.database)
    app.state.store = store
    app.state.engine = AnswerEngine(store)
    app.state.worker = ImportWorker(store)
    app.state.worker.start()
    yield
    app.state.worker.close()


app = FastAPI(title="FinSight Evidence API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
def health(request: Request):
    store = request.app.state.store
    with store.connect() as db:
        total = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        indexed = db.execute(
            "SELECT COUNT(*) FROM chunks WHERE vector IS NOT NULL AND model=?",
            (INDEX_ID,),
        ).fetchone()[0]
    return {
        "status": "ready" if total and indexed == total else "needs_index",
        "filings": len(store.list_filings()),
        "chunks": total,
        "indexed": indexed,
        "embedding_model": settings.embedding_model,
        "ollama_enabled": settings.allow_ollama,
    }


@app.get("/api/corpus")
def corpus(request: Request):
    filings = request.app.state.store.list_filings()
    chunks = request.app.state.store.chunks()
    return {
        "filings": filings,
        "sections": sorted({c["section"] for c in chunks}),
        "scope": "Imported public SEC filings; annual consolidated calculations only.",
    }


@app.post("/api/query")
def query(payload: QueryRequest, request: Request):
    try:
        return request.app.state.engine.answer(payload)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@app.get("/api/history")
def history(request: Request):
    with request.app.state.store.connect() as db:
        return [
            json.loads(r["response"])
            for r in db.execute("SELECT response FROM queries ORDER BY rowid DESC LIMIT 30")
        ]


@app.get("/api/sources/{source_id}")
def source(source_id: str, request: Request):
    store = request.app.state.store
    with store.connect() as db:
        row = db.execute("SELECT payload,filing_id FROM chunks WHERE id=?", (source_id,)).fetchone()
        if not row:
            row = db.execute(
                "SELECT payload,filing_id FROM facts WHERE id=?", (source_id,)
            ).fetchone()
    if not row:
        raise HTTPException(404, "Source not found")
    filing = next(f for f in store.list_filings() if f["id"] == row["filing_id"])
    return {"source": json.loads(row["payload"]), "filing": filing}


@app.post("/api/imports", status_code=202)
async def import_filing(request: Request, metadata: str = Form(...), file: UploadFile = File(...)):
    try:
        filing = Filing.model_validate_json(metadata)
    except ValidationError as e:
        raise HTTPException(422, "Invalid filing metadata: " + str(e)) from e
    if not file.filename or not file.filename.lower().endswith((".html", ".htm")):
        raise HTTPException(422, "Import a SEC inline-XBRL HTML filing")
    content = await file.read(15_000_001)
    if len(content) > 15_000_000:
        raise HTTPException(413, "Filing exceeds 15 MB")
    if b"<html" not in content[:20000].lower() and b"<ix:" not in content[:20000].lower():
        raise HTTPException(422, "The file is not supported filing HTML")
    return request.app.state.worker.submit(filing, content)


@app.get("/api/imports/{job_id}")
def job(job_id: str, request: Request):
    result = request.app.state.worker.get(job_id)
    if not result:
        raise HTTPException(404, "Import not found")
    return result


@app.post("/api/imports/{job_id}/retry")
def retry(job_id: str, request: Request):
    result = request.app.state.worker.retry(job_id)
    if not result:
        raise HTTPException(404, "Import not found")
    return result


@app.get("/api/evaluation")
def evaluation():
    path = REPO / "evaluation/results.json"
    if not path.exists():
        raise HTTPException(404, "Run the evaluation command to generate results")
    return json.loads(path.read_text())


# Serve the built UI locally with the same-origin API. No hosting service involved.
@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    root = (REPO / "frontend/dist").resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise HTTPException(404)
    if candidate.is_file():
        return FileResponse(candidate)
    if path.startswith(("api/", "assets/")) or not (root / "index.html").exists():
        raise HTTPException(404)
    return FileResponse(root / "index.html")
