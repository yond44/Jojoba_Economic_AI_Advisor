"""
RAG engine — orchestration for the modular RAG package.
=======================================================

This is the public core the agent + routes call (via query_rag). It preserves
the original thread-safe init, offline/hot-swap build, retries, metrics, and the
two-tier (exact + semantic) cache — and UPGRADES the answer path to run:

    rewrite → hybrid(BM25+dense)+metadata+adaptive_k → rerank → compress
    → versioned prompt (A/B/canary) → generate → groundedness → prettify

Cache behaviour is unchanged and now caches the fully-upgraded answer, so the
whole system (agent, /ask, chat, webhook) benefits without bypassing your cache.

Structure of the package (each capability is its own module):
  config, cache, metrics, embeddings, chunking, vector_store   (foundation)
  query_transform, retrieval, reranker, compressor,
  groundedness, streaming, indexer, evaluation, formatting     (the 14 features)
  engine                                                       (this file)
"""
from __future__ import annotations

import os
import time
import random
import logging
import hashlib
import threading
import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from llama_index.core import (
    VectorStoreIndex, SimpleDirectoryReader, Settings, StorageContext, Document,
)
import chromadb

from src.services.rag.config import (
    CHUNK_SIZE, CHUNK_OVERLAP, SIMILARITY_TOP_K, MAX_QUERY_LENGTH,
    RETRY_BASE_DELAY, CHROMA_DB_DIR, DATA_HASH_FILE, COLLECTION_NAME,
    SEMANTIC_CACHE_ENABLED, GROUNDEDNESS_ENABLED, GROUNDEDNESS_THRESHOLD,
)
from src.services.rag.embeddings import setup_embeddings, setup_llm
from src.services.rag.chunking import (
    chunk_documents_by_type, setup_node_parser,
)
from src.services.rag.vector_store import (
    setup_vector_store, _hash_data_directory, _data_has_changed, _save_data_hash,
)
from src.services.rag.cache import (
    _query_cache, _semantic_cache, _hash_query, _embed_query_safe,
    clear_query_cache, get_cache_stats,
)
from src.services.rag.metrics import _metrics

logger = logging.getLogger(__name__)

_query_engine = None
_is_initialized = False
_index = None
_init_lock = threading.Lock()

_llm = None
_llm_lock = threading.Lock()


def _get_llm():
    global _llm
    if _llm is None:
        with _llm_lock:
            if _llm is None:
                _llm = setup_llm()
                logger.info("🔌 RAG LLM client created (cached)")
    return _llm


# ==========================================================================
# UPGRADED ANSWER PIPELINE  (the 14-feature flow, wired into the cached core)
# ==========================================================================
def _answer_pipeline(question: str, language: str, filters, history, bucket_key: str,
                     attempt: int) -> Dict[str, Any]:
    from src.services.rag.retrieval import retrieve_advanced
    from src.services.rag import groundedness as _g
    from src.services.rag.formatting import prettify_answer
    from src.prompts.registry import select_prompt
    from src.observability.tracing import add_span_attrs

    r = retrieve_advanced(question, filters=filters, history=history)
    context, sources = r["context"], r["sources"]

    if not context:
        response = _query_engine.query(question)
        return {"answer": prettify_answer(str(response)),
                "sources": _extract_sources(response), "success": True,
                "attempts": attempt + 1, "from_cache": False,
                "groundedness": None, "prompt_version": "legacy"}

    assignment = select_prompt(language=language, bucket_key=bucket_key)
    prompt = assignment.render(context=context, question=question)
    answer = prettify_answer(str(_get_llm().complete(prompt)).strip())

    ground = None
    if GROUNDEDNESS_ENABLED and answer:
        ground = _g.check_groundedness(
            answer, context, overall_threshold=GROUNDEDNESS_THRESHOLD).as_dict()

    add_span_attrs(prompt_version=assignment.version, sources=len(sources))
    return {"answer": answer, "sources": sources, "success": True,
            "attempts": attempt + 1, "from_cache": False, "groundedness": ground,
            "prompt_version": assignment.version,
            "rewritten_query": r.get("search_query", question)}


