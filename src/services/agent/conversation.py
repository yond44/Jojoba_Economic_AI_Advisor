"""Conversation metrics + per-thread context store."""
import logging
import threading
from collections import OrderedDict
from typing import Dict, Any, Optional, List
from datetime import datetime, timedelta

from src.services.agent.util import _utcnow
from src.services.agent.config import MAX_CONTEXTS, CONTEXT_TTL_HOURS
from src.services.agent.models import ConversationContext, QueryRequest
from src.config.prompts import detect_language, IntelligentRecommender

logger = logging.getLogger(__name__)


class AgentMetrics:
    """Thread-safe request metrics with a single recording path."""

    _COUNTER_TYPES = (
        "analysis", "greeting", "gratitude", "human_expression",
        "off_topic", "queue", "error",
    )

    def __init__(self):
        self._lock = threading.Lock()
        self.total_queries = 0
        self.successful_queries = 0
        self.failed_queries = 0
        self.total_processing_time = 0.0
        self.by_type: Dict[str, int] = {t: 0 for t in self._COUNTER_TYPES}

    def record(self, response_type: str, success: bool, processing_time: float):
        """The ONLY way metrics change. Called exactly once per request."""
        with self._lock:
            self.total_queries += 1
            self.total_processing_time += processing_time
            if success:
                self.successful_queries += 1
            else:
                self.failed_queries += 1
            key = response_type if response_type in self.by_type else "analysis"
            self.by_type[key] += 1

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            n = self.total_queries
            return {
                "total_queries": n,
                "successful_queries": self.successful_queries,
                "failed_queries": self.failed_queries,
                "error_rate": round(self.failed_queries / n, 3) if n else 0.0,
                "avg_processing_time": round(self.total_processing_time / n, 3) if n else 0.0,
                "greetings_handled": self.by_type["greeting"],
                "gratitude_handled": self.by_type["gratitude"],
                "human_expressions_handled": self.by_type["human_expression"],
                "off_topic_rejected": self.by_type["off_topic"],
                "by_type": dict(self.by_type),
            }

class ConversationManager:
    """Manages conversation contexts across threads — bounded and thread-safe."""

    PRUNE_EVERY = 100

    def __init__(self, max_contexts: int = MAX_CONTEXTS,
                 ttl_hours: int = CONTEXT_TTL_HOURS):
        self.contexts: "OrderedDict[str, ConversationContext]" = OrderedDict()
        self.metrics = AgentMetrics()
        self.max_contexts = max_contexts
        self.ttl_hours = ttl_hours
        self._lock = threading.Lock()
        self._creations = 0

    def get_or_create_context(self, request: QueryRequest) -> ConversationContext:
        with self._lock:
            thread_id = request.thread_id

            if thread_id not in self.contexts:
                self.contexts[thread_id] = ConversationContext(
                    thread_id=thread_id,
                    user_id=request.user_id,
                    username=request.username,
                    language=request.language or detect_language(request.question),
                    channel=request.channel
                )
                self._creations += 1
                if self._creations % self.PRUNE_EVERY == 0:
                    self._prune_expired_locked()
                while len(self.contexts) > self.max_contexts:
                    evicted_id, _ = self.contexts.popitem(last=False)
                    logger.info(f"🧹 Evicted LRU conversation context: {evicted_id}")

            context = self.contexts[thread_id]
            self.contexts.move_to_end(thread_id)
            context.last_interaction = _utcnow().isoformat()
            context.interaction_count += 1
            return context

    def update_context(self, context: ConversationContext, question: str,
                       response_type: str, entities: Dict[str, Any]):
        with self._lock:
            context.questions_history.append(question)
            if len(context.questions_history) > 50:
                context.questions_history = context.questions_history[-50:]

            if entities.get("companies"):
                context.topics_discussed.extend(["company_analysis"] * len(entities["companies"]))
            if entities.get("sectors"):
                context.topics_discussed.extend(["sector_analysis"] * len(entities["sectors"]))
            if entities.get("assets"):
                context.topics_discussed.extend(entities["assets"])
            if len(context.topics_discussed) > 200:
                context.topics_discussed = context.topics_discussed[-200:]

            if len(context.questions_history) > 5:
                context.user_level = IntelligentRecommender.estimate_user_level(
                    context.questions_history)

    def get_summary(self, thread_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            context = self.contexts.get(thread_id)
            if not context:
                return None
            return {
                "thread_id": thread_id,
                "interaction_count": context.interaction_count,
                "topics": list(set(context.topics_discussed)),
                "user_level": context.user_level,
                "language": context.language,
                "duration": {
                    "created_at": context.created_at,
                    "last_interaction": context.last_interaction
                },
                "question_count": len(context.questions_history)
            }

    def _prune_expired_locked(self) -> int:
        """Remove contexts idle longer than ttl_hours. Caller holds lock."""
        cutoff = _utcnow() - timedelta(hours=self.ttl_hours)
        expired = [
            tid for tid, ctx in self.contexts.items()
            if datetime.fromisoformat(ctx.last_interaction) < cutoff
        ]
        for tid in expired:
            del self.contexts[tid]
        if expired:
            logger.info(f"🧹 Pruned {len(expired)} expired conversation contexts")
        return len(expired)

    def clear_old_contexts(self, max_age_hours: int = 24) -> int:
        """Public manual cleanup (kept for API compatibility). Now actually
        works — the original raised NameError because `timedelta` was
        never imported (FIX #1a)."""
        with self._lock:
            old_ttl, self.ttl_hours = self.ttl_hours, max_age_hours
            removed = self._prune_expired_locked()
            self.ttl_hours = old_ttl
            return removed


conversation_manager = ConversationManager()
