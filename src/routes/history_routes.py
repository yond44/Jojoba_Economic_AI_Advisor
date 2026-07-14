
from fastapi import APIRouter, Depends, HTTPException, status, Query
import logging
from typing import Optional
from datetime import datetime

from src.config.database import get_db
from src.services import history_manager
from src.models.history import (
    SentHistoryCreate,
    SentHistoryResponse,
    SentHistoryListResponse,
    SentHistoryStats,
    SentHistoryUpdate,
    DeliveryStatus,
    ChannelType
)
from src.auth.auth import get_current_user
from src.models.user import UserInDB

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/history", tags=["history"])


def _user_filter(current_user: UserInDB) -> Optional[str]:
    """
    Return the user_id filter to apply for history queries.
    
    - Admins see everything (return None = no filter).
    - Regular users see entries matching their user_id OR system-generated
      entries (handled in history_manager via the include_system flag).
    """
    if getattr(current_user, "role", None) == "admin" or getattr(current_user, "is_admin", False):
        return None
    return str(current_user.id)


@router.post("", response_model=SentHistoryResponse, status_code=status.HTTP_201_CREATED)
async def create_history_entry(
    history_data: SentHistoryCreate,
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db)
):
    """Create a new sent history entry"""
    try:
        history_id = await history_manager.create_history_entry(
            db=db,
            history_data=history_data,
            user_id=str(current_user.id),
            username=current_user.username
        )
        
        if not history_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create history entry"
            )
        
        entry = await history_manager.get_history_entry(db, history_id)
        return entry
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating history entry: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create history entry"
        )


@router.get("", response_model=SentHistoryListResponse)
async def get_history(
    limit: int = Query(50, ge=1, le=100),
    skip: int = Query(0, ge=0),
    status_filter: Optional[str] = Query(None, description="Filter by status"),
    channel: Optional[str] = Query(None, description="Filter by channel"),
    include_system: bool = Query(True, description="Include n8n/system-generated entries"),
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get sent history entries.
    
    Regular users see their own entries plus optionally system-generated ones
    (from n8n automation). Admins see everything.
    """
    try:
        user_filter = _user_filter(current_user)
        
        histories = await history_manager.get_history_entries(
            db=db,
            limit=limit,
            skip=skip,
            status=status_filter,
            channel=channel,
            user_id=user_filter,
            include_system=include_system,
        )
        
        total = await history_manager.count_history_entries(
            db=db,
            status=status_filter,
            channel=channel,
            user_id=user_filter,
            include_system=include_system,
        )
        
        return {
            "status": "success",
            "count": len(histories),
            "total": total,
            "histories": histories
        }
        
    except Exception as e:
        logger.error(f"Error getting history: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get history"
        )


@router.get("/stats/overview", response_model=SentHistoryStats)
async def get_history_stats(
    days: int = Query(7, ge=1, le=30),
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get sent history statistics"""
    try:
        stats = await history_manager.get_history_stats(
            db=db,
            days=days,
            user_id=_user_filter(current_user),
        )
        return stats
        
    except Exception as e:
        logger.error(f"Error getting history stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get history stats"
        )


@router.get("/{history_id}", response_model=SentHistoryResponse)
async def get_history_entry(
    history_id: str,
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get a single history entry by ID"""
    try:
        entry = await history_manager.get_history_entry(db, history_id)
        
        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="History entry not found"
            )
        
        is_admin = getattr(current_user, "role", None) == "admin" or getattr(current_user, "is_admin", False)
        entry_user_id = entry.get("user_id")
        if not is_admin and entry_user_id and entry_user_id not in (str(current_user.id), "system"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this history entry"
            )
        
        return entry
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting history entry: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get history entry"
        )


@router.put("/{history_id}", response_model=SentHistoryResponse)
async def update_history_entry(
    history_id: str,
    update_data: SentHistoryUpdate,
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db)
):
    """Update a history entry"""
    try:
        entry = await history_manager.get_history_entry(db, history_id)
        
        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="History entry not found"
            )
        
        is_admin = getattr(current_user, "role", None) == "admin" or getattr(current_user, "is_admin", False)
        entry_user_id = entry.get("user_id")
        if not is_admin and entry_user_id and entry_user_id != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this history entry"
            )
        
        success = await history_manager.update_history_entry(db, history_id, update_data)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to update history entry"
            )
        
        updated_entry = await history_manager.get_history_entry(db, history_id)
        return updated_entry
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating history entry: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update history entry"
        )


@router.delete("/{history_id}")
async def delete_history_entry(
    history_id: str,
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db)
):
    """Delete a history entry"""
    try:
        entry = await history_manager.get_history_entry(db, history_id)
        
        if not entry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="History entry not found"
            )
        
        is_admin = getattr(current_user, "role", None) == "admin" or getattr(current_user, "is_admin", False)
        entry_user_id = entry.get("user_id")
        if not is_admin and entry_user_id and entry_user_id != str(current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this history entry"
            )
        
        success = await history_manager.delete_history_entry(db, history_id)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to delete history entry"
            )
        
        return {
            "status": "success",
            "message": "History entry deleted successfully"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting history entry: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete history entry"
        )


@router.delete("/clear/all")
async def clear_history(
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db)
):
    """Clear all history for the current user (admins clear everything)"""
    try:
        count = await history_manager.clear_history(db, _user_filter(current_user))
        return {
            "status": "success",
            "message": f"Cleared {count} history entries",
            "deleted_count": count
        }
        
    except Exception as e:
        logger.error(f"Error clearing history: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to clear history"
        )