def query_rag_sync(question: str, max_retries: int = 3, language: str = "en",
                   filters: Optional[Dict[str, Any]] = None,
                   history: Optional[List[str]] = None,
                   bucket_key: str = "anon") -> Dict[str, Any]:
    """Upgraded query core — same cache/retry contract, richer pipeline.

    Returns the same shape as before plus: groundedness, prompt_version,
    rewritten_query. Callers that only read answer/sources are unaffected.
    """
    from src.observability.tracing import traced

    start = time.time()

    err = _validate_question(question)
    if err:
        return {"answer": None, "sources": [], "success": False, "attempts": 0,
                "error": err, "from_cache": False}

    initialize_rag()

    cached = _query_cache.get(_hash_query(question))
    if cached is not None:
        logger.info("✅ Cache HIT (exact): %s...", question[:50])
        return {**cached, "from_cache": True, "cache_tier": "exact"}

    query_vec = None
    if SEMANTIC_CACHE_ENABLED:
        query_vec = _embed_query_safe(question)
        if query_vec is not None:
            hit = _semantic_cache.get(query_vec)
            if hit is not None:
                logger.info("✅ Cache HIT (semantic, sim=%.3f)", hit.similarity)
                _query_cache.set(_hash_query(question), hit.result)
                return {**hit.result, "from_cache": True, "cache_tier": "semantic",
                        "matched_question": hit.question,
                        "similarity": round(hit.similarity, 3)}

    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            result = _answer_pipeline(question, language, filters, history,
                                      bucket_key, attempt)
            _query_cache.set(_hash_query(question), result)
            if SEMANTIC_CACHE_ENABLED and query_vec is not None:
                _semantic_cache.set(_hash_query(question), query_vec, question, result)
            _metrics.record_query(time.time() - start, failed=False, retries=attempt)
            return result
        except Exception as e:
            last_error = e
            if _is_permanent_error(e):
                logger.error("❌ Permanent error, not retrying: %s", e)
                break
            logger.warning("⚠️ Transient error attempt %d: %s", attempt + 1, e)
            if attempt < max_retries - 1:
                time.sleep(_backoff_delay(attempt))

    logger.error("❌ Query failed after %d attempt(s): %s", max_retries, last_error)
    _metrics.record_query(time.time() - start, failed=True, retries=max_retries - 1)
    return {"answer": None, "sources": [], "success": False, "attempts": max_retries,
            "error": str(last_error), "from_cache": False}


async def query_rag(question: str, max_retries: int = 3, language: str = "en",
                    filters: Optional[Dict[str, Any]] = None,
                    history: Optional[List[str]] = None,
                    bucket_key: str = "anon") -> Dict[str, Any]:
    """Async wrapper — keeps the event loop free while the sync core runs."""
    return await asyncio.to_thread(
        query_rag_sync, question, max_retries, language, filters, history, bucket_key)


async def answer_stream(question: str, language: str = "en",
                        filters: Optional[Dict[str, Any]] = None,
                        history: Optional[List[str]] = None, bucket_key: str = "anon"):
    """Streaming variant (SSE) — used by the chat stream endpoint."""
    from src.services.rag.retrieval import retrieve_advanced
    from src.services.rag import streaming as _st, groundedness as _g
    from src.prompts.registry import select_prompt

    initialize_rag()
    r = retrieve_advanced(question, filters=filters, history=history)
    assignment = select_prompt(language=language, bucket_key=bucket_key)
    prompt = assignment.render(context=r["context"] or "No specific data found.",
                               question=question)
    async for ev in _st.stream_answer(
        _get_llm(), prompt, sources=r["sources"], context=r["context"],
        groundedness_check=(_g.check_groundedness if GROUNDEDNESS_ENABLED else None),
    ):
        yield ev


# ==========================================================================
# Below: original engine helpers (init, build, eval, status) — unchanged.
# ==========================================================================
def _extract_sources(response) -> List[Dict[str, Any]]:
    sources = []
    if hasattr(response, 'source_nodes'):
        for node in response.source_nodes:
            sources.append({
                "text": node.node.text[:300],
                "score": float(node.score) if node.score else 0,
                "chunk_type": node.node.metadata.get('chunk_type', 'unknown'),
                "file": node.node.metadata.get('file_name', 'unknown'),
                "category": node.node.metadata.get('category', ''),
                "topic": node.node.metadata.get('topic', ''),
            })
    return sources


def _validate_question(question: str) -> Optional[str]:
    """Input validation — reject garbage BEFORE spending an LLM call on it.
    Returns an error string, or None if the input is fine."""
    if not question or not question.strip():
        return "Question is empty."
    if len(question) > MAX_QUERY_LENGTH:
        return f"Question too long ({len(question)} chars; max {MAX_QUERY_LENGTH})."
    return None


