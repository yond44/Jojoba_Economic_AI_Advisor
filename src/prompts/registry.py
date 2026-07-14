"""
Prompt registry — versioning, A/B testing, and canary deployments in one place.
===============================================================================

FEATURES: "Prompt versioning", "A/B testing", "Canary deployments"

These three are the SAME mechanism at different rollout percentages, so they
live together:

  - Versioning: every prompt is stored by (name, version). You never edit a
    live prompt in place — you register v2 and roll it out. Old versions stay
    reproducible, so you can explain exactly which text produced an old answer.

  - A/B test: two versions each get a weight (e.g. 50/50). A stable hash of the
    user/thread id decides which version they get, so the SAME user is
    consistently in the same bucket (no flip-flopping mid-conversation), and
    results are attributable.

  - Canary: an A/B test skewed 95/5. Ship v2 to 5% of traffic, watch
    groundedness/error metrics for that variant, then dial the weight up. A
    canary that misbehaves is rolled back by setting its weight to 0 — no deploy.

DECIDE-BY-HASH (why not random?)
--------------------------------
random() would put the same user on different variants across requests, which
(a) ruins per-user experience and (b) makes metrics unattributable. Hashing a
stable key gives deterministic, uniform, sticky assignment.

PERSISTENCE
-----------
This registry is in-memory with a seed from config/prompts.py (your existing
SYSTEM_PROMPT_EN/ID). To make rollouts editable without redeploying, back it
with a Mongo collection — the interface here already matches that (see
BUILD_GUIDE.md "Make prompts editable at runtime").
"""
from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PromptVersion:
    name: str
    version: str
    template: str
    weight: float = 0.0
    active: bool = True
    metadata: dict = field(default_factory=dict)


@dataclass
class Assignment:
    name: str
    version: str
    template: str

    def render(self, **kwargs) -> str:
        return self.template.format(**kwargs)


class PromptRegistry:
    """Thread-safe store of prompt versions with weighted, sticky selection."""

    def __init__(self):
        self._lock = threading.Lock()
        self._prompts: Dict[str, Dict[str, PromptVersion]] = {}

    def register(self, pv: PromptVersion) -> None:
        with self._lock:
            self._prompts.setdefault(pv.name, {})[pv.version] = pv
            logger.info("📝 Registered prompt %s@%s (weight=%.2f)",
                        pv.name, pv.version, pv.weight)

    def set_weights(self, name: str, weights: Dict[str, float]) -> None:
        """Set rollout weights for versions of a prompt. Canary = {'v1':0.95,'v2':0.05}."""
        with self._lock:
            versions = self._prompts.get(name, {})
            for ver, w in weights.items():
                if ver in versions:
                    versions[ver].weight = max(0.0, w)
            logger.info("🎚️ Weights for %s -> %s", name, weights)

    def rollback(self, name: str, to_version: str) -> None:
        """Instant rollback: give one version all the weight, others zero."""
        with self._lock:
            for ver, pv in self._prompts.get(name, {}).items():
                pv.weight = 1.0 if ver == to_version else 0.0
        logger.warning("⏪ Rolled %s back to %s", name, to_version)

    def list_versions(self, name: str) -> List[PromptVersion]:
        with self._lock:
            return list(self._prompts.get(name, {}).values())

    def select(self, name: str, bucket_key: str = "anon") -> Optional[Assignment]:
        """Pick a version for this caller. Sticky per bucket_key (user/thread)."""
        with self._lock:
            versions = [
                pv for pv in self._prompts.get(name, {}).values()
                if pv.active and pv.weight > 0
            ]
        if not versions:
            fallback = [pv for pv in self._prompts.get(name, {}).values() if pv.active]
            if not fallback:
                return None
            pv = fallback[0]
            return Assignment(pv.name, pv.version, pv.template)

        total = sum(pv.weight for pv in versions)
        h = hashlib.sha256(f"{name}:{bucket_key}".encode()).hexdigest()
        point = (int(h[:8], 16) / 0xFFFFFFFF) * total

        cumulative = 0.0
        for pv in versions:
            cumulative += pv.weight
            if point <= cumulative:
                return Assignment(pv.name, pv.version, pv.template)
        pv = versions[-1]
        return Assignment(pv.name, pv.version, pv.template)


