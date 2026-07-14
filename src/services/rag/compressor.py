"""Context compression — keep only query-relevant sentences per chunk.  [FEATURE]"""
from __future__ import annotations

import logging
import re
from typing import List

import numpy as np

from src.services.rag.embeddings import setup_embeddings
from src.services.rag.types import RetrievedChunk

logger = logging.getLogger(__name__)
_SENT_RE = re.compile(r"(?<=[.!?])\s+|\n+")


def _sents(text: str) -> List[str]:
    parts = [s.strip() for s in _SENT_RE.split(text) if s.strip()]
    return parts or [text.strip()]


def _cos(a, b) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return 0.0 if na == 0 or nb == 0 else float(np.dot(a, b) / (na * nb))


def compress(query: str, chunks: List[RetrievedChunk], keep_ratio: float = 0.6) -> List[RetrievedChunk]:
    if not chunks:
        return []
    emb = setup_embeddings()
    qv = np.asarray(emb.get_query_embedding(query), dtype=np.float32)
    out = []
    for c in chunks:
        sents = _sents(c.text)
        if len(sents) <= 1:
            out.append(c)
            continue
        sims = [_cos(qv, np.asarray(emb.get_text_embedding(s), dtype=np.float32)) for s in sents]
        best = max(sims) if sims else 0.0
        kept = [s for s, sim in zip(sents, sims) if sim >= best * keep_ratio] or [sents[int(np.argmax(sims))]]
        out.append(RetrievedChunk(" ".join(kept), c.score, c.metadata))
    return out
