"""
Retrieval — hybrid (BM25 + dense), metadata filtering, adaptive top_k, fusion,
and the retrieve_advanced() orchestration (rewrite → hybrid → rerank → compress).
================================================================================
FEATURES: Hybrid search, Metadata filtering, Adaptive top_k (+ retrieval caching).

retrieve_advanced() is what the engine calls. It is CACHED (reusing the same
TTLLRUCache the rest of the RAG uses) so repeated/similar questions skip the
expensive BM25+rerank+compress work — this is how the upgrade keeps using your
existing cache infrastructure rather than bypassing it.
"""
from __future__ import annotations

import logging
import math
import re
from collections import Counter
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

import src.services.rag.compressor as compressor
import src.services.rag.query_transform as query_transform
import src.services.rag.reranker as reranker
from src.services.rag.cache import TTLLRUCache, _hash_query
from src.services.rag.config import (
    ADAPTIVE_TOP_K, CACHE_TTL, COMPRESSION_ENABLED, HYBRID_ALPHA, HYBRID_ENABLED,
    QUERY_REWRITE_ENABLED, RERANK_ENABLED, SIMILARITY_TOP_K,
)
from src.services.rag.embeddings import setup_embeddings
from src.services.rag.types import RetrievedChunk
from src.services.rag.vector_store import all_documents, dense_search

logger = logging.getLogger(__name__)
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_retrieval_cache = TTLLRUCache(max_size=256, ttl=CACHE_TTL)


def _tok(t: str) -> List[str]:
    return _TOKEN_RE.findall(t.lower())


class BM25:
    def __init__(self, corpus: List[Dict[str, Any]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = corpus
        self.toks = [_tok(c["text"]) for c in corpus]
        self.dl = [len(t) for t in self.toks]
        self.avgdl = (sum(self.dl) / len(self.dl)) if self.dl else 0.0
        self.freqs = [Counter(t) for t in self.toks]
        df: Counter = Counter()
        for t in self.toks:
            for term in set(t):
                df[term] += 1
        n = len(corpus)
        self.idf = {term: math.log(1 + (n - d + 0.5) / (d + 0.5)) for term, d in df.items()}

    def search(self, query: str, top_k: int, allowed: Optional[set] = None) -> List[Tuple[int, float]]:
        qterms = _tok(query)
        scored = []
        for i, freq in enumerate(self.freqs):
            if allowed is not None and i not in allowed:
                continue
            s, dl = 0.0, self.dl[i] or 1
            for term in qterms:
                if term not in freq:
                    continue
                tf = freq[term]
                s += self.idf.get(term, 0.0) * (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1)))
            if s > 0:
                scored.append((i, s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


@lru_cache(maxsize=1)
def _bm25() -> BM25:
    corpus = all_documents()
    logger.info("🔤 BM25 index built over %d chunks", len(corpus))
    return BM25(corpus)


def invalidate_bm25() -> None:
    _bm25.cache_clear()
    _retrieval_cache.clear()


def adaptive_top_k(query: str, base_k: int) -> int:
    words = len(query.split())
    specific = bool(re.search(r"[A-Z]{2,5}\b|\b\d{4}\b|\d+%", query))
    if words <= 4 and not specific:
        return min(base_k * 2, 20)
    if words >= 14 or specific:
        return max(3, base_k - 2)
    return base_k


def _norm(scores: List[float]) -> List[float]:
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return [1.0] * len(scores)
    return [(s - lo) / (hi - lo) for s in scores]


def _weighted_fuse(dense: List[RetrievedChunk], sparse: List[RetrievedChunk], alpha: float) -> List[RetrievedChunk]:
    dn, sn = _norm([c.score for c in dense]), _norm([c.score for c in sparse])
    bucket: Dict[str, Tuple[float, RetrievedChunk]] = {}
    for c, n in zip(dense, dn):
        bucket[c.text[:120]] = (alpha * n, c)
    for c, n in zip(sparse, sn):
        k = c.text[:120]
        prev = bucket.get(k, (0.0, c))
        bucket[k] = (prev[0] + (1 - alpha) * n, prev[1])
    fused = [RetrievedChunk(v[1].text, v[0], v[1].metadata) for v in bucket.values()]
    fused.sort(key=lambda c: c.score, reverse=True)
    return fused


def retrieve(query: str, filters: Optional[Dict[str, Any]] = None,
             top_k: Optional[int] = None, use_hybrid: Optional[bool] = None) -> List[RetrievedChunk]:
    """Hybrid (or dense-only) retrieval with metadata filter + adaptive top_k."""
    use_hybrid = HYBRID_ENABLED if use_hybrid is None else use_hybrid
    base_k = top_k or SIMILARITY_TOP_K
    k = adaptive_top_k(query, base_k) if ADAPTIVE_TOP_K else base_k

    emb = setup_embeddings().get_query_embedding(query)
    dense = [RetrievedChunk(d["text"], d["score"], d["metadata"])
             for d in dense_search(emb, top_k=k, where=filters)]
    if not use_hybrid:
        return dense[:k]

    bm = _bm25()
    allowed = None
    if filters:
        allowed = {i for i, d in enumerate(bm.docs)
                   if all(d["metadata"].get(f) == v for f, v in filters.items())}
    sparse = [RetrievedChunk(bm.docs[i]["text"], sc, bm.docs[i]["metadata"])
              for i, sc in bm.search(query, top_k=k, allowed=allowed)]
    fused = _weighted_fuse(dense, sparse, HYBRID_ALPHA)
    if fused and fused[0].score < 0.15 and k < 16:
        return retrieve(query, filters, top_k=min(k * 2, 16), use_hybrid=use_hybrid)
    return fused[:k]


def retrieve_advanced(question: str, filters: Optional[Dict[str, Any]] = None,
                      history: Optional[List[str]] = None) -> Dict[str, Any]:
    """rewrite → hybrid retrieve → rerank → compress. Cached per (query, filters).

    Returns {"context", "sources", "search_query", "chunks"}.
    """
    cache_key = _hash_query(f"{question}|{filters}")
    cached = _retrieval_cache.get(cache_key)
    if cached is not None:
        return {**cached, "from_cache": True}

    search_query = query_transform.rewrite(question, history).rewritten if QUERY_REWRITE_ENABLED else question
    chunks = retrieve(search_query, filters=filters)
    if RERANK_ENABLED and chunks:
        chunks = reranker.rerank(search_query, chunks)
    if COMPRESSION_ENABLED and chunks:
        chunks = compressor.compress(search_query, chunks)

    context = "\n\n".join(c.text for c in chunks)
    sources = [{
        "text": c.text[:300], "score": round(c.score, 4),
        "chunk_type": c.chunk_type, "file": c.file,
        "category": c.metadata.get("category", ""), "topic": c.metadata.get("topic", ""),
    } for c in chunks]

    result = {"context": context, "sources": sources, "search_query": search_query}
    _retrieval_cache.set(cache_key, result)
    return {**result, "from_cache": False}
