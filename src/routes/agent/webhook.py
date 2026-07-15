import json
import time
import logging
from fastapi import APIRouter, Depends, Request, HTTPException, Header, Query as QueryParam
from datetime import datetime
from typing import Optional, List, Dict, Any
from pymongo.errors import PyMongoError

from src.middleware.rate_limiter import check_rate_limit
from src.auth.auth import get_current_user
from src.config.database import get_db
from src.models.user import UserInDB
from src.models.agent import BatchEmailRequest
from src.services.agent import ask_agent, get_agent_status, batch_processor
from src.services.email_manager import get_all_emails
from src.services.question_manager import (
    get_question_count,
    get_next_question,
    remove_first_question,
    add_question,
    generate_new_question_from_data,
    get_default_fallback_questions
)
from src.utils.question_logger import log_question

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/webhook", tags=["webhook"])


# ============================================
# HELPER FUNCTIONS
# ============================================

def validate_webhook_secret(request: Request, expected_secret: Optional[str] = None) -> bool:
    """Validate webhook secret if configured"""
    if not expected_secret:
        return True
    secret = request.headers.get("X-Webhook-Secret")
    return secret == expected_secret


def extract_question_text(question: Any) -> str:
    """Extract question text from various formats"""
    if isinstance(question, str):
        return question
    elif isinstance(question, dict):
        return question.get("text", question.get("question", str(question)))
    elif hasattr(question, "text"):
        return question.text
    elif hasattr(question, "question"):
        return question.question
    else:
        return str(question)


async def get_recipient_emails(db, provided_emails: Optional[List[str]] = None) -> List[str]:
    if provided_emails and isinstance(provided_emails, list):
        return [e.strip() for e in provided_emails if isinstance(e, str) and e.strip()]
    
    try:
        contacts = await get_all_emails(db)
        emails = [c.get("email") for c in contacts if c.get("email")]
        logger.info(f"📧 Retrieved {len(emails)} emails from database")
        return emails
    except Exception as e:
        logger.warning(f"⚠️ Error retrieving emails: {str(e)}")
        return []


# ============================================
# MAIN ASK ENDPOINT
# ============================================

