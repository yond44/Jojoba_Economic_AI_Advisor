"""
Automatic index builder for server deployments.
Detects if index exists and builds it if missing.
"""

import os
import logging
import time
from pathlib import Path
from typing import Optional

from src.services.rag.config import CHROMA_DB_DIR, COLLECTION_NAME
from src.services.rag.engine import build_index, _resolve_raw_dir

logger = logging.getLogger(__name__)


def ensure_index_exists(
    force_rebuild: bool = False,
    rebuild_on_empty: bool = True,
    max_retries: int = 3,
    retry_delay: int = 5
) -> bool:
    """
    Ensure the RAG index exists and is ready.
    
    Args:
        force_rebuild: Force rebuild even if index exists
        rebuild_on_empty: Rebuild if collection exists but is empty
        max_retries: Number of retry attempts
        retry_delay: Seconds between retries
    
    Returns:
        True if index is ready, False if failed
    """
    
    raw_dir = _resolve_raw_dir()
    if raw_dir is None or not raw_dir.exists():
        logger.warning(f"⚠️ No data/raw directory found. RAG will be unavailable.")
        return False
    
    index_exists = (CHROMA_DB_DIR / COLLECTION_NAME).exists()
    index_empty = False
    
    if index_exists:
        try:
            import chromadb
            client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
            collection = client.get_or_create_collection(COLLECTION_NAME)
            index_empty = collection.count() == 0
            logger.info(f"📊 Existing index: {collection.count()} vectors")
        except Exception as e:
            logger.warning(f"⚠️ Could not check index: {e}")
            index_empty = True
    
    needs_build = (
        force_rebuild or
        not index_exists or
        (rebuild_on_empty and index_empty)
    )
    
    if not needs_build:
        logger.info("✅ RAG index already exists and is ready")
        return True
    
    logger.info(f"🔄 Building RAG index (force={force_rebuild}, empty={index_empty})")
    
    for attempt in range(max_retries):
        try:
            result = build_index(force=force_rebuild)
            
            if result.get('rebuilt', False) or result.get('vectors', 0) > 0:
                logger.info(f"✅ Index built successfully: {result}")
                return True
            else:
                logger.warning(f"⚠️ Index build produced no vectors: {result}")
                
        except Exception as e:
            logger.error(f"❌ Index build failed (attempt {attempt + 1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                logger.info(f"⏳ Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                logger.error("❌ All retry attempts failed")
                return False
    
    return False


def get_index_status() -> dict:
    """Get current index status for health checks."""
    status = {
        "exists": False,
        "vector_count": 0,
        "data_exists": False,
        "ready": False,
        "location": str(CHROMA_DB_DIR),
        "collection": COLLECTION_NAME,
    }
    
    raw_dir = _resolve_raw_dir()
    if raw_dir and raw_dir.exists():
        status["data_exists"] = True
        status["data_path"] = str(raw_dir)
    
    try:
        import chromadb
        client = chromadb.PersistentClient(path=str(CHROMA_DB_DIR))
        collection = client.get_or_create_collection(COLLECTION_NAME)
        status["exists"] = True
        status["vector_count"] = collection.count()
        status["ready"] = collection.count() > 0
    except Exception as e:
        logger.warning(f"⚠️ Could not read index status: {e}")
    
    return status