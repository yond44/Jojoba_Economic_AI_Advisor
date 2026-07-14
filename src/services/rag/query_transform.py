"""Query rewriting — clean/expand the raw question before retrieval.  [FEATURE]"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

_ABBREV = {
    r"\bbi rate\b": "Bank Indonesia interest rate",
    r"\bthe fed\b": "US Federal Reserve",
    r"\bipo\b": "initial public offering",
    r"\betf\b": "exchange traded fund",
    r"\bidx\b": "Indonesia Stock Exchange",
}
_FILLER = [r"\bplease\b", r"\bpls\b", r"\bcan you\b", r"\bcould you\b",
           r"\btell me about\b", r"\bi want to know\b", r"\btolong\b", r"\bmohon\b"]


@dataclass
class RewriteResult:
    original: str
    rewritten: str
    expansions: List[str] = field(default_factory=list)
    method: str = "heuristic"


def heuristic_rewrite(question: str, history: Optional[List[str]] = None) -> RewriteResult:
    low = question.strip().lower()
    for pat, repl in _ABBREV.items():
        low = re.sub(pat, repl, low)
    for pat in _FILLER:
        low = re.sub(pat, " ", low)
    low = re.sub(r"\s+", " ", low).strip(" ?.!,")
    if history and len(low.split()) <= 4:
        last = history[-1].strip().rstrip("?.! ")
        if last:
            low = f"{last} — {low}"
    return RewriteResult(question.strip(), low or question.strip())


def rewrite(question: str, history: Optional[List[str]] = None) -> RewriteResult:
    return heuristic_rewrite(question, history)
