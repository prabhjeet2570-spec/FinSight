"""Import the checked-in corpus and resume incomplete local embedding batches."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ["FINSIGHT_DOWNLOAD_MODELS"] = "true"
from app.config import REPO, settings
from app.search import Retriever, build_index
from app.store import Store

if __name__ == "__main__":
    store = Store(settings.database)
    for result in store.bundle(REPO / "data/manifest.json"):
        print(result, flush=True)
    print(
        build_index(store, lambda done, total: print(f"Embedding {done}/{total}", flush=True)),
        flush=True,
    )
    Retriever(store).search("manufacturing supply chain", ["aapl-2024"], rerank=True, top_k=1)
    print("Embedding and reranking models cached; normal queries need no network.", flush=True)