@router.post("/ask")
async def webhook_ask(
    request: Request,
    rate_limit: bool = Depends(check_rate_limit),
    db = Depends(get_db),
    current_user: UserInDB = Depends(get_current_user)
):
    """Ask the agent a question and persist the turn to chat_sessions/chat_messages.

    This endpoint does exactly one job: save the user's question, get the
    agent's answer, save that answer, and hand back the chat_id so the
    conversation can be reloaded through the normal chat_routes API
    (GET /api/v1/chats/{chat_id}) — the same records that endpoint reads.
    """
    from src.services import chat_manager as cm

    if not rate_limit:
        logger.warning("⚠️ Rate limit exceeded on webhook")
        raise HTTPException(status_code=429, detail="Too many requests")

    status_data = await get_agent_status()
    if not status_data.get("initialized"):
        raise HTTPException(status_code=503, detail="Agent not initialized")

    try:
        body = await request.json()
    except Exception as e:
        logger.error(f"❌ Invalid JSON: {str(e)}")
        raise HTTPException(status_code=400, detail="Invalid JSON format")

    question = (
        body.get("question") or
        body.get("message") or
        body.get("text") or
        body.get("prompt")
    )

    if not question or not isinstance(question, str) or not question.strip():
        raise HTTPException(status_code=400, detail="No question provided")

    question = question.strip()
    language = body.get("language", "en")
    chat_id = body.get("thread_id") or body.get("chat_id")
    user_id = str(current_user.id)

    logger.info(f"📨 Ask: {question[:100]}...")
    start_time = time.time()

    try:
        if chat_id:
            try:
                await cm.get_chat(db, user_id, chat_id)
            except Exception:
                chat_id = None

        if not chat_id:
            chat = await cm.create_chat(
                db, user_id, title=f"Chat: {question[:50]}", first_message=question
            )
            chat_id = chat["id"] if isinstance(chat, dict) else chat.id
            logger.info(f"✅ Created new chat session: {chat_id}")

        result = await ask_agent(
            question=question,
            thread_id=chat_id,
            db=db,
            user_id=user_id,
            username=current_user.username,
            language=language,
            channel="webhook",
        )

        await cm.append_turn(
            db, user_id, chat_id,
            question,
            result.get("answer", ""),
            sources=result.get("sources", []),
            groundedness=result.get("groundedness"),
        )

        processing_time = time.time() - start_time
        logger.info(f"✅ Ask processed + saved in {processing_time:.2f}s (chat {chat_id})")

        return {
            "status": "success" if result.get("success") else "error",
            "timestamp": datetime.utcnow().isoformat(),
            "chat_id": chat_id,
            "thread_id": chat_id,
            "question": question,
            "answer": result.get("answer", ""),
            "sources": result.get("sources", []),
            "groundedness": result.get("groundedness"),
            "processing_time_seconds": round(processing_time, 3),
            "response_type": result.get("response_type", "answer"),
            "language_detected": result.get("language_detected", language),
            "error": result.get("error"),
        }

    except HTTPException:
        raise
    except PyMongoError as e:
        logger.error(f"❌ MongoDB error in /ask: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Ask error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================
# QUEUE PROCESSING WEBHOOK
# ============================================

@router.post("/process-next")
async def webhook_process_next(
    rate_limit: bool = Depends(check_rate_limit),
    db = Depends(get_db),
    send_email: bool = QueryParam(False),
    language: str = QueryParam("en"),
    x_webhook_token: Optional[str] = Header(None, alias="X-Webhook-Token"),
):
    """Process next question in queue and optionally send via email.

    ISOLATION: if the caller presents an X-Webhook-Token (the per-user JWT the
    app mints when deploying an n8n workflow), this endpoint behaves exactly
    like /api/webhook/user/process-next — THAT user's queue and THAT user's
    isolated recipient list (user_emails), never the shared collection. Without
    a token it keeps the original single-tenant behavior (shared queue +
    shared emails collection) for backward compatibility.
    """

    if not rate_limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    status_data = await get_agent_status()
    if not status_data.get("initialized"):
        raise HTTPException(status_code=503, detail="Agent not initialized")

    if x_webhook_token:
        from src.auth.auth import verify_token
        from src.routes.webhook_user import process_next_for_user
        try:
            payload = verify_token(x_webhook_token)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid X-Webhook-Token")
        purpose = payload.get("purpose")
        if purpose and purpose != "n8n-webhook":
            raise HTTPException(status_code=403, detail="Token not intended for n8n webhook")
        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token has no user_id")
        return await process_next_for_user(
            db, user_id, language=language, send_email=send_email
        )


    try:
        start_time = time.time()
        
        question = await get_next_question(db)
        question_text = extract_question_text(question) if question else None
        
        if not question_text:
            logger.info("📭 Queue empty, generating new question...")
            new_q = await generate_new_question_from_data(db)
            
            if not new_q:
                fallbacks = get_default_fallback_questions()
                for fb in fallbacks:
                    await add_question(db, fb)
                new_q = await get_next_question(db)
            
            if new_q:
                await add_question(db, new_q)
                question = await get_next_question(db)
                question_text = extract_question_text(question) if question else None
        
        if not question_text:
            return {
                "status": "error",
                "message": "No questions available",
                "queue_size": await get_question_count(db),
                "timestamp": datetime.utcnow().isoformat()
            }
        
        preview = question_text[:100] + "..." if len(question_text) > 100 else question_text
        logger.info(f"📝 Processing queue question: {preview}")
        
        result = await ask_agent(
            question=question_text,
            db=db,
            language=language,
            channel="webhook"
        )
        
        processing_time = time.time() - start_time
        
        try:
            await log_question(
                db,
                question=question_text,
                answer=result.get("answer", ""),
                processing_time=processing_time,
                channel="webhook_queue",
                language=language,
                success=result.get("success", False)
            )
        except Exception as e:
            logger.warning(f"⚠️ Log error: {str(e)}")
        
        try:
            await remove_first_question(db)
            logger.info(f"✅ Removed from queue")
        except Exception as e:
            logger.warning(f"⚠️ Remove error: {str(e)}")
        
        try:
            new_question = await generate_new_question_from_data(db)
            if new_question:
                await add_question(db, new_question)
        except Exception as e:
            logger.warning(f"⚠️ Generation error: {str(e)}")
        
        try:
            recipient_emails = await get_recipient_emails(db)
            email_string_value = ", ".join(recipient_emails)
            email_count_value = len(recipient_emails)
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch recipients: {str(e)}")
            recipient_emails = []
            email_string_value = ""
            email_count_value = 0
        
        email_data = None
        if send_email:
            try:
                if recipient_emails:
                    from src.services.email_sender import send_batch_emails
                    email_result = await send_batch_emails(
                        to_emails=recipient_emails,
                        subject=f"Daily Economic Analysis: {question_text[:50]}...",
                        body=result.get("answer", ""),
                        html_body=None
                    )
                    email_data = {
                        "sent": True,
                        "recipients": len(recipient_emails),
                        "sent_count": email_result.get("sent_count", 0),
                        "failed_emails": email_result.get("failed_emails", [])
                    }
                    logger.info(f"📧 Sent to {email_data['sent_count']} recipients")
            except Exception as e:
                logger.error(f"❌ Email error: {str(e)}")
                email_data = {"sent": False, "error": str(e)}
        
        next_q = await get_next_question(db)
        next_text = extract_question_text(next_q) if next_q else None
        
        logger.info(f"✅ Queue processing complete in {processing_time:.2f}s")
        
        return {
            "status": "success" if result.get("success") else "error",
            "timestamp": datetime.utcnow().isoformat(),
            "question": question_text,
            "answer": result.get("answer", ""),
            "response": result.get("answer", ""),
            "processing_time_seconds": round(processing_time, 3),
            "processing_time": round(processing_time, 3),
            "iterations": result.get("attempts", 1),
            "response_type": result.get("response_type", "answer"),
            "queue_remaining": await get_question_count(db),
            "next_question": next_text,
            "email_string": email_string_value,
            "email_count": email_count_value,
            "recipients": recipient_emails,
            "email": email_data,
            "error": result.get("error")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Queue processing error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================
# BATCH EMAIL WEBHOOK
# ============================================

@router.post("/send-batch")
async def webhook_send_batch(
    request: BatchEmailRequest,
    rate_limit: bool = Depends(check_rate_limit),
    db = Depends(get_db)
):
    """Process question and send batch emails"""
    
    if not rate_limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")
    
    status_data = await get_agent_status()
    if not status_data.get("initialized"):
        raise HTTPException(status_code=503, detail="Agent not initialized")
    
    try:
        start_time = time.time()
        
        if not request.question or not request.emails:
            raise HTTPException(status_code=400, detail="Missing question or emails")
        
        logger.info(f"📧 Batch email request: {len(request.emails)} recipients")
        logger.info(f"❓ Question: {request.question[:100]}...")
        
        result = await ask_agent(
            question=request.question,
            db=db,
            language=request.language or "en",
            channel="batch_email"
        )
        
        processing_time = time.time() - start_time
        
        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=f"Failed to process question: {result.get('error')}"
            )
        
        answer = result.get("answer", "")
        
        try:
            await log_question(
                db,
                question=request.question,
                answer=answer,
                processing_time=processing_time,
                channel="batch_email",
                language=request.language or "en",
                success=True,
                recipient_count=len(request.emails)
            )
        except Exception as e:
            logger.warning(f"⚠️ Log error: {str(e)}")
        
        email_result = None
        try:
            from src.services.email_sender import send_batch_emails
            from src.utils.email_html import generate_economic_news_email
            
            logger.info(f"📧 Sending to {len(request.emails)} recipients...")
            
            html_body = generate_economic_news_email(
                question=request.question,
                answer=answer,
                processing_time=processing_time,
                iterations=result.get("attempts", 1),
                sources_count=len(result.get("sources", []))
            )
            
            email_result = await send_batch_emails(
                to_emails=request.emails,
                subject=request.subject or f"Economic Analysis: {request.question[:50]}...",
                body=answer,
                html_body=html_body
            )
            
            logger.info(f"✅ Sent to {email_result.get('sent_count', 0)} recipients")
            
        except Exception as e:
            logger.error(f"❌ Email sending error: {str(e)}")
            email_result = {
                "status": "error",
                "message": str(e),
                "sent_count": 0
            }
        
        logger.info(f"✅ Batch email complete in {processing_time:.2f}s")
        
        return {
            "status": "success" if email_result and email_result.get("sent_count", 0) > 0 else "partial",
            "timestamp": datetime.utcnow().isoformat(),
            "question": request.question,
            "answer_preview": answer[:500] + ("..." if len(answer) > 500 else ""),
            "total_recipients": len(request.emails),
            "sent_count": email_result.get("sent_count", 0) if email_result else 0,
            "failed_emails": email_result.get("failed_emails", []) if email_result else [],
            "processing_time_seconds": round(processing_time, 3),
            "iterations": result.get("attempts", 1),
            "simulated": email_result.get("simulated", False) if email_result else False,
            "error": email_result.get("message") if email_result and email_result.get("status") == "error" else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Batch email error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================
# WEBHOOK VALIDATION & TESTING
# ============================================

@router.post("/test")
async def test_webhook(
    request: Request,
    db = Depends(get_db)
):
    """Test webhook connectivity and agent status"""
    
    try:
        logger.info("🧪 Webhook test initiated")
        status = await get_agent_status()
        
        return {
            "status": "operational" if status.get("initialized") else "degraded",
            "agent_ready": status.get("initialized", False),
            "graph_compiled": status.get("graph_compiled", False),
            "queue_size": await get_question_count(db),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Test error: {str(e)}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }, 500


@router.get("/health")
async def webhook_health():
    """Webhook health check"""
    
    try:
        status_data = await get_agent_status()
        ready = status_data.get("initialized", False)
        
        response = {
            "status": "healthy" if ready else "degraded",
            "ready": ready,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return response if ready else (response, 503)
        
    except Exception as e:
        logger.error(f"❌ Health check error: {str(e)}")
        return {
            "status": "error",
            "error": str(e)
        }, 503