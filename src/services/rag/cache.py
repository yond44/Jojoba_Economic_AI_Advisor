"""
Two-tier query cache (exact + semantic) — extracted verbatim from the original
rag.py during the modular refactor. Behaviour is unchanged; see the class
docstrings for the FIX #2 / FIX #9 rationale.
"""
from __future__ import annotations

import sys
import time
import hashlib
import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from llama_index.core import Settings

from src.services.rag.config import (
    CACHE_TTL, CACHE_MAX_SIZE,
    SEMANTIC_CACHE_ENABLED, SEMANTIC_CACHE_THRESHOLD,
    SEMANTIC_CACHE_MAX_SIZE, SEMANTIC_CACHE_DIM,
)

logger = logging.getLogger(__name__)


class TTLLRUCache:
    """Thread-safe cache with both a TTL per entry and an LRU size cap.

    v2 upgrades (aligned with SemanticCache v2):
      [T-FIX 1] Evictions split by cause (lru vs ttl) — monitoring can now
                distinguish "cache too small" from "data expiring".
      [T-FIX 2] TTL expiry during get() is now COUNTED (evictions_ttl),
                not silently dropped.
      [T-FIX 3] Optional sliding_ttl — refresh timestamp on every hit.
      [T-FIX 4] invalidate(key) — surgically drop one entry (e.g. after
                a source document changes) without nuking the tier.
      [T-FIX 5] enabled flag injected via constructor, mirroring
                SemanticCache (FIX 10) — no implicit globals.
      [T-FIX 6] Constructor validation — fail fast on max_size <= 0.
    """

    def __init__(
        self,
        max_size: int,
        ttl: float,
        sliding_ttl: bool = False,
        enabled: bool = True,
    ):
        if max_size <= 0:
            raise ValueError("max_size harus > 0")
        self.max_size = max_size
        self.ttl = ttl
        self.sliding_ttl = sliding_ttl
        self.enabled = enabled
        self._store: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.evictions_lru = 0
        self.evictions_ttl = 0

    def get(self, key: str) -> Optional[Any]:
        if not self.enabled:
            return None
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self.misses += 1
                return None
            timestamp, value = entry
            now = time.time()
            if (now - timestamp) >= self.ttl:
                del self._store[key]
                self.evictions_ttl += 1
                self.misses += 1
                return None
            self._store.move_to_end(key)
            if self.sliding_ttl:
                self._store[key] = (now, value)
            self.hits += 1
            return value

    def set(self, key: str, value: Any):
        if not self.enabled:
            return
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (time.time(), value)
            while len(self._store) > self.max_size:
                self._store.popitem(last=False)
                self.evictions_lru += 1

    def invalidate(self, key: str) -> bool:
        """T-FIX 4: drop one entry explicitly."""
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def clear(self):
        with self._lock:
            self._store.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            valid = sum(1 for ts, _ in self._store.values() if (now - ts) < self.ttl)
            total_lookups = self.hits + self.misses
            return {
                "enabled": self.enabled,
                "size": len(self._store),
                "max_size": self.max_size,
                "valid_entries": valid,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total_lookups, 3) if total_lookups else 0.0,
                "evictions_lru": self.evictions_lru,
                "evictions_ttl": self.evictions_ttl,
                "ttl_seconds": self.ttl,
                "sliding_ttl": self.sliding_ttl,
            }

_query_cache = TTLLRUCache(max_size=CACHE_MAX_SIZE, ttl=CACHE_TTL)


class CacheHit:
    key: str
    question: str
    similarity: float
    result: Dict[str, Any]
    age_seconds: float


