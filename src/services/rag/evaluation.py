"""Automated retrieval evaluation — hit@k, MRR, A/B compare.  [FEATURE]"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List

logger = logging.getLogger(__name__)


def _rr(chunks, pred: Callable) -> float:
    for i, c in enumerate(chunks):
        if pred(c):
            return 1.0 / (i + 1)
    return 0.0


def evaluate_retrieval(golden_set: List[Dict[str, Any]], retrieve_fn: Callable[[str], List]) -> Dict[str, Any]:
    rows = []
    for item in golden_set:
        chunks = retrieve_fn(item["question"])
        blob = " ".join(c.text.lower() for c in chunks)
        files = {c.file for c in chunks}
        kws = item.get("expected_keywords", [])
        found = [k for k in kws if k.lower() in blob]
        kw_hit = (len(found) / len(kws)) if kws else 1.0
        exp_file = item.get("expected_file")
        file_hit = (exp_file in files) if exp_file else True
        mrr = _rr(chunks, lambda c: any(k.lower() in c.text.lower() for k in kws) or (exp_file == c.file if exp_file else False))
        rows.append({"question": item["question"], "keyword_hit_rate": round(kw_hit, 2),
                     "file_hit": file_hit, "reciprocal_rank": round(mrr, 3),
                     "passed": kw_hit >= 0.5 and file_hit})
    n = len(rows) or 1
    report = {"total": len(rows),
              "pass_rate": round(sum(r["passed"] for r in rows) / n, 3),
              "avg_keyword_hit_rate": round(sum(r["keyword_hit_rate"] for r in rows) / n, 3),
              "mrr": round(sum(r["reciprocal_rank"] for r in rows) / n, 3),
              "details": rows}
    logger.info("🧪 Retrieval eval: pass=%.2f mrr=%.2f", report["pass_rate"], report["mrr"])
    return report


def compare_configs(golden_set, retrieve_a, retrieve_b, label_a="A", label_b="B") -> Dict[str, Any]:
    ra, rb = evaluate_retrieval(golden_set, retrieve_a), evaluate_retrieval(golden_set, retrieve_b)
    return {label_a: {"pass_rate": ra["pass_rate"], "mrr": ra["mrr"]},
            label_b: {"pass_rate": rb["pass_rate"], "mrr": rb["mrr"]},
            "delta_mrr": round(rb["mrr"] - ra["mrr"], 3),
            "winner": label_b if rb["mrr"] >= ra["mrr"] else label_a}
