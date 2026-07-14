from fastapi import HTTPException, Request
import time
from collections import defaultdict
import os
import logging

logger = logging.getLogger(__name__)

RATE_LIMIT = int(os.getenv("RATE_LIMIT", 50))
RATE_LIMIT_PERIOD = int(os.getenv("RATE_LIMIT_PERIOD", 60))


_requests = defaultdict(list)
_last_cleanup = time.time()


def _cleanup():
    global _last_cleanup
    now = time.time()
    
    if now - _last_cleanup > 300:
        for client_id in list(_requests.keys()):
            _requests[client_id] = [
                t for t in _requests[client_id] 
                if now - t < RATE_LIMIT_PERIOD
            ]
            if not _requests[client_id]:
                del _requests[client_id]
        _last_cleanup = now


def _is_allowed(client_id: str):
    now = time.time()
    _cleanup()
    
    _requests[client_id] = [
        t for t in _requests[client_id] 
        if now - t < RATE_LIMIT_PERIOD
    ]
    
    if len(_requests[client_id]) >= RATE_LIMIT:
        if _requests[client_id]:
            oldest = _requests[client_id][0]
            wait_time = int(RATE_LIMIT_PERIOD - (now - oldest))
            return False, max(1, wait_time)
        return False, RATE_LIMIT_PERIOD
    
    _requests[client_id].append(now)
    return True, 0


async def check_rate_limit(request: Request):
    client_id = request.client.host if request.client else "unknown"
    api_key = request.headers.get("X-API-Key")
    if api_key:
        client_id = f"key_{api_key[:8]}"
    
    allowed, wait_time = _is_allowed(client_id)
    
    if not allowed:
        logger.warning(f"⚠️ Rate limit exceeded for {client_id}")
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Try again in {wait_time} seconds."
        )
    
    return True