_registry: Optional[PromptRegistry] = None
_seed_lock = threading.Lock()


def get_registry() -> PromptRegistry:
    global _registry
    if _registry is None:
        with _seed_lock:
            if _registry is None:
                _registry = PromptRegistry()
                _seed(_registry)
    return _registry


_RESPONSE_FORMAT_EN = """
  <response_format>
  Write the answer the way a great AI assistant would — clean, skimmable, easy to act on:
  - Open with ONE bold sentence that directly answers the question.
  - Keep paragraphs short. For multi-part answers, use "## " subheadings.
  - Use "- " bullets for lists, and bold the key numbers, terms, and takeaways.
  - Prefer plain, confident language; briefly define a term the first time it appears.
  - When the answer is long, end with a short "Bottom line:" line.
  - Never invent figures that are not in the context. Output clean Markdown only.
  </response_format>
"""

_RESPONSE_FORMAT_ID = """
  <response_format>
  Tulis jawaban seperti asisten AI terbaik — rapi, mudah dipindai, mudah ditindaklanjuti:
  - Buka dengan SATU kalimat tebal yang langsung menjawab pertanyaan.
  - Paragraf pendek. Untuk jawaban bertahap, gunakan subjudul "## ".
  - Gunakan poin "- " untuk daftar, dan tebalkan angka, istilah, serta poin penting.
  - Gunakan bahasa yang jelas; jelaskan istilah saat pertama kali muncul.
  - Bila jawaban panjang, akhiri dengan baris "Intinya:" yang singkat.
  - Jangan mengarang angka yang tidak ada dalam konteks. Keluarkan Markdown yang bersih.
  </response_format>
"""


def _prettify_template(base: str, rules: str) -> str:
    """Insert formatting rules into the system prompt without disturbing
    the {context}/{question} placeholders."""
    if "</system_prompt>" in base:
        return base.replace("</system_prompt>", rules + "\n</system_prompt>", 1)
    return rules + "\n" + base


def _seed(reg: PromptRegistry) -> None:
    """Seed v1 (your current prompts) and v2 (prettier formatting).

    v2 is rolled out to 100% so answers look like a modern AI assistant; v1
    stays registered at weight 0 so `registry.rollback("system_en","v1")`
    reverts instantly with no redeploy. To canary instead, set weights to
    {'v1':0.9,'v2':0.1}.
    """
    try:
        from src.config.prompts import SYSTEM_PROMPT_EN, SYSTEM_PROMPT_ID
        reg.register(PromptVersion("system_en", "v1", SYSTEM_PROMPT_EN, weight=0.0))
        reg.register(PromptVersion("system_id", "v1", SYSTEM_PROMPT_ID, weight=0.0))
        reg.register(PromptVersion(
            "system_en", "v2",
            _prettify_template(SYSTEM_PROMPT_EN, _RESPONSE_FORMAT_EN), weight=1.0))
        reg.register(PromptVersion(
            "system_id", "v2",
            _prettify_template(SYSTEM_PROMPT_ID, _RESPONSE_FORMAT_ID), weight=1.0))
    except Exception as exc:
        logger.warning("Prompt seed failed: %s", exc)


def select_prompt(language: str = "en", bucket_key: str = "anon") -> Assignment:
    """Convenience used by the pipeline: pick the system prompt for a user."""
    name = "system_id" if language == "id" else "system_en"
    reg = get_registry()
    assignment = reg.select(name, bucket_key=bucket_key)
    if assignment is None:
        from src.config.prompts import get_system_prompt
        return Assignment(name, "v1", get_system_prompt(language))
    return assignment
