"""Agent Routes Package"""
from fastapi import APIRouter

from . import query
from . import webhook
from . import queue
from . import status
from . import logs

router = APIRouter(prefix="/agent", tags=["agent"])

router.include_router(query.router)
router.include_router(queue.router)
router.include_router(status.router)
router.include_router(logs.router)

__all__ = ["router"]