
from fastapi import APIRouter, Depends, HTTPException, status, Query
import logging
from typing import Optional
from datetime import datetime

from src.config.database import get_db
from src.services import question_manager
from src.services.email_manager import get_all_emails
from src.services.history_manager import create_history_entry
from src.models.history import SentHistoryCreate, ChannelType, DeliveryStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/questions", tags=["questions"])


# ============================================
# REGULAR ENDPOINTS
# ============================================

@router.get("")
async def get_questions(
    limit: int = Query(100, ge=1, le=1000),
    status_filter: Optional[str] = Query(None, description="Filter by status: pending, processing, completed, archived"),
    db = Depends(get_db),
):
    """Get all questions with optional status filter"""
    try:
        questions = await question_manager.get_all_questions(db, limit=limit, status=status_filter)
        return {
            "status": "success",
            "count": len(questions),
            "questions": questions
        }
    except Exception as e:
        logger.error(f"Error fetching questions: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/next")
async def get_next(
    db = Depends(get_db),
):
    """Get next pending question"""
    try:
        question = await question_manager.get_next_question(db)
        if not question:
            raise HTTPException(status_code=404, detail="No pending questions")
        return {"status": "success", "question": question}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting next question: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("")
async def create_question(
    text: str,
    source: str = "api",
    db = Depends(get_db),
):
    """Create new question manually"""
    try:
        question_id = await question_manager.add_question(db, text=text, source=source)
        if not question_id:
            raise HTTPException(status_code=400, detail="Invalid question")
        
        question = await question_manager.get_question_by_id(db, question_id)
        
        return {
            "status": "success",
            "question": question
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating question: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/generate")
async def generate_question(
    db = Depends(get_db),
):
    """Generate new question from templates (non-LLM)"""
    try:
        question = await question_manager.generate_new_question_from_data(db)
        if not question:
            raise HTTPException(status_code=404, detail="No data available to generate question")
        
        return {
            "status": "success",
            "question": question,
            "source": "auto-generated"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating question: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/next")
async def delete_next_question(
    db = Depends(get_db),
):
    """Remove and archive next question"""
    try:
        deleted = await question_manager.remove_first_question(db)
        if not deleted:
            raise HTTPException(status_code=404, detail="No questions to delete")
        return {
            "status": "success",
            "message": "Question archived successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting question: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stats")
async def get_stats(
    db = Depends(get_db),
):
    """Get question statistics"""
    try:
        stats = await question_manager.get_question_stats(db)
        return {
            "status": "success",
            "stats": stats
        }
    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/reset")
async def reset_queue(
    db = Depends(get_db),
):
    """Reset question queue"""
    try:
        count = await question_manager.reset_question_queue(db)
        return {
            "status": "success",
            "message": f"Queue reset with {count} questions"
        }
    except Exception as e:
        logger.error(f"Error resetting queue: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/archive")
async def get_archive(
    limit: int = Query(100, ge=1, le=1000),
    db = Depends(get_db),
):
    """Get archived questions"""
    try:
        archive = await question_manager.get_archive(db, limit=limit)
        return {
            "status": "success",
            "count": len(archive),
            "archive": archive
        }
    except Exception as e:
        logger.error(f"Error getting archive: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================
# N8N AUTOMATION ENDPOINTS
# ============================================

@router.get("/n8n/status")
async def n8n_status(
    db = Depends(get_db),
):
    """N8N: Get queue status for monitoring"""
    try:
        pending_count = await question_manager.get_question_count(db)
        stats = await question_manager.get_question_stats(db)
        
        next_q = await question_manager.get_next_question(db)
        next_text = next_q.get("text") if next_q else None
        
        emails = await get_all_emails(db)
        email_count = len(emails)
        email_list = [e.get("email") for e in emails if e.get("email")]
        
        return {
            "status": "operational",
            "queue_size": pending_count,
            "stats": stats,
            "next_question": next_text,
            "ready_for_processing": pending_count > 0,
            "email_recipients": email_count,
            "emails": email_list[:10],
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Error getting n8n status: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/n8n/generate")
async def n8n_generate_question(
    db = Depends(get_db),
    num_questions: int = Query(5, ge=1, le=10, description="Number of questions to generate"),
    complexity: str = Query("medium", description="Question complexity: simple, medium, complex"),
    topic: Optional[str] = Query(None, description="Specific topic to focus on")
):
    """N8N: Generate questions using LLM"""
    try:
        from src.services.question_manager import n8n_generate_questions_with_llm
        
        questions = await n8n_generate_questions_with_llm(
            db=db,
            topic=topic,
            complexity=complexity,
            num_questions=num_questions
        )
        
        if not questions:
            return {
                "status": "warning",
                "message": "No questions generated",
                "questions": [],
                "count": 0
            }
        
        return {
            "status": "success",
            "questions": questions,
            "count": len(questions),
            "source": "llm-generated",
            "complexity": complexity,
            "topic": topic or "general"
        }
    except Exception as e:
        logger.error(f"Error in n8n generation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/n8n/process-and-refill")
async def n8n_process_and_refill(
    db = Depends(get_db),
    num_to_generate: int = Query(5, ge=1, le=20, description="Number of new questions to generate"),
    language: str = Query("en", description="Response language")
):
    """N8N: Process next question and refill queue with LLM-generated questions"""
    try:
        from src.services.agent import ask_agent
        from src.services.question_manager import n8n_generate_questions_with_llm
        
        question_data = await question_manager.get_next_question(db)
        
        if not question_data:
            logger.info("📭 No pending questions, generating new ones...")
            new_questions = await n8n_generate_questions_with_llm(
                db=db,
                num_questions=num_to_generate
            )
            
            for q in new_questions:
                await question_manager.add_question(db, q, source="n8n-refill")
            
            question_data = await question_manager.get_next_question(db)
            
            if not question_data:
                return {
                    "status": "warning",
                    "message": "No questions available even after generation",
                    "queue_remaining": await question_manager.get_question_count(db),
                    "question": None,
                    "response": None,
                    "processing_time": 0,
                    "iterations": 0
                }
        
        question_text = question_data.get("text", "")
        
        logger.info(f"📝 Processing question: {question_text[:100]}...")
        
        result = await ask_agent(
            question=question_text,
            db=db,
            language=language,
            channel="api"
        )
        
        processing_time = result.get("processing_time", 0)
        
        await question_manager.remove_first_question(db)
        
        new_questions = await n8n_generate_questions_with_llm(
            db=db,
            num_questions=num_to_generate
        )
        
        added_count = 0
        for q in new_questions:
            if await question_manager.add_question(db, q, source="n8n-refill"):
                added_count += 1
        
        pending_count = await question_manager.get_question_count(db)
        next_q = await question_manager.get_next_question(db)
        next_text = next_q.get("text") if next_q else None
        
        emails = await get_all_emails(db)
        email_list = [e.get("email") for e in emails if e.get("email")]
        
        if result.get("success"):
            history_data = SentHistoryCreate(
                question=question_text,
                answer=result.get("answer", ""),
                channel=ChannelType.N8N,
                status=DeliveryStatus.SENT,
                processing_time=processing_time,
                iterations=result.get("attempts", 1),
                response_type=result.get("response_type", "answer"),
                language=language,
                recipients=email_list,
                recipient_count=len(email_list),
                sources=result.get("sources", []),
                thread_id=result.get("thread_id"),
                user_id="system",
                username="n8n-automation"
            )
            
            await create_history_entry(
                db=db,
                history_data=history_data,
                user_id="system",
                username="n8n-automation"
            )
            logger.info(f"✅ History logged for question: {question_text[:50]}...")
        
        return {
            "status": "success" if result.get("success") else "warning",
            "question": question_text,
            "response": result.get("answer", ""),
            "processing_time": processing_time,
            "iterations": result.get("attempts", 1),
            "response_type": result.get("response_type", "answer"),
            "sources": result.get("sources", []),
            "queue_remaining": pending_count,
            "next_question": next_text,
            "new_questions_generated": added_count,
            "email_recipients": email_list,
            "email_count": len(email_list),
            "timestamp": datetime.utcnow().isoformat(),
            "message": f"Processed question and refilled queue with {added_count} new questions"
        }
        
    except Exception as e:
        logger.error(f"Error in n8n process: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/n8n/refill")
async def n8n_refill_queue(
    db = Depends(get_db),
    num_questions: int = Query(10, ge=1, le=20, description="Number of questions to generate"),
    complexity: str = Query("medium", description="Question complexity"),
    topic: Optional[str] = Query(None, description="Topic to focus on")
):
    """N8N: Refill the question queue with LLM-generated questions"""
    try:
        from src.services.question_manager import n8n_generate_questions_with_llm
        
        questions = await n8n_generate_questions_with_llm(
            db=db,
            topic=topic,
            complexity=complexity,
            num_questions=num_questions
        )
        
        added_count = 0
        for q in questions:
            if await question_manager.add_question(db, q, source="n8n-refill"):
                added_count += 1
        
        return {
            "status": "success",
            "generated": len(questions),
            "added": added_count,
            "questions": questions,
            "queue_remaining": await question_manager.get_question_count(db),
            "message": f"Added {added_count} new questions to the queue"
        }
    except Exception as e:
        logger.error(f"Error refilling queue: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")