class SemanticCache:
    """
    Thread-safe semantic cache dengan:
      - Cosine similarity di atas matrix pre-allocated (zero-copy lookup)
      - LRU eviction + TTL (fixed atau sliding)
      - Lazy expiry + periodic sweep (amortized O(1) purge)
      - Statistik lengkap: hit rate, latency p50/p95, evictions per penyebab
    """
 
    def __init__(
        self,
        max_size: int = 512,
        ttl: float = 3600.0,
        threshold: float = 0.90,
        embedding_dim: int = 384,
        sliding_ttl: bool = False,
        sweep_interval: float = 60.0,
        max_result_bytes: Optional[int] = None,
        enabled: bool = True,
    ):
        if max_size <= 0:
            raise ValueError("max_size harus > 0")
        if not (0.0 < threshold <= 1.0):
            raise ValueError("threshold harus di (0, 1]")
 
        self.max_size = max_size
        self.ttl = ttl
        self.threshold = threshold
        self.embedding_dim = embedding_dim
        self.sliding_ttl = sliding_ttl
        self.sweep_interval = sweep_interval
        self.max_result_bytes = max_result_bytes
        self.enabled = enabled
 
        self._matrix = np.zeros((max_size, embedding_dim), dtype=np.float32)
        self._key_to_slot: Dict[str, int] = {}
        self._slot_to_key: Dict[int, str] = {}
        self._free_slots: List[int] = list(range(max_size - 1, -1, -1))
 
        self._meta: "OrderedDict[str, Tuple[float, str, Dict[str, Any]]]" = OrderedDict()
 
        self._lock = threading.Lock()
        self._last_sweep = time.time()
 
        self.hits = 0
        self.misses = 0
        self.evictions_lru = 0
        self.evictions_ttl = 0
        self.rejected_oversize = 0
        self._lookup_times: List[float] = []
        self._max_lookup_samples = 1000
 
 
    @staticmethod
    def _normalize(vec: List[float]) -> np.ndarray:
        arr = np.asarray(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        return arr / norm if norm > 0 else arr
 
    def _validate_dim(self, arr: np.ndarray) -> None:
        if arr.shape[0] != self.embedding_dim:
            raise ValueError(
                f"Dimensi embedding {arr.shape[0]} != {self.embedding_dim}. "
                f"Apakah model embedding berganti? Panggil clear() dan buat "
                f"ulang cache dengan embedding_dim yang benar."
            )
 
    def _record_latency(self, elapsed: float) -> None:
        if len(self._lookup_times) >= self._max_lookup_samples:
            self._lookup_times.pop(0)
        self._lookup_times.append(elapsed)
 
 
    def _evict_key(self, key: str, *, reason: str) -> None:
        slot = self._key_to_slot.pop(key)
        del self._slot_to_key[slot]
        del self._meta[key]
        self._matrix[slot].fill(0.0)
        self._free_slots.append(slot)
        if reason == "lru":
            self.evictions_lru += 1
        else:
            self.evictions_ttl += 1
 
    def _is_expired(self, key: str, now: float) -> bool:
        ts, _, _ = self._meta[key]
        return (now - ts) >= self.ttl
 
    def _maybe_sweep(self, now: float) -> None:
        if (now - self._last_sweep) < self.sweep_interval:
            return
        self._last_sweep = now
        expired = [k for k in self._meta if self._is_expired(k, now)]
        for k in expired:
            self._evict_key(k, reason="ttl")
 
 
    def get(self, query_vec: List[float]) -> Optional[CacheHit]:
        if not self.enabled:
            return None
 
        t0 = time.perf_counter()
        q = self._normalize(query_vec)
        self._validate_dim(q)
 
        with self._lock:
            now = time.time()
            self._maybe_sweep(now)
 
            if not self._meta:
                self.misses += 1
                self._record_latency(time.perf_counter() - t0)
                return None
 
            sims = self._matrix @ q
 
            while True:
                best_slot = int(np.argmax(sims))
                best_sim = float(sims[best_slot])
 
                if best_sim < self.threshold:
                    self.misses += 1
                    self._record_latency(time.perf_counter() - t0)
                    return None
 
                best_key = self._slot_to_key.get(best_slot)
                if best_key is None:
                    self.misses += 1
                    self._record_latency(time.perf_counter() - t0)
                    return None
 
                if self._is_expired(best_key, now):
                    self._evict_key(best_key, reason="ttl")
                    sims[best_slot] = -1.0
                    continue
 
                ts, question, result = self._meta[best_key]
                self._meta.move_to_end(best_key)
                if self.sliding_ttl:
                    self._meta[best_key] = (now, question, result)
 
                self.hits += 1
                self._record_latency(time.perf_counter() - t0)
                return CacheHit(
                    key=best_key,
                    question=question,
                    similarity=best_sim,
                    result=result,
                    age_seconds=now - ts,
                )
 
    def set(
        self,
        key: str,
        query_vec: List[float],
        question: str,
        result: Dict[str, Any],
    ) -> bool:
        """Return True jika tersimpan, False jika ditolak (oversize/disabled)."""
        if not self.enabled:
            return False
 
        if self.max_result_bytes is not None:
            approx = sys.getsizeof(str(result))
            if approx > self.max_result_bytes:
                self.rejected_oversize += 1
                return False
 
        q = self._normalize(query_vec)
        self._validate_dim(q)
 
        with self._lock:
            now = time.time()
 
            if key in self._key_to_slot:
                slot = self._key_to_slot[key]
                self._matrix[slot] = q
                self._meta[key] = (now, question, result)
                self._meta.move_to_end(key)
                return True
 
            if not self._free_slots:
                lru_key = next(iter(self._meta))
                self._evict_key(lru_key, reason="lru")
 
            slot = self._free_slots.pop()
            self._matrix[slot] = q
            self._key_to_slot[key] = slot
            self._slot_to_key[slot] = key
            self._meta[key] = (now, question, result)
            return True
 
    def invalidate(self, key: str) -> bool:
        """Hapus satu entri secara eksplisit (mis. data sumber berubah)."""
        with self._lock:
            if key not in self._key_to_slot:
                return False
            self._evict_key(key, reason="ttl")
            self.evictions_ttl -= 1
            return True
 
    def clear(self) -> None:
        with self._lock:
            self._meta.clear()
            self._key_to_slot.clear()
            self._slot_to_key.clear()
            self._free_slots = list(range(self.max_size - 1, -1, -1))
            self._matrix.fill(0.0)
 
    def stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self.hits + self.misses
            lat = sorted(self._lookup_times)
            p50 = lat[len(lat) // 2] * 1000 if lat else 0.0
            p95 = lat[int(len(lat) * 0.95)] * 1000 if lat else 0.0
            return {
                "enabled": self.enabled,
                "size": len(self._meta),
                "max_size": self.max_size,
                "threshold": self.threshold,
                "embedding_dim": self.embedding_dim,
                "ttl_seconds": self.ttl,
                "sliding_ttl": self.sliding_ttl,
                "hits": self.hits,
                "misses": self.misses,
                "hit_rate": round(self.hits / total, 3) if total else 0.0,
                "evictions_lru": self.evictions_lru,
                "evictions_ttl": self.evictions_ttl,
                "rejected_oversize": self.rejected_oversize,
                "lookup_p50_ms": round(p50, 3),
                "lookup_p95_ms": round(p95, 3),
                "memory_matrix_mb": round(self._matrix.nbytes / 1_048_576, 2),
            }

_semantic_cache = SemanticCache(
    max_size=SEMANTIC_CACHE_MAX_SIZE,
    ttl=CACHE_TTL,
    threshold=SEMANTIC_CACHE_THRESHOLD,
    embedding_dim=SEMANTIC_CACHE_DIM,
    enabled=SEMANTIC_CACHE_ENABLED,
)


def _embed_query_safe(question: str) -> Optional[List[float]]:
    """Embed a query for cache purposes; never let a cache path crash a request.

    Returns None on any failure — callers treat None as 'skip the
    semantic tier'. A broken cache should degrade to a slower answer,
    never to a failed one.
    """
    try:
        return Settings.embed_model.get_query_embedding(question)
    except Exception as e:
        logger.warning(f"⚠️ Semantic cache: embedding failed, skipping tier 2: {e}")
        return None


def _hash_query(question: str) -> str:
    """Cache key. MD5 is fine here — we need a fast fingerprint,
    not cryptographic security (nobody is attacking a cache key)."""
    return hashlib.md5(question.lower().strip().encode()).hexdigest()


def clear_query_cache():
    """Clear BOTH tiers. Call this after a reindex (build_index) — cached
    answers were generated from the OLD documents and are now stale in a
    way TTL alone won't catch fast enough."""
    _query_cache.clear()
    _semantic_cache.clear()
    logger.info("🧹 Query cache cleared (exact + semantic tiers)")


def get_cache_stats() -> Dict[str, Any]:
    return {
        "exact": _query_cache.stats(),
        "semantic": _semantic_cache.stats(),
    }
