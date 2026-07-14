"""Streaming responses — SSE meta -> token* -> done.  [FEATURE]"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)


def _sse(event: str, data: Dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def stream_answer(llm, prompt: str, sources: Optional[List[Dict[str, Any]]] = None,
                        context: str = "", groundedness_check=None) -> AsyncGenerator[str, None]:
    start = time.time()
    yield _sse("meta", {"sources": sources or [], "streaming": True})
    full: List[str] = []
    try:
        stream_fn = getattr(llm, "stream_complete", None)
        if stream_fn is not None:
            deltas = await asyncio.to_thread(lambda: list(stream_fn(prompt)))
            for d in deltas:
                token = getattr(d, "delta", None) or str(d)
                full.append(token)
                yield _sse("token", {"text": token})
                await asyncio.sleep(0)
        else:
            ans = str(await asyncio.to_thread(llm.complete, prompt))
            full.append(ans)
            yield _sse("token", {"text": ans})
    except Exception as exc:
        logger.error("Streaming failed: %s", exc)
        yield _sse("error", {"message": "generation failed"})
        return
    done: Dict[str, Any] = {"elapsed_s": round(time.time() - start, 2)}
    if groundedness_check is not None and context:
        try:
            done["groundedness"] = groundedness_check("".join(full), context).as_dict()
        except Exception:
            pass
    yield _sse("done", done)
