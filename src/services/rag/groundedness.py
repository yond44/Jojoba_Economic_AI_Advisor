"""Groundedness / hallucination detection — is the answer supported?  [FEATURE]"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List

import numpy as np

from src.services.rag.embeddings import setup_embeddings

logger = logging.getLogger(__name__)
_SENT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_NUM_RE = re.compile(r"\b\d+(?:[.,]\d+)?%?\b")


@dataclass
class GroundednessReport:
    score: float
    is_grounded: bool
    supported: int
    total: int
    unsupported_sentences: List[str] = field(default_factory=list)
    unverified_numbers: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"score": round(self.score, 3), "is_grounded": self.is_grounded,
                "supported": self.supported, "total": self.total,
                "unsupported_sentences": self.unsupported_sentences[:5],
                "unverified_numbers": self.unverified_numbers[:10]}


def _split(t: str) -> List[str]:
    return [s.strip() for s in _SENT_RE.split(t) if len(s.strip()) > 15]


def _cos(a, b) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    return 0.0 if na == 0 or nb == 0 else float(np.dot(a, b) / (na * nb))


def check_groundedness(answer: str, context: str, sim_threshold: float = 0.55,
                       overall_threshold: float = 0.35) -> GroundednessReport:
    ans = _split(answer)
    ctx = _split(context)
    if not ans:
        return GroundednessReport(1.0, True, 0, 0)
    if not ctx:
        return GroundednessReport(0.0, False, 0, len(ans), unsupported_sentences=ans)
    emb = setup_embeddings()
    ctx_vecs = [np.asarray(emb.get_text_embedding(s), dtype=np.float32) for s in ctx]
    supported, unsupported = 0, []
    for s in ans:
        av = np.asarray(emb.get_text_embedding(s), dtype=np.float32)
        if max((_cos(av, cv) for cv in ctx_vecs), default=0.0) >= sim_threshold:
            supported += 1
        else:
            unsupported.append(s)
    ctx_nums = set(_NUM_RE.findall(context))
    unverified = [n for n in _NUM_RE.findall(answer) if n not in ctx_nums]
    score = supported / len(ans)
    grounded = score >= overall_threshold and not (len(unverified) > 2 and score < 0.6)
    if not grounded:
        logger.warning("⚠️ Low groundedness: score=%.2f unverified=%s", score, unverified[:5])
    return GroundednessReport(score, grounded, supported, len(ans), unsupported, unverified)