_PERMANENT_ERROR_MARKERS = (
    "api key", "api_key", "authentication", "unauthorized", "401", "403",
    "invalid request", "model_decommissioned", "model not found",
    "context_length", "billing",
)


def _is_permanent_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(marker in msg for marker in _PERMANENT_ERROR_MARKERS)


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff with jitter: ~2s, ~4s, ~8s (±50% random)."""
    base = RETRY_BASE_DELAY * (2 ** attempt)
    return base * (0.5 + random.random())


def _resolve_raw_dir() -> Optional[Path]:
    """Find data/raw using multiple strategies:
    1. Environment variable DATA_DIR (for server deployments)
    2. Project root relative to this file (for normal installs)
    3. Current working directory (for development)
    4. Fallback locations
    """
    import os
    
    data_dir = os.getenv("DATA_DIR")
    if data_dir:
        path = Path(data_dir)
        if path.exists():
            logger.info(f"📂 Using DATA_DIR: {path}")
            return path
    
    current_dir = Path(__file__).parent
    project_root = current_dir.parent.parent
    
    candidates = [
        project_root / "data" / "raw",
        current_dir / "data" / "raw",
        current_dir.parent.parent / "data" / "raw",
        Path.cwd() / "data" / "raw",
    ]
    
    for candidate in candidates:
        if candidate.exists():
            logger.info(f"📂 Found data directory: {candidate}")
            return candidate
    
    for parent in [Path.cwd(), Path(__file__).parent, project_root]:
        for _ in range(3):
            test_path = parent / "data" / "raw"
            if test_path.exists():
                logger.info(f"📂 Found data directory (search): {test_path}")
                return test_path
            parent = parent.parent
    
    logger.warning("⚠️ No data/raw directory found in any location")
    return None


def _build_index_from_raw(raw_dir: Path, vector_store) -> VectorStoreIndex:
    """Full pipeline: load raw docs -> chunk -> embed -> index.
    Expensive. At runtime this should only run as a last-resort fallback;
    normal deploys use build_index.py offline + _load_existing_index()."""
    logger.info("📂 Indexing data files (full rebuild)...")

    clear_query_cache()

    raw_documents = SimpleDirectoryReader(str(raw_dir)).load_data()
    logger.info(f"✅ Loaded {len(raw_documents)} documents")

    for fn in sorted({doc.metadata.get('file_name', 'unknown') for doc in raw_documents}):
        logger.info(f"  📄 {fn}")

    logger.info("🔨 Applying chunking strategies...")
    chunked_documents = chunk_documents_by_type(raw_documents)
    logger.info(f"✅ Created {len(chunked_documents)} chunks from {len(raw_documents)} documents")

    chunk_types: Dict[str, int] = {}
    for doc in chunked_documents:
        ct = doc.metadata.get('chunk_type', 'unknown')
        chunk_types[ct] = chunk_types.get(ct, 0) + 1
    for ct, count in sorted(chunk_types.items()):
        logger.info(f"  📈 {ct}: {count} chunks")

    logger.info("🔍 Building vector index...")
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    parser = setup_node_parser()

    index = VectorStoreIndex.from_documents(
        chunked_documents,
        storage_context=storage_context,
        transformations=[parser],
        show_progress=True,
    )

    _save_data_hash(raw_dir)
    return index


def _load_existing_index(vector_store) -> VectorStoreIndex:
    """Cheap path: attach to vectors already sitting in ChromaDB."""
    logger.info("⚡ Loading existing index from ChromaDB...")
    return VectorStoreIndex.from_vector_store(vector_store)


def _do_build_index(force: bool) -> Dict[str, Any]:
    """The actual build. Only ever runs while holding _init_lock."""
    global _index, _query_engine

    start = time.time()

    raw_dir = _resolve_raw_dir()
    if raw_dir is None:
        raise FileNotFoundError(
            "Data directory not found (looked for ./data/raw next to rag.py "
            "and at project_root/data/raw)"
        )

    if not force and DATA_HASH_FILE.exists() and not _data_has_changed(raw_dir):
        return {
            "rebuilt": False,
            "reason": "data content unchanged (use force=True to override)",
            "raw_dir": str(raw_dir),
            "collection": COLLECTION_NAME,
            "duration_s": round(time.time() - start, 2),
        }

    logger.info("🚀 Starting index build...")
    logger.info(f"📊 Chunk size: {CHUNK_SIZE}, Overlap: {CHUNK_OVERLAP}, "
                f"Collection: {COLLECTION_NAME}")

    if not _is_initialized:
        Settings.embed_model = setup_embeddings()

    vector_store = setup_vector_store(force_clear=True)
    new_index = _build_index_from_raw(raw_dir, vector_store)

    vector_count = 0
    try:
        chroma_client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
        vector_count = chroma_client.get_or_create_collection(COLLECTION_NAME).count()
    except Exception:
        pass

    if _is_initialized:
        _index = new_index
        _query_engine = new_index.as_query_engine(
            similarity_top_k=SIMILARITY_TOP_K,
            response_mode="compact",
        )
        logger.info("🔁 Live query engine hot-swapped to the new index")

    duration = round(time.time() - start, 2)
    logger.info(f"✅ Index build complete: {vector_count} vectors in {duration}s")

    return {
        "rebuilt": True,
        "raw_dir": str(raw_dir),
        "collection": COLLECTION_NAME,
        "vectors": vector_count,
        "hot_swapped": _is_initialized,
        "duration_s": duration,
    }


def build_index(force: bool = False) -> Dict[str, Any]:
    """Build the vector index (or skip if data content is unchanged).

    Single implementation used by:
      - build_index.py (CLI, offline builds you commit to git)
      - admin endpoints / cron jobs on a server (via rebuild_index_async)
      - the runtime fallback path in initialize_rag

    Thread-safe: takes the same lock as initialization, so a rebuild
    can't race a cold start or another rebuild.
    """
    with _init_lock:
        return _do_build_index(force)


async def rebuild_index_async(force: bool = False) -> Dict[str, Any]:
    """Async wrapper for calling build_index from FastAPI without
    blocking the event loop (embedding can take minutes)."""
    return await asyncio.to_thread(build_index, force)


def initialize_rag(force_reindex: bool = False):
    """Thread-safe entry point. Safe to call from every request —
    after the first successful init, it returns instantly.

    PRODUCTION FIX #1 in action: double-checked locking.
    """
    global _is_initialized

    if _is_initialized and not force_reindex:
        return

    with _init_lock:
        if _is_initialized and not force_reindex:
            return
        _do_initialize(force_reindex)


def _do_initialize(force_reindex: bool):
    """The actual init work. Only ever runs while holding _init_lock.

    Runtime default (HF Spaces / production):
      - Does NOT scan, read, or chunk data/raw.
      - Just attaches to the ChromaDB collection prebuilt offline via
        `python build_index.py` and committed to the repo.
      - This is what fixes the 20-minute startup hang.

    Fallback (prebuilt collection empty/missing, e.g. very first deploy):
      - Full build pipeline, with a loud warning.
    """
    global _query_engine, _is_initialized, _index

    try:
        logger.info("🚀 Initializing RAG System...")
        logger.info(f"📊 Chunk size: {CHUNK_SIZE}, Overlap: {CHUNK_OVERLAP}, Top-K: {SIMILARITY_TOP_K}")

        Settings.embed_model = setup_embeddings()
        Settings.llm = setup_llm()

        raw_dir = _resolve_raw_dir()

        vector_store = setup_vector_store(force_clear=False)

        try:
            chroma_client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
            collection = chroma_client.get_or_create_collection(COLLECTION_NAME)
            collection_has_vectors = collection.count() > 0
        except Exception:
            collection_has_vectors = False

        if force_reindex:
            logger.warning("⚠️ force_reindex=True — running full rebuild at runtime. "
                           "Prefer running build_index.py offline instead.")
            if raw_dir is None:
                raise FileNotFoundError("Data directory not found: data/raw")
            vector_store = setup_vector_store(force_clear=True)
            _index = _build_index_from_raw(raw_dir, vector_store)

        elif not collection_has_vectors:
            logger.warning(
                "⚠️ No prebuilt vectors found in data/chroma_db — falling back to full "
                "rebuild at runtime (slow). To avoid this in future, run "
                "`python build_index.py` locally (index tersimpan di data/chroma_db/)."
            )
            if raw_dir is None:
                raise FileNotFoundError(
                    "No prebuilt index and data directory not found: data/raw"
                )
            _index = _build_index_from_raw(raw_dir, vector_store)

        else:
            _index = _load_existing_index(vector_store)

        _query_engine = _index.as_query_engine(
            similarity_top_k=SIMILARITY_TOP_K,
            response_mode="compact",
        )

        _is_initialized = True
        logger.info("✅ RAG initialized successfully")

    except Exception as e:
        logger.error(f"❌ RAG initialization failed: {str(e)}")
        raise


def run_eval(golden_set: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Measure retrieval quality against a golden question set.

    Each golden item:
      question           (str, required)
      expected_keywords  (list[str], required) — should appear in the
                         retrieved source chunks (checks RETRIEVAL, the
                         part chunking actually affects)
      expected_file      (str, optional) — a file that should appear
                         among the retrieved sources
    """
    initialize_rag()
    results = []

    for item in golden_set:
        question = item["question"]
        res = query_rag_sync(question)

        retrieved_text = " ".join(s["text"].lower() for s in res.get("sources", []))
        retrieved_files = {s["file"] for s in res.get("sources", [])}

        keywords = item.get("expected_keywords", [])
        keywords_found = [kw for kw in keywords if kw.lower() in retrieved_text]

        file_ok = True
        if item.get("expected_file"):
            file_ok = item["expected_file"] in retrieved_files

        keyword_rate = len(keywords_found) / len(keywords) if keywords else 1.0
        passed = res["success"] and keyword_rate >= 0.5 and file_ok

        results.append({
            "question": question,
            "success": res["success"],
            "keyword_hit_rate": round(keyword_rate, 2),
            "keywords_missing": [kw for kw in keywords if kw not in keywords_found],
            "expected_file_retrieved": file_ok,
            "passed": passed,
        })

    n = len(results)
    passed_n = sum(1 for r in results if r["passed"])
    report = {
        "total": n,
        "passed": passed_n,
        "pass_rate": round(passed_n / n, 2) if n else 0.0,
        "avg_keyword_hit_rate": round(
            sum(r["keyword_hit_rate"] for r in results) / n, 2
        ) if n else 0.0,
        "details": results,
    }

    logger.info(f"🧪 Eval: {passed_n}/{n} passed "
                f"(avg keyword hit rate {report['avg_keyword_hit_rate']})")
    return report


