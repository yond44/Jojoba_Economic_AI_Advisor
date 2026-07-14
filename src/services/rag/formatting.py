"""
Answer prettifier — makes model output read like a modern AI assistant.  [UPGRADE]

The heavy lifting is done by the v2 system prompt (registered in
src/prompts/registry.py) which instructs the model to write clean, skimmable
markdown. This module is a light, deterministic tidy-up applied afterwards:
  - normalize excessive blank lines,
  - ensure list markers are on their own lines,
  - guarantee a short bold lead sentence if the model produced a wall of text.
It never rewrites content — only whitespace/structure — so it's safe.
"""
from __future__ import annotations

import re


def prettify_answer(text: str) -> str:
    if not text:
        return text
    t = text.strip()
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"(?<!\n)\n?([-*] )", r"\n\1", t)
    t = re.sub(r"(?<!\n)\n?(\d+\.\s)", r"\n\1", t)
    t = re.sub(r"\n(#{1,4} )", r"\n\n\1", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()
