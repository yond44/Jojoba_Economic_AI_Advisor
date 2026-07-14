"""Cross-encoder reranking — precise (query, chunk) relevance scoring.  [FEATURE]"""
from __future__ import annotations

import logging
import os
import platform
from functools import lru_cache
from typing import List
from pathlib import Path

from src.services.rag.config import RERANK_MODEL, RERANK_TOP_N
from src.services.rag.types import RetrievedChunk

logger = logging.getLogger(__name__)

def _setup_fastembed_environment():
    """Configure FastEmbed cache directory to avoid Windows symlink issues"""
    
    cache_dir = os.environ.get("FASTEMBED_CACHE_PATH")
    if not cache_dir:
        if platform.system() == 'Windows':
            cache_dir = os.path.expanduser("C:/fastembed_cache")
        else:
            cache_dir = os.path.expanduser("~/fastembed_cache")
    
    os.makedirs(cache_dir, exist_ok=True)
    
    os.environ["FASTEMBED_CACHE_PATH"] = cache_dir
    os.environ["HF_HOME"] = cache_dir
    os.environ["TRANSFORMERS_CACHE"] = cache_dir
    os.environ["HUGGINGFACE_HUB_CACHE"] = cache_dir
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
    os.environ["HF_HUB_DISABLE_SYMLINKS"] = "1"
    os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "0"
    
    for subdir in ["models", "datasets", "metrics"]:
        os.makedirs(os.path.join(cache_dir, subdir), exist_ok=True)
    
    logger.info(f"📂 FastEmbed cache: {cache_dir}")
    return cache_dir

CACHE_DIR = _setup_fastembed_environment()

@lru_cache(maxsize=1)
def _cross_encoder():
    try:
        from fastembed.rerank.cross_encoder import TextCrossEncoder
        
        model_dir = Path(CACHE_DIR) / "models--Xenova--ms-marco-MiniLM-L-6-v2"
        
        if not model_dir.exists():
            logger.info(f"📥 Model not found in cache. Downloading to: {CACHE_DIR}")
            try:
                from huggingface_hub import snapshot_download
                snapshot_download(
                    repo_id="Xenova/ms-marco-MiniLM-L-6-v2",
                    cache_dir=CACHE_DIR,
                    local_dir_use_symlinks=False,
                    resume_download=True,
                    ignore_patterns=["*.h5", "*.ot", "*.msgpack"],
                    token=False
                )
                logger.info("✅ Model downloaded successfully")
            except Exception as e:
                logger.warning(f"⚠️  Could not download model: {e}")
        
        logger.info(f"🎯 Loading cross-encoder: {RERANK_MODEL}")
        return TextCrossEncoder(model_name=RERANK_MODEL)
        
    except Exception as exc:
        logger.warning(f"⚠️  Cross-encoder unavailable ({exc}) — lexical fallback")
        return None


def _lex(query: str, text: str) -> float:
    """Simple lexical overlap score as fallback"""
    q, t = set(query.lower().split()), set(text.lower().split())
    if not q:
        return 0.0
    return len(q & t) / len(q)


def rerank(query: str, chunks: List[RetrievedChunk], top_n: int | None = None) -> List[RetrievedChunk]:
    if not chunks:
        return []
    
    top_n = top_n or RERANK_TOP_N
    enc = _cross_encoder()
    
    if enc is not None:
        try:
            texts = [c.text for c in chunks]
            scores = list(enc.rerank(query, texts))
            
            out = [
                RetrievedChunk(
                    text=c.text,
                    score=float(scores[i]) if i < len(scores) else 0.0,
                    metadata=c.metadata
                )
                for i, c in enumerate(chunks)
            ]
            
            out.sort(key=lambda c: c.score, reverse=True)
            return out[:top_n]
            
        except Exception as exc:
            logger.warning(f"⚠️  Rerank failed ({exc}) — lexical fallback")
    
    out = [
        RetrievedChunk(
            text=c.text,
            score=_lex(query, c.text),
            metadata=c.metadata
        )
        for c in chunks
    ]
    out.sort(key=lambda c: c.score, reverse=True)
    return out[:top_n]