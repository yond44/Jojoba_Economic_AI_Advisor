"""Incremental indexing — embed only changed chunks (content-hash diff).  [FEATURE]"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Dict

import chromadb

from src.services.rag.chunking import chunk_documents_by_type
from src.services.rag.config import CHROMA_DB_DIR, COLLECTION_NAME
from src.services.rag.embeddings import setup_embeddings
from src.services.rag.retrieval import invalidate_bm25

logger = logging.getLogger(__name__)


def _cid(file_name: str, text: str) -> str:
    return hashlib.sha1(f"{file_name}::{text}".encode("utf-8")).hexdigest()


def incremental_index(data_dir: str | None = None) -> Dict[str, int]:
    from llama_index.core import SimpleDirectoryReader
    from src.services.rag.engine import _resolve_raw_dir

    raw = Path(data_dir) if data_dir else _resolve_raw_dir()
    if raw is None or not raw.exists():
        raise FileNotFoundError("data/raw not found")
    start = time.time()
    col = chromadb.PersistentClient(path=str(CHROMA_DB_DIR)).get_or_create_collection(COLLECTION_NAME)

    docs = SimpleDirectoryReader(str(raw)).load_data()
    chunks = chunk_documents_by_type(docs)
    desired = {}
    for c in chunks:
        fn = c.metadata.get("file_name", "unknown")
        desired[_cid(fn, c.text)] = {"text": c.text, "metadata": c.metadata}

    existing = set(col.get(include=[]).get("ids", []))
    to_add = [cid for cid in desired if cid not in existing]
    to_del = [cid for cid in existing if cid not in desired]

    if to_del:
        col.delete(ids=to_del)
    if to_add:
        emb = setup_embeddings()
        texts = [desired[c]["text"] for c in to_add]
        metas = [desired[c]["metadata"] for c in to_add]
        vecs = [emb.get_text_embedding(t) for t in texts]
        col.upsert(ids=to_add, documents=texts, metadatas=metas, embeddings=vecs)
    if to_add or to_del:
        invalidate_bm25()
        from src.services.rag.cache import clear_query_cache
        clear_query_cache()

    result = {"added": len(to_add), "deleted": len(to_del),
              "unchanged": len(desired) - len(to_add), "duration_s": round(time.time() - start, 2)}
    logger.info("📈 Incremental index: %s", result)
    return result
