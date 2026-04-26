"""BM25 + retrieval-trained local embeddings, reciprocal rank fusion, optional reranking."""
import math
import re
import threading
from collections import Counter
import numpy as np
from app.config import settings

STOP = set('a an and are as at be by can company companies did do does for from how in is it its of on or that the their this to was were what which with would year fiscal annual'.split())

def tokens(text):
    return [t for t in re.findall(r'[a-z0-9]+', text.lower()) if t not in STOP and len(t) > 1]

def bm25(query, documents):
    query_terms = set(tokens(query))
    counts = [Counter(tokens(text)) for text in documents]
    lengths = [sum(c.values()) for c in counts]
    average = sum(lengths) / max(1, len(lengths))
    df = Counter(t for c in counts for t in c)
    scores = []
    for c, length in zip(counts, lengths):
        score = 0.0
        for term in query_terms:
            freq = c[term]
            idf = math.log(1 + (len(documents) - df[term] + .5) / (df[term] + .5))
            if freq:
                score += idf * freq * 2.5 / (freq + 1.5 * (.25 + .75 * length / max(average, 1)))
        scores.append(score)
    return scores

def rrf(rankings, k=60):
    scores = Counter()
    for ranking in rankings:
        for rank, key in enumerate(ranking, 1):
            scores[key] += 1 / (k + rank)
    return scores

class Encoder:
    def __init__(self):
        self._model = None
        self.lock = threading.Lock()

    def model(self):
        with self.lock:
            if self._model is None:
                from fastembed import TextEmbedding
                self._model = TextEmbedding(model_name=settings.embedding_model, cache_dir=str(settings.model_cache), threads=2)
        return self._model

    def embed(self, texts, query=False):
        model = self.model()
        method = model.query_embed if query else model.passage_embed
        result = np.asarray(list(method(texts, batch_size=32)), dtype=np.float32)
        return result / np.maximum(np.linalg.norm(result, axis=1, keepdims=True), 1e-9)

encoder = Encoder()

def build_index(store, progress=None):
    rows = [r for r in store.chunks() if r['model'] != settings.embedding_model or r['vector'] is None]
    for i in range(0, len(rows), 64):
        batch = rows[i:i+64]
        vectors = encoder.embed([r['text'] for r in batch])
        with store.connect() as db:
            db.executemany('UPDATE chunks SET vector=?,model=? WHERE id=?',
                [(v.tobytes(), settings.embedding_model, r['id']) for r,v in zip(batch,vectors)])
        if progress:
            progress(min(i+64,len(rows)),len(rows))
    return {'indexed': len(rows), 'model': settings.embedding_model}

class Retriever:
    def __init__(self, store):
        self.store = store
        self._reranker = None
        self._lock = threading.Lock()

    def search(self, question, filing_ids, section=None, mode='hybrid', top_k=5, rerank=False):
        rows = [r for r in self.store.chunks(filing_ids) if section is None or r['section'] == section]
        if not rows:
            return []
        lexical = bm25(question, [r['text'] for r in rows])
        sparse_ranks = sorted((i for i,s in enumerate(lexical) if s > 0), key=lambda i:(-lexical[i], rows[i]['id']))[:30]
        dense, dense_ranks = [0.0]*len(rows), []
        if mode != 'bm25':
            if any(r['vector'] is None or r['model'] != settings.embedding_model for r in rows):
                raise ValueError('The local embedding index is incomplete. Run the prepare command or wait for import indexing.')
            matrix = np.asarray([np.frombuffer(r['vector'],dtype=np.float32) for r in rows])
            dense = (matrix @ encoder.embed([question],query=True)[0]).tolist()
            dense_ranks = sorted(range(len(rows)),key=lambda i:(-dense[i],rows[i]['id']))[:30]
        fused = rrf([sparse_ranks,dense_ranks])
        if mode == 'bm25':
            order = sparse_ranks
        elif mode == 'dense':
            order = dense_ranks
        else:
            order = sorted(fused,key=lambda i:(-fused[i],rows[i]['id']))
        rerank_scores = {}
        if rerank and order:
            with self._lock:
                if self._reranker is None:
                    from fastembed.rerank.cross_encoder import TextCrossEncoder
                    self._reranker = TextCrossEncoder(model_name='Xenova/ms-marco-MiniLM-L-6-v2', cache_dir=str(settings.model_cache),threads=2)
            candidates = order[:15]
            rerank_scores = dict(zip(candidates,map(float,self._reranker.rerank(question,[rows[i]['text'] for i in candidates]))))
            order = sorted(candidates,key=lambda i:(-rerank_scores[i],rows[i]['id']))
        result,seen = [],set()
        for i in order:
            row=rows[i]
            # Don't fill the context window with near-duplicate overlapping chunks.
            terms=set(tokens(row['text']))
            if any(len(terms & old) / max(1,len(terms | old)) > .88 for old in seen):
                continue
            seen.add(frozenset(terms))
            result.append({k:row[k] for k in ('id','filing_id','text','section','ordinal','source_anchor','start_offset','end_offset','kind')} |
                          {'bm25_score':round(lexical[i],4),'dense_score':round(dense[i],4),'rrf_score':round(fused[i],6),
                           'rerank_score':rerank_scores.get(i)})
            if len(result) == top_k:
                break
        return result
