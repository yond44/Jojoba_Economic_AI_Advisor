"""
Modular RAG package (this IS the project's RAG — upgraded in place).
====================================================================

Public API preserved for backward compatibility — every symbol the rest of the
codebase imported from the old `src.services.rag` module still lives here:

    query_rag, query_rag_sync, initialize_rag, get_rag_status, setup_llm,
    setup_embeddings, setup_vector_store, get_cache_stats, clear_query_cache,
    build_index, rebuild_index_async, chunk_documents_by_type,
    CHROMA_DB_DIR, COLLECTION_NAME, run_eval

New capabilities exported by the upgrade:
    answer_stream        streaming (SSE) answers
    retrieve, retrieve_advanced   hybrid retrieval + full retrieval pipeline
    incremental_index    embed only changed chunks
    evaluate_retrieval, compare_configs   automated retrieval evaluation
"""
from src.services.rag.config import CHROMA_DB_DIR, COLLECTION_NAME
from src.services.rag.embeddings import setup_embeddings, setup_llm
from src.services.rag.vector_store import setup_vector_store
from src.services.rag.chunking import chunk_documents_by_type
from src.services.rag.cache import get_cache_stats, clear_query_cache

from src.services.rag.engine import (
    query_rag,
    query_rag_sync,
    answer_stream,
    initialize_rag,
    build_index,
    rebuild_index_async,
    run_eval,
    get_rag_status,
    test_chunking,
    _resolve_raw_dir,
)

from src.services.rag.retrieval import retrieve, retrieve_advanced
from src.services.rag.indexer import incremental_index
from src.services.rag.evaluation import evaluate_retrieval, compare_configs

__all__ = [
    "query_rag", "query_rag_sync", "initialize_rag", "get_rag_status",
    "setup_llm", "setup_embeddings", "setup_vector_store",
    "get_cache_stats", "clear_query_cache", "build_index",
    "rebuild_index_async", "chunk_documents_by_type",
    "CHROMA_DB_DIR", "COLLECTION_NAME", "run_eval", "test_chunking",
    "answer_stream", "retrieve", "retrieve_advanced",
    "incremental_index", "evaluate_retrieval", "compare_configs",
]
