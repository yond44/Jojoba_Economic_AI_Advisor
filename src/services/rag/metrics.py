"""RAG metrics — extracted verbatim from the original rag.py (FIX #7)."""
from __future__ import annotations

import threading
from typing import Any, Dict

logger = __import__("logging").getLogger(__name__)


class Metrics:
    def __init__(self):
        self._lock = threading.Lock()
        self.queries_total = 0
        self.queries_failed = 0
        self.retries_total = 0
        self.total_latency_s = 0.0
        self.max_latency_s = 0.0

    def record_query(self, latency_s: float, failed: bool, retries: int):
        with self._lock:
            self.queries_total += 1
            self.retries_total += retries
            self.total_latency_s += latency_s
            self.max_latency_s = max(self.max_latency_s, latency_s)
            if failed:
                self.queries_failed += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            n = self.queries_total
            return {
                "queries_total": n,
                "queries_failed": self.queries_failed,
                "error_rate": round(self.queries_failed / n, 3) if n else 0.0,
                "retries_total": self.retries_total,
                "avg_latency_s": round(self.total_latency_s / n, 2) if n else 0.0,
                "max_latency_s": round(self.max_latency_s, 2),
            }

_metrics = Metrics()
