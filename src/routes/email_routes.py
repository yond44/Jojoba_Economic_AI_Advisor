from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import PlainTextResponse
import logging

from src.config.database import get_db
from src.models.email import (
    EmailCreate,
    EmailUpdate,
    EmailResponse,
    EmailListResponse,
    EmailSingleResponse,
    EmailStringResponse,
    SuccessMessageResponse
)
from src.services import email_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emails", tags=["emails"])


def convert_email_document(email_doc):
    """Convert MongoDB document to API response format"""
    if email_doc is None:
        return None
    
    result = dict(email_doc)
    if '_id' in result:
        result['id'] = str(result['_id'])
        del result['_id']
    
    return result


# ============================================
# GET ENDPOINTS
# ============================================

@router.get("", response_model=EmailListResponse)
async def get_emails(
    db = Depends(get_db),
):
    """Get all email contacts"""
    try:
        emails = await email_manager.get_all_emails(db)
        
        converted_emails = [convert_email_document(email) for email in emails]
        
        return EmailListResponse(
            status="success",
            count=len(converted_emails),
            emails=converted_emails
        )
    except Exception as e:
        logger.error(f"Error fetching emails: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch emails"
        )


@router.get("/{email_id}", response_model=EmailSingleResponse)
async def get_email(
    email_id: str,
    db = Depends(get_db),
):
    """Get a single email contact by ID"""
    try:
        email = await email_manager.get_email_by_id(db, email_id)
        
        if not email:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Email contact not found"
            )
        
        converted_email = convert_email_document(email)
        
        return EmailSingleResponse(
            status="success",
            email=converted_email
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching email {email_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch email"
        )


@router.get("/string/export", response_model=EmailStringResponse)
async def get_emails_string(
    db = Depends(get_db),
):
    """Get all emails as comma-separated string"""
    try:
        email_string = await email_manager.get_email_string(db)
        count = await email_manager.get_email_count(db)
        
        return EmailStringResponse(
            status="success",
            email_string=email_string,
            count=count
        )
    except Exception as e:
        logger.error(f"Error fetching email string: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch email string"
        )


@router.get("/search/query")
async def search_emails(
    q: str = Query(..., min_length=1),
    db = Depends(get_db),
):
    """Search emails by name or email address"""
    try:
        results = await email_manager.search_emails(db, q)
        
        converted_results = [convert_email_document(result) for result in results]
        
        return {
            "status": "success",
            "query": q,
            "count": len(converted_results),
            "results": converted_results
        }
    except Exception as e:
        logger.error(f"Error searching emails: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Search failed"
        )


@router.get("/export/format")
async def export_emails(
    format: str = Query("json", regex="^(json|csv)$"),
    db = Depends(get_db),
):
    """Export emails in specified format"""
    try:
        content = await email_manager.export_emails(db, format)
        
        if not content:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported format: {format}"
            )
        
        media_type = "application/json" if format == "json" else "text/csv"
        
        return PlainTextResponse(
            content=content,
            media_type=media_type
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error exporting emails: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Export failed"
        )


@router.get("/stats/overview")
async def get_email_stats(
    db = Depends(get_db),
):
    """Get email statistics"""
    try:
        stats = await email_manager.get_email_stats(db)
        
        return {
            "status": "success",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Error fetching stats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch statistics"
        )


# ============================================
# POST ENDPOINTS
# ============================================

@router.post("", response_model=EmailSingleResponse, status_code=status.HTTP_201_CREATED)
async def create_email(
    email_data: EmailCreate,
    db = Depends(get_db),
):
    """Add a new email contact"""
    try:
        new_email = await email_manager.add_email(
            db,
            name=email_data.name,
            email=email_data.email
        )
        
        if not new_email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already exists or failed to add"
            )
        
        converted_email = convert_email_document(new_email)
        
        logger.info(f"Email created: {converted_email['id']}")
        
        return EmailSingleResponse(
            status="success",
            email=converted_email
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating email: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create email"
        )


@router.post("/reset/all", response_model=SuccessMessageResponse)
async def reset_emails(
    db = Depends(get_db),
):
    """Reset all email contacts"""
    try:
        success = await email_manager.reset_email_file(db)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to reset emails"
            )
        
        logger.info("Email collection reset")
        
        return SuccessMessageResponse(
            status="success",
            message="All email contacts have been reset"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resetting emails: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reset emails"
        )


@router.post("/initialize")
async def initialize_emails(
    emails: list[EmailCreate],
    db = Depends(get_db),
):
    """Initialize emails with default list"""
    try:
        email_dicts = [email.dict() for email in emails]
        success = await email_manager.initialize_email_file(db, email_dicts)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to initialize emails"
            )
        
        logger.info(f"Emails initialized with {len(emails)} contacts")
        
        return {
            "status": "success",
            "message": f"Initialized with {len(emails)} email contacts",
            "count": len(emails)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error initializing emails: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initialize emails"
        )


# ============================================
# PUT ENDPOINTS
# ============================================

@router.put("/{email_id}", response_model=EmailSingleResponse)
async def update_email_contact(
    email_id: str,
    email_data: EmailUpdate,
    db = Depends(get_db),
):
    """Update an email contact"""
    try:
        updated = await email_manager.update_email(
            db,
            email_id=email_id,
            name=email_data.name,
            email=email_data.email
        )
        
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Email contact not found"
            )
        
        converted_email = convert_email_document(updated)
        
        logger.info(f"Email updated: {email_id}")
        
        return EmailSingleResponse(
            status="success",
            email=converted_email
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating email {email_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update email"
        )


# ============================================
# DELETE ENDPOINTS
# ============================================

@router.delete("/{email_id}", response_model=SuccessMessageResponse)
async def delete_email_contact(
    email_id: str,
    db = Depends(get_db),
):
    """Delete an email contact"""
    try:
        deleted = await email_manager.delete_email(db, email_id)
        
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Email contact not found"
            )
        
        logger.info(f"Email deleted: {email_id}")
        
        return SuccessMessageResponse(
            status="success",
            message="Email contact deleted successfully"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting email {email_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete email"
        )