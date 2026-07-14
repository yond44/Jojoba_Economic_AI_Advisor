import logging
from fastapi import APIRouter, Depends, HTTPException, Query as QueryParam
from datetime import datetime
from typing import Optional

from src.config.database import get_db
from src.auth.auth import get_current_user
from src.models.user import UserInDB
from src.services.question_manager import (
    get_question_count,
    get_all_questions,
    get_next_question,
    add_question,
    remove_first_question,
    generate_new_question_from_data,
    get_archive,
    get_file_paths,
    get_data_summary,
    reset_question_queue,
    initialize_question_file
)
from src.services.agent import reset_question_system

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/queue", tags=["queue"])


# ============================================
# MIDDLEWARE - ADMIN CHECK
# ============================================

async def check_admin(current_user: UserInDB = Depends(get_current_user)) -> UserInDB:
    if not getattr(current_user, 'is_admin', False):
        logger.warning(f"⚠️ Unauthorized queue access attempt by {current_user.username}")
        raise HTTPException(
            status_code=403,
            detail="Only administrators can access queue management endpoints"
        )
    return current_user


# ============================================
# QUEUE OVERVIEW
# ============================================

@router.get("")
async def get_queue(
    current_user: UserInDB = Depends(get_current_user)
):
    try:
        questions = get_all_questions()
        next_question = get_next_question()
        
        logger.info(f"📊 Queue status retrieved by {current_user.username}")
        
        metrics = {
            "total": len(questions),
            "average_length": int(sum(len(q) for q in questions) / len(questions)) if questions else 0,
            "min_length": min(len(q) for q in questions) if questions else 0,
            "max_length": max(len(q) for q in questions) if questions else 0,
            "processing_order": "FIFO" if next_question else "empty"
        }
        
        return {
            "status": "success",
            "total": len(questions),
            "next_question": next_question,
            "questions": questions,
            "metrics": metrics,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error retrieving queue: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/count")
async def get_queue_count(
    current_user: UserInDB = Depends(get_current_user)
):
    try:
        count = get_question_count()
        archive_count = len(get_archive())
        
        logger.debug(f"📈 Queue count: {count} | Archive: {archive_count}")
        
        return {
            "status": "success",
            "queue_count": count,
            "archive_count": archive_count,
            "total_processed": count + archive_count
        }
        
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/next")
async def peek_next_question(
    current_user: UserInDB = Depends(get_current_user)
):
    try:
        next_q = get_next_question()
        
        if not next_q:
            logger.info(f"📭 Queue is empty - checked by {current_user.username}")
            return {
                "status": "empty",
                "message": "No questions in queue"
            }
        
        logger.debug(f"👀 Peeked next question")
        
        return {
            "status": "success",
            "question": next_q,
            "position": 1,
            "queue_size": get_question_count()
        }
        
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================
# ARCHIVE MANAGEMENT
# ============================================

@router.get("/archive")
async def get_archive_questions(
    skip: int = QueryParam(0, ge=0),
    limit: int = QueryParam(20, ge=1, le=100),
    current_user: UserInDB = Depends(get_current_user)
):
    try:
        archive = get_archive()
        total = len(archive)
        
        paginated = list(reversed(archive))[skip:skip + limit]
        
        logger.info(f"📜 Archive retrieved by {current_user.username} (skip={skip}, limit={limit})")
        
        return {
            "status": "success",
            "total": total,
            "archive": paginated,
            "pagination": {
                "skip": skip,
                "limit": limit,
                "remaining": max(0, total - skip - limit)
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error retrieving archive: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/archive/search")
async def search_archive(
    q: str = QueryParam(..., min_length=1, max_length=200),
    current_user: UserInDB = Depends(get_current_user)
):
    try:
        archive = get_archive()
        query_lower = q.lower()
        
        results = [item for item in archive if query_lower in item.lower()]
        
        logger.info(f"🔍 Archive search by {current_user.username}: '{q}' - {len(results)} matches")
        
        return {
            "status": "success",
            "query": q,
            "results": results,
            "total": len(results)
        }
        
    except Exception as e:
        logger.error(f"❌ Search error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================
# QUEUE MANAGEMENT (ADMIN ONLY)
# ============================================

@router.post("/add")
async def add_question_to_queue(
    question: str = QueryParam(..., min_length=5, max_length=2000),
    admin: UserInDB = Depends(check_admin),
    db = Depends(get_db)
):
    if not question or not question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")
    
    try:
        add_question(question.strip())
        new_count = get_question_count()
        
        logger.warning(f"➕ Question added by {admin.username}: {question[:50]}...")
        logger.info(f"   Queue size is now: {new_count}")
        
        return {
            "status": "success",
            "message": "Question added to queue",
            "question": question[:100],
            "queue_size": new_count,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error adding question: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/add-bulk")
async def add_bulk_questions(
    questions: list,
    admin: UserInDB = Depends(check_admin),
    db = Depends(get_db)
):
    if not questions or not isinstance(questions, list):
        raise HTTPException(status_code=400, detail="Expected list of questions")
    
    try:
        added = 0
        failed = 0
        errors = []
        
        for q in questions:
            if q and isinstance(q, str) and len(q.strip()) >= 5:
                try:
                    add_question(q.strip())
                    added += 1
                except Exception as e:
                    failed += 1
                    errors.append({"question": q[:50], "error": str(e)})
            else:
                failed += 1
        
        new_count = get_question_count()
        
        logger.warning(f"➕ Bulk add by {admin.username}: {added} added, {failed} failed")
        
        return {
            "status": "success" if added > 0 else "partial",
            "added": added,
            "failed": failed,
            "errors": errors if errors else None,
            "queue_size": new_count,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Bulk add error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/process")
async def process_next_question(
    admin: UserInDB = Depends(check_admin),
    db = Depends(get_db)
):
    try:
        next_q = get_next_question()
        
        if not next_q:
            logger.warning(f"⚠️ Process attempted on empty queue by {admin.username}")
            raise HTTPException(status_code=404, detail="Queue is empty")
        
        remove_first_question()
        new_count = get_question_count()
        
        logger.warning(f"✅ Processed by {admin.username}: {next_q[:50]}...")
        logger.info(f"   Remaining in queue: {new_count}")
        
        return {
            "status": "success",
            "processed_question": next_q,
            "remaining_count": new_count,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Process error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/generate")
async def generate_new_question(
    admin: UserInDB = Depends(check_admin),
    db = Depends(get_db)
):
    try:
        new_q = generate_new_question_from_data()
        
        if not new_q:
            logger.warning(f"⚠️ Could not generate question - by {admin.username}")
            raise HTTPException(
                status_code=500,
                detail="Could not generate question from available data"
            )
        
        add_question(new_q)
        new_count = get_question_count()
        
        logger.warning(f"✨ Generated by {admin.username}: {new_q[:50]}...")
        logger.info(f"   Queue size is now: {new_count}")
        
        return {
            "status": "success",
            "message": "Question generated and added to queue",
            "question": new_q,
            "queue_size": new_count,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Generation error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================
# QUEUE MAINTENANCE (ADMIN ONLY)
# ============================================

@router.post("/reset")
async def reset_queue(
    admin: UserInDB = Depends(check_admin),
    db = Depends(get_db)
): 
    try:
        logger.warning(f"🔄 QUEUE RESET initiated by {admin.username}")
        
        result = reset_question_system(db=db)
        
        logger.warning(f"✅ Queue reset completed by {admin.username}")
        
        return {
            "status": "success",
            "message": "Queue reset successfully",
            **result,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Reset error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/reinitialize")
async def reinitialize_queue(
    admin: UserInDB = Depends(check_admin),
    db = Depends(get_db)
):
    try:
        logger.warning(f"🔁 Queue reinitialization initiated by {admin.username}")
        
        count = initialize_question_file(db=db)
        
        logger.warning(f"✅ Queue reinitialized by {admin.username}: {count} questions")
        
        return {
            "status": "success",
            "message": "Queue reinitialized from source files",
            "initialized_count": count,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Reinitialization error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================
# QUEUE INFORMATION
# ============================================

@router.get("/files")
async def get_queue_files(
    current_user: UserInDB = Depends(get_current_user)
):
    try:
        paths = get_file_paths()
        question_count = get_question_count()
        archive_count = len(get_archive())
        
        logger.debug(f"📁 File info retrieved by {current_user.username}")
        
        return {
            "status": "success",
            "paths": paths,
            "question_count": question_count,
            "archive_count": archive_count,
            "total_processed": question_count + archive_count,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/data-summary")
async def get_data_summary_endpoint(
    current_user: UserInDB = Depends(get_current_user)
):
    try:
        summary = get_data_summary()
        
        logger.info(f"📊 Data summary retrieved by {current_user.username}")
        
        return {
            "status": "success",
            "data": summary,
            "retrieved_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stats")
async def get_queue_statistics(
    current_user: UserInDB = Depends(get_current_user)
):
    try:
        questions = get_all_questions()
        archive = get_archive()
        
        queue_stats = {
            "total": len(questions),
            "average_length": int(sum(len(q) for q in questions) / len(questions)) if questions else 0,
            "min_length": min(len(q) for q in questions) if questions else 0,
            "max_length": max(len(q) for q in questions) if questions else 0,
        }
        
        archive_stats = {
            "total": len(archive),
            "average_length": int(sum(len(q) for q in archive) / len(archive)) if archive else 0,
        }
        
        health = {
            "queue_utilization": len(questions),
            "processing_rate": "unknown",
            "status": "healthy" if len(questions) < 1000 else "warning" if len(questions) < 5000 else "critical"
        }
        
        logger.debug(f"📈 Stats retrieved by {current_user.username}")
        
        return {
            "status": "success",
            "queue_stats": queue_stats,
            "archive_stats": archive_stats,
            "health": health,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================
# HEALTH CHECK
# ============================================

@router.get("/health")
async def queue_health():
    try:
        count = get_question_count()
        
        is_operational = True
        status = "healthy"
        
        if count == 0:
            status = "empty"
        elif count > 5000:
            status = "warning"
            is_operational = True
        
        return {
            "status": status,
            "queue_size": count,
            "is_operational": is_operational,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Health check failed: {str(e)}")
        return {
            "status": "error",
            "is_operational": False,
            "error": str(e)
        }, 503