def get_rag_status() -> Dict[str, Any]:
    """Health/status snapshot — wire this to a /status endpoint and you
    have a real operational dashboard, not just a liveness ping."""
    return {
        "initialized": _is_initialized,
        "collection": COLLECTION_NAME,
        "db_path": str(CHROMA_DB_DIR),
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "similarity_top_k": SIMILARITY_TOP_K,
        "chunk_strategies": [
            "qa_pair", "glossary_entry", "scenario_playbook",
            "structured_row", "deep_dive_report", "quant_table", "default",
        ],
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "llm_model": "llama-3.3-70b-versatile",
        "cache": get_cache_stats(),
        "metrics": _metrics.snapshot(),
    }


def test_chunking():
    """Test chunking strategy with detailed output."""
    current_dir = Path(__file__).parent
    raw_dir = current_dir.parent.parent / "data" / "raw"

    documents = SimpleDirectoryReader(str(raw_dir)).load_data()
    chunked = chunk_documents_by_type(documents)

    chunk_types: Dict[str, int] = {}
    for doc in chunked:
        ct = doc.metadata.get('chunk_type', 'unknown')
        chunk_types[ct] = chunk_types.get(ct, 0) + 1

    avg_chunk_size = sum(len(doc.text) for doc in chunked) / len(chunked) if chunked else 0

    print(f"\n📊 Chunking Results:")
    print(f"  Raw documents: {len(documents)}")
    print(f"  Total chunks: {len(chunked)}")
    print(f"  Average chunk size: {avg_chunk_size:.0f} chars")
    print(f"  Chunk size config: {CHUNK_SIZE}")
    print(f"  Chunk overlap config: {CHUNK_OVERLAP}")
    print(f"\n📈 Chunk distribution:")
    for ct, count in sorted(chunk_types.items()):
        print(f"    {ct}: {count}")

    shown_types = set()
    print(f"\n📝 Sample chunks:")
    for doc in chunked:
        ct = doc.metadata.get('chunk_type', 'unknown')
        if ct not in shown_types:
            shown_types.add(ct)
            print(f"\n  --- {ct} ---")
            print(f"  {doc.text[:200]}...")
            print(f"  Metadata: { {k: v for k, v in doc.metadata.items() if k != 'file_name'} }")

    return chunked