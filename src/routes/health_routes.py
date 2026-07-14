from fastapi import APIRouter
from src.services.agent import get_agent_status

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/health/ready")
async def ready():
    status = await get_agent_status()
    return {"status": "ready" if status.get("initialized", False) else "not_ready"}


@router.get("/health/live")
async def live():
    return {"status": "alive"}