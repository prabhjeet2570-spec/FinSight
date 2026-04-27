"""Durable single-process import worker with idempotent requests and restart recovery."""

import hashlib
import json
import threading
from uuid import uuid4

from app.contracts import Filing
from app.search import build_index


class ImportWorker:
    def __init__(self, store):
        self.store = store
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.spool = store.path.parent / "imports"
        self.spool.mkdir(parents=True, exist_ok=True)

    def submit(self, filing, content):
        key = hashlib.sha256(filing.model_dump_json().encode() + content).hexdigest()[:32]
        source = self.spool / (key + ".html")
        if not source.exists():
            temp = self.spool / (key + "-" + uuid4().hex + ".tmp")
            temp.write_bytes(content)
            temp.replace(source)
        payload = json.dumps({"filing": filing.model_dump(mode="json"), "source": str(source)})
        with self.store.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO jobs VALUES(?,?,?,?,?)",
                (key, "pending", payload, None, None),
            )
        self.wake.set()
        return self.get(key)

    def get(self, key):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT id,status,result,error FROM jobs WHERE id=?", (key,)
            ).fetchone()
        if not row:
            return None
        return dict(row) | {"result": json.loads(row["result"]) if row["result"] else None}

    def start(self):
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET status='pending' WHERE status='processing'")
        self.thread = threading.Thread(target=self.run, daemon=True, name="finsight-imports")
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=3)

    def process_one(self):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM jobs WHERE status='pending' ORDER BY rowid LIMIT 1"
            ).fetchone()
            if not row:
                return False
            db.execute(
                "UPDATE jobs SET status='processing',error=NULL WHERE id=?",
                (row["id"],),
            )
        try:
            from pathlib import Path

            payload = json.loads(row["payload"])
            source = Path(payload["source"])
            if not source.resolve().is_relative_to(self.spool.resolve()):
                raise ValueError("Invalid import staging path")
            result = self.store.ingest(Filing(**payload["filing"]), source.read_bytes())
            build_index(self.store)
            with self.store.connect() as db:
                db.execute(
                    "UPDATE jobs SET status='ready',result=? WHERE id=?",
                    (json.dumps(result), row["id"]),
                )
        except Exception as e:
            with self.store.connect() as db:
                db.execute(
                    "UPDATE jobs SET status='failed',error=? WHERE id=?",
                    (str(e)[:500], row["id"]),
                )
        return True

    def retry(self, key):
        with self.store.connect() as db:
            db.execute(
                "UPDATE jobs SET status='pending',error=NULL WHERE id=? AND status='failed'",
                (key,),
            )
        self.wake.set()
        return self.get(key)

    def run(self):
        while not self.stop.is_set():
            if not self.process_one():
                self.wake.wait(1)
                self.wake.clear()
