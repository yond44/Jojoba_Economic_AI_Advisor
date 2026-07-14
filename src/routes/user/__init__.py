"""User Routes Package"""
from fastapi import APIRouter

from . import data
from . import emails
from . import preferences


router = APIRouter(prefix="/user")

router.include_router(data.router)
router.include_router(emails.router)
router.include_router(preferences.router)


__all__ = ["router"]