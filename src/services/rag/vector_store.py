"""
Vector store setup + data-hash helpers — extracted from the original rag.py,
plus dense_search()/all_documents() used by the new hybrid retriever.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from llama_index.vector_stores.chroma import ChromaVectorStore

from src.services.rag.config import CHROMA_DB_DIR, COLLECTION_NAME, DATA_HASH_FILE
from src.services.rag.embeddings import setup_embeddings

logger = logging.getLogger(__name__)


def setup_vector_store(force_clear: bool = False):
    chroma_client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    if force_clear:
        try:
            chroma_client.delete_collection(COLLECTION_NAME)
            logger.info("🗑️ Cleared old ChromaDB collection")
        except Exception:
            pass
    collection = chroma_client.get_or_create_collection(COLLECTION_NAME)
    logger.info(f"📊 ChromaDB collection has {collection.count()} existing vectors")
    return ChromaVectorStore(chroma_collection=collection)


def _hash_data_directory(data_dir: Path) -> str:
    """SHA-256 over file names + file contents (deterministic order)."""
    hasher = hashlib.sha256()
    for filepath in sorted(data_dir.glob("*")):
        if filepath.is_file():
            hasher.update(filepath.name.encode())
            with open(filepath, "rb") as f:
                for block in iter(lambda: f.read(65536), b""):
                    hasher.update(block)
    return hasher.hexdigest()


def _data_has_changed(data_dir: Path) -> bool:
    current_hash = _hash_data_directory(data_dir)
    if DATA_HASH_FILE.exists():
        if DATA_HASH_FILE.read_text().strip() == current_hash:
            logger.info("📦 Data content unchanged — skipping reindex")
            return False
    logger.info("🔄 Data content changed — reindex required")
    return True


def _save_data_hash(data_dir: Path):
    DATA_HASH_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_HASH_FILE.write_text(_hash_data_directory(data_dir))
    logger.info("💾 Data content hash saved")

def _raw_collection():
    client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
    return client.get_or_create_collection(COLLECTION_NAME)


def dense_search(query_embedding: List[float], top_k: int,
                 where: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Vector similarity search returning [{text, score, metadata}]."""
    col = _raw_collection()
    res = col.query(query_embeddings=[query_embedding], n_results=top_k,
                    where=where or None, include=["documents", "metadatas", "distances"])
    docs = (res.get("documents") or [[]])[0]
    metas = (res.get("metadatas") or [[]])[0]
    dists = (res.get("distances") or [[]])[0]
    out = []
    for text, meta, dist in zip(docs, metas, dists):
        out.append({"text": text or "", "score": 1.0 / (1.0 + float(dist)),
                    "metadata": meta or {}})
    return out


def all_documents() -> List[Dict[str, Any]]:
    """Every chunk (for building an in-memory BM25 index)."""
    col = _raw_collection()
    res = col.get(include=["documents", "metadatas"])
    docs = res.get("documents") or []
    metas = res.get("metadatas") or []
    return [{"text": d or "", "metadata": m or {}} for d, m in zip(docs, metas)]

