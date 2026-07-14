"""Agent Question Logs Routes"""
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
import logging
from typing import Optional

from src.config.database import get_db
from src.auth.auth import get_current_user
from src.utils.question_logger import (
    get_question_logs,
    get_question_log_stats,
    clear_question_logs,
    export_question_logs,
    get_channel_stats,
    get_logs_by_channel
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/logs", tags=["agent:logs"])


@router.get("")
async def get_logs(
    limit: int = Query(100, ge=1, le=10000),
    success_only: bool = False,
    user_id: Optional[str] = Query(None),
    channel: Optional[str] = Query(None),
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    try:
        filter_user_id = user_id if user_id else current_user.id
        
        logs = await get_question_logs(
            db,
            limit=limit,
            success_only=success_only,
            user_id=filter_user_id,
            channel=channel
        )
        
        logger.info(f"📋 Retrieved {len(logs)} logs for user {filter_user_id}")
        
        return {
            "status": "success",
            "count": len(logs),
            "logs": logs
        }
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stats")
async def get_stats(
    user_id: Optional[str] = Query(None),
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    try:
        filter_user_id = user_id if user_id else current_user.id
        stats = await get_question_log_stats(db, user_id=filter_user_id)
        
        logger.info(f"📊 Retrieved stats for user {filter_user_id}")
        
        return {
            "status": "success",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/channel-stats")
async def get_channel_statistics(
    user_id: Optional[str] = Query(None),
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    try:
        filter_user_id = user_id if user_id else current_user.id
        stats = await get_channel_stats(db, user_id=filter_user_id)
        
        logger.info(f"📊 Retrieved channel stats for user {filter_user_id}")
        
        return {
            "status": "success",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/channel/{channel}")
async def get_channel_logs(
    channel: str,
    limit: int = Query(100, ge=1, le=10000),
    user_id: Optional[str] = Query(None),
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    try:
        filter_user_id = user_id if user_id else current_user.id
        logs = await get_logs_by_channel(db, channel, limit=limit, user_id=filter_user_id)
        
        logger.info(f"📋 Retrieved {len(logs)} logs for channel: {channel}")
        
        return {
            "status": "success",
            "channel": channel,
            "count": len(logs),
            "logs": logs
        }
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/export")
async def export_logs(
    format: str = Query("json", pattern="^(json|csv)$"),
    user_id: Optional[str] = Query(None),
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    try:
        filter_user_id = user_id if user_id else current_user.id
        content = await export_question_logs(db, format=format, user_id=filter_user_id)
        
        if not content:
            raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")
        
        media_type = "application/json" if format == "json" else "text/csv"
        
        logger.info(f"📤 Exported logs as {format.upper()}")
        
        return PlainTextResponse(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename=logs.{format}"}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/clear")
async def clear_logs(
    user_id: Optional[str] = Query(None),
    db = Depends(get_db),
    current_user = Depends(get_current_user)
):
    try:
        filter_user_id = user_id if user_id else current_user.id
        success = await clear_question_logs(db, user_id=filter_user_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to clear logs")
        
        logger.warning(f"🗑️ Logs cleared for user {filter_user_id}")
        
        return {
            "status": "success",
            "message": "Question logs cleared"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")