"""Transactional local storage. A filing is visible only after a complete commit."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.contracts import Filing
from app.ingest import PARSER_VERSION, parse_filing

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS filings(id TEXT PRIMARY KEY, metadata TEXT NOT NULL, checksum TEXT NOT NULL,
 parser_version TEXT NOT NULL, chunk_count INTEGER NOT NULL, fact_count INTEGER NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS filings_accession ON filings(json_extract(metadata,'$.accession'));
CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY, filing_id TEXT NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
 payload TEXT NOT NULL, vector BLOB, model TEXT);
CREATE INDEX IF NOT EXISTS chunks_filing ON chunks(filing_id);
CREATE TABLE IF NOT EXISTS facts(id TEXT PRIMARY KEY, filing_id TEXT NOT NULL REFERENCES filings(id) ON DELETE CASCADE, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, status TEXT NOT NULL, payload TEXT NOT NULL, result TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS queries(id TEXT PRIMARY KEY, payload TEXT NOT NULL, response TEXT NOT NULL);
"""


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def list_filings(self):
        with self.connect() as db:
            return [
                dict(
                    json.loads(r["metadata"]),
                    checksum=r["checksum"],
                    chunk_count=r["chunk_count"],
                    fact_count=r["fact_count"],
                )
                for r in db.execute("SELECT * FROM filings ORDER BY id")
            ]

    def ingest(self, filing: Filing, content: bytes):
        if len(content) > 15_000_000:
            raise ValueError("Filing exceeds the 15 MB local import limit")
        checksum = hashlib.sha256(content).hexdigest()
        with self.connect() as db:
            old = db.execute(
                "SELECT id,checksum,parser_version,metadata FROM filings WHERE id=? OR json_extract(metadata,'$.accession')=?",
                (filing.id, filing.accession),
            ).fetchone()
            if old:
                if Filing.model_validate_json(old["metadata"]).model_dump(
                    exclude={"path", "id"}
                ) != filing.model_dump(exclude={"path", "id"}):
                    raise ValueError("Filing ID already exists with different metadata")
                if old["checksum"] == checksum and old["parser_version"] == PARSER_VERSION:
                    return {"filing_id": old["id"], "cached": True}
                raise ValueError(
                    "Filing ID already exists with different content; use a new immutable ID"
                )
        chunks, facts = parse_filing(content.decode("utf-8", errors="replace"), filing)
        with self.connect() as db:
            # Recheck under the write lock: concurrent import of identical data is idempotent.
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT id,checksum,metadata FROM filings WHERE id=? OR json_extract(metadata,'$.accession')=?",
                (filing.id, filing.accession),
            ).fetchone()
            if old:
                if old["checksum"] != checksum or Filing.model_validate_json(
                    old["metadata"]
                ).model_dump(exclude={"path", "id"}) != filing.model_dump(exclude={"path", "id"}):
                    raise ValueError("Conflicting concurrent import")
                return {"filing_id": old["id"], "cached": True}
            db.execute(
                "INSERT INTO filings VALUES(?,?,?,?,?,?)",
                (
                    filing.id,
                    filing.model_dump_json(),
                    checksum,
                    PARSER_VERSION,
                    len(chunks),
                    len(facts),
                ),
            )
            db.executemany(
                "INSERT INTO chunks(id,filing_id,payload) VALUES(?,?,?)",
                [(c.id, filing.id, c.model_dump_json()) for c in chunks],
            )
            db.executemany(
                "INSERT INTO facts VALUES(?,?,?)",
                [(f.id, filing.id, f.model_dump_json()) for f in facts],
            )
        return {
            "filing_id": filing.id,
            "cached": False,
            "chunks": len(chunks),
            "facts": len(facts),
        }

    def chunks(self, filing_ids=None):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM chunks ORDER BY id").fetchall()
        return [
            dict(r, **json.loads(r["payload"]))
            for r in rows
            if filing_ids is None or r["filing_id"] in filing_ids
        ]

    def facts(self, filing_ids):
        from app.contracts import Fact

        with self.connect() as db:
            rows = db.execute("SELECT payload,filing_id FROM facts").fetchall()
        return [
            Fact.model_validate_json(r["payload"]) for r in rows if r["filing_id"] in filing_ids
        ]

    def bundle(self, manifest_path):
        path = Path(manifest_path)
        manifest = json.loads(path.read_text())
        results = []
        for entry in manifest["filings"]:
            filing = Filing(**entry)
            source = (path.parent / filing.path).resolve()
            if not source.is_relative_to(path.parent.resolve()):
                raise ValueError("Manifest source must be inside its bundle")
            content = source.read_bytes()
            if entry.get("sha256") and hashlib.sha256(content).hexdigest() != entry["sha256"]:
                raise ValueError(f"Checksum mismatch: {filing.id}")
            results.append(self.ingest(filing, content))
        return results
