"""User Emails Routes"""
from fastapi import APIRouter, Depends, HTTPException
import logging

from src.config.database import get_db
from src.auth.auth import get_current_user
from src.models.email import EmailCreate, EmailUpdate
from src.utils.user_data_manager import (
    add_user_email,
    get_user_emails,
    delete_user_email,
    get_user_email_string
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/emails", tags=["user:emails"])


@router.get("")
async def get_my_emails(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get user's emails"""
    try:
        emails = await get_user_emails(db, current_user.id)
        
        return {
            "status": "success",
            "count": len(emails),
            "emails": emails
        }
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("")
async def add_my_email(
    email_data: EmailCreate,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Add email to user's list"""
    try:
        new_email = await add_user_email(
            db,
            user_id=current_user.id,
            name=email_data.name,
            email=email_data.email
        )
        
        if not new_email:
            raise HTTPException(status_code=400, detail="Email already exists")
        
        return {"status": "success", "email": new_email}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/{email_id}")
async def delete_my_email(
    email_id: str,
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Delete email from user's list"""
    try:
        deleted = await delete_user_email(db, current_user.id, email_id)
        
        if not deleted:
            raise HTTPException(status_code=404, detail="Email not found")
        
        return {"status": "success", "message": "Email deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/string/export")
async def get_my_email_string(
    current_user = Depends(get_current_user),
    db = Depends(get_db)
):
    """Get user's emails as string"""
    try:
        email_string = await get_user_email_string(db, current_user.id)
        
        return {
            "status": "success",
            "email_string": email_string
        }
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")