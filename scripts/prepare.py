"""Import the checked-in corpus and resume incomplete local embedding batches."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app.config import REPO, settings
from app.store import Store
from app.search import build_index

if __name__ == '__main__':
    store=Store(settings.database)
    for result in store.bundle(REPO/'data/manifest.json'):
        print(result,flush=True)
    print(build_index(store,lambda done,total: print(f'Embedding {done}/{total}',flush=True)),flush=True)
