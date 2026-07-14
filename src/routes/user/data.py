from fastapi import APIRouter, Depends, HTTPException
import logging

from src.config.database import get_db
from src.auth.auth import get_current_user
from src.utils.user_data_manager import (
    get_user_questions,
    get_user_question_stats,
    delete_user_questions,
    get_user_overview
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["user:data"])


@router.get("/me")
async def get_user_overview_endpoint(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get user's complete overview"""
    try:
        overview = await get_user_overview(db, current_user.id)
        return {"status": "success", "data": overview}
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/questions")
async def get_my_questions(
    limit: int = 100,
    success_only: bool = False,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get user's questions"""
    try:
        questions = await get_user_questions(db, current_user.id, limit=limit, success_only=success_only)
        
        return {
            "status": "success",
            "count": len(questions),
            "questions": questions
        }
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stats")
async def get_my_stats(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get user's statistics"""
    try:
        stats = await get_user_question_stats(db, current_user.id)
        
        return {
            "status": "success",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/questions")
async def delete_my_questions(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Delete all user's questions"""
    try:
        success = await delete_user_questions(db, current_user.id)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete")
        
        logger.warning(f"🗑️ Questions deleted for {current_user.username}")
        
        return {
            "status": "success",
            "message": "All questions deleted"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")