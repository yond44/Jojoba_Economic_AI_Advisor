"""User Preferences Routes"""
from fastapi import APIRouter, Depends, HTTPException
import logging

from src.config.database import get_db
from src.auth.auth import get_current_user
from src.utils.user_data_manager import (
    set_user_preferences,
    get_user_preferences
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/preferences", tags=["user:preferences"])


@router.get("")
async def get_my_preferences(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get user preferences"""
    try:
        prefs = await get_user_preferences(db, current_user.id)
        
        return {
            "status": "success",
            "preferences": prefs
        }
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.put("")
async def update_my_preferences(
    preferences: dict,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Update user preferences"""
    try:
        success = await set_user_preferences(db, current_user.id, preferences)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to update")
        
        updated_prefs = await get_user_preferences(db, current_user.id)
        
        return {
            "status": "success",
            "preferences": updated_prefs
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")