"""
RAG retrieval evaluation — legacy metric-based checks plus RAGAS-based checks
in one module, since src/services/rag/__init__.py imports both styles from
this single file (`evaluate_retrieval`, `compare_configs` for the legacy
side; the RAGAS functions below are used directly where needed).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Callable

from datasets import Dataset
from ragas import evaluate
from ragas.metrics import (
    context_recall,
    context_precision,
    faithfulness,
    answer_relevancy,
)
from ragas.llms import LangchainLLMWrapper
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


# ============================================================================
# Legacy metric-based evaluation (pass_rate / MRR)
# ----------------------------------------------------------------------------
# Reconstructed from the golden_set / retrieve_fn interface already used
# elsewhere in this file (item["question"], item["expected_file"],
# item["expected_keywords"], chunk.text, chunk.file) and the "pass_rate" /
# "mrr" keys that combined_evaluation() expects back. Review the pass/fail
# rule below against what your original implementation actually did, in case
# it scored things differently.
# ============================================================================

def _chunk_matches(chunk, item: Dict[str, Any]) -> bool:
    """A retrieved chunk counts as a 'hit' if it matches the golden item's
    expected file, or (when no expected_file is given) contains one of the
    expected keywords."""
    if "expected_file" in item:
        return getattr(chunk, "file", None) == item["expected_file"]
    if "expected_keywords" in item:
        text = getattr(chunk, "text", "").lower()
        return any(k.lower() in text for k in item["expected_keywords"])
    return False


def evaluate_retrieval(
    golden_set: List[Dict[str, Any]],
    retrieve_fn: Callable[[str], List],
) -> Dict[str, Any]:
    """
    Evaluate a retrieval function against a golden set using two metrics:

      pass_rate — fraction of queries where AT LEAST ONE retrieved chunk
                  matched the expected file/keywords.
      mrr       — mean reciprocal rank: for each query, 1/rank of the first
                  matching chunk (0 if none matched), averaged across the set.
    """
    per_item = []
    hits = 0
    reciprocal_ranks = []

    for item in golden_set:
        chunks = retrieve_fn(item["question"])
        rank_of_first_hit = None
        for i, chunk in enumerate(chunks, start=1):
            if _chunk_matches(chunk, item):
                rank_of_first_hit = i
                break

        matched = rank_of_first_hit is not None
        if matched:
            hits += 1
        reciprocal_ranks.append(1.0 / rank_of_first_hit if matched else 0.0)

        per_item.append({
            "question": item["question"],
            "matched": matched,
            "rank_of_first_hit": rank_of_first_hit,
            "num_retrieved": len(chunks),
        })

    total = len(golden_set) or 1
    pass_rate = round(hits / total, 3)
    mrr = round(sum(reciprocal_ranks) / total, 3) if reciprocal_ranks else 0.0

    logger.info("📊 Legacy eval: pass_rate=%.3f mrr=%.3f (%d/%d queries matched)",
                pass_rate, mrr, hits, len(golden_set))

    return {
        "pass_rate": pass_rate,
        "mrr": mrr,
        "total_queries": len(golden_set),
        "matched_queries": hits,
        "details": per_item,
    }


def compare_configs(
    golden_set: List[Dict[str, Any]],
    retrieve_a: Callable[[str], List],
    retrieve_b: Callable[[str], List],
    label_a: str = "A",
    label_b: str = "B",
) -> Dict[str, Any]:
    """Compare two retrieval configurations using pass_rate / MRR."""
    eval_a = evaluate_retrieval(golden_set, retrieve_a)
    eval_b = evaluate_retrieval(golden_set, retrieve_b)

    deltas = {
        "delta_pass_rate": round(eval_b["pass_rate"] - eval_a["pass_rate"], 3),
        "delta_mrr": round(eval_b["mrr"] - eval_a["mrr"], 3),
    }

    winner = label_b
    if eval_a["pass_rate"] >= eval_b["pass_rate"]:
        winner = label_a

    return {
        label_a: {"pass_rate": eval_a["pass_rate"], "mrr": eval_a["mrr"]},
        label_b: {"pass_rate": eval_b["pass_rate"], "mrr": eval_b["mrr"]},
        "deltas": deltas,
        "winner": winner,
    }


# ============================================================================
# RAGAS-based evaluation (LLM-graded metrics)
# ============================================================================

def evaluate_with_ragas(
    golden_set: List[Dict[str, Any]],
    retrieve_fn: Callable[[str], List],
    llm_model: str = "gpt-4o-mini",
    metrics: List = None
) -> Dict[str, Any]:
    """
    Evaluate retrieval using RAGAS metrics.
    This is complementary to evaluate_retrieval() above.
    """
    if metrics is None:
        metrics = [
            context_recall,
            context_precision,
            faithfulness,
            answer_relevancy,
        ]
    data = []
    for item in golden_set:
        chunks = retrieve_fn(item["question"])
        contexts = [chunk.text for chunk in chunks]

        ground_truth = []
        if "expected_file" in item:
            ground_truth = [c.text for c in chunks if c.file == item["expected_file"]]

        if not ground_truth and "expected_keywords" in item:
            keywords = [k.lower() for k in item["expected_keywords"]]
            ground_truth = [
                c.text for c in chunks
                if any(k in c.text.lower() for k in keywords)
            ]

        if not ground_truth and chunks:
            ground_truth = [chunks[0].text]

        data.append({
            "question": item["question"],
            "contexts": contexts,
            "ground_truth": ground_truth if ground_truth else contexts[:3],
            "answer": "",
        })

    dataset = Dataset.from_list(data)
    llm = LangchainLLMWrapper(ChatOpenAI(model=llm_model, temperature=0))

    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=llm,
    )

    result_dict = {
        "context_recall": round(result["context_recall"], 3) if "context_recall" in result else None,
        "context_precision": round(result["context_precision"], 3) if "context_precision" in result else None,
        "faithfulness": round(result["faithfulness"], 3) if "faithfulness" in result else None,
        "answer_relevancy": round(result["answer_relevancy"], 3) if "answer_relevancy" in result else None,
        "details": result.to_pandas().to_dict('records') if hasattr(result, 'to_pandas') else {},
    }

    logger.info("🤖 RAGAS eval: recall=%.3f precision=%.3f",
                result_dict["context_recall"] or 0,
                result_dict["context_precision"] or 0)

    return result_dict


def compare_configs_with_ragas(
    golden_set: List[Dict[str, Any]],
    retrieve_a: Callable[[str], List],
    retrieve_b: Callable[[str], List],
    label_a: str = "A",
    label_b: str = "B",
    llm_model: str = "gpt-4o-mini"
) -> Dict[str, Any]:
    """Compare two retrieval configurations using RAGAS metrics."""
    eval_a = evaluate_with_ragas(golden_set, retrieve_a, llm_model)
    eval_b = evaluate_with_ragas(golden_set, retrieve_b, llm_model)

    deltas = {}
    for metric in ["context_recall", "context_precision"]:
        if eval_a.get(metric) is not None and eval_b.get(metric) is not None:
            deltas[f"delta_{metric}"] = round(eval_b[metric] - eval_a[metric], 3)

    winner = label_b
    if eval_a.get("context_precision") and eval_b.get("context_precision"):
        if eval_a["context_precision"] >= eval_b["context_precision"]:
            winner = label_a

    return {
        label_a: {
            "context_recall": eval_a.get("context_recall"),
            "context_precision": eval_a.get("context_precision"),
        },
        label_b: {
            "context_recall": eval_b.get("context_recall"),
            "context_precision": eval_b.get("context_precision"),
        },
        "deltas": deltas,
        "winner": winner,
    }


# ============================================================================
# Combined entrypoints
# ============================================================================

def combined_evaluation(
    golden_set: List[Dict[str, Any]],
    retrieve_fn: Callable[[str], List],
    llm_model: str = "gpt-4o-mini"
) -> Dict[str, Any]:
    """Run both the legacy metric-based evaluation and RAGAS evaluation."""
    legacy_results = evaluate_retrieval(golden_set, retrieve_fn)
    ragas_results = evaluate_with_ragas(golden_set, retrieve_fn, llm_model)

    return {
        "legacy": legacy_results,
        "ragas": ragas_results,
        "combined": {
            "pass_rate": legacy_results["pass_rate"],
            "mrr": legacy_results["mrr"],
            "context_recall": ragas_results.get("context_recall"),
            "context_precision": ragas_results.get("context_precision"),
        }
    }


def evaluate_with_ragas_wrapper(
    golden_set: List[Dict[str, Any]],
    retrieve_fn: Callable[[str], List],
    use_legacy: bool = True,
    use_ragas: bool = True,
    **kwargs
) -> Dict[str, Any]:
    """Wrapper function that can run either or both evaluations."""
    results = {}

    if use_legacy:
        results["legacy"] = evaluate_retrieval(golden_set, retrieve_fn)
        logger.info("✅ Legacy evaluation completed")

    if use_ragas:
        results["ragas"] = evaluate_with_ragas(golden_set, retrieve_fn, **kwargs)
        logger.info("✅ RAGAS evaluation completed")

    return results