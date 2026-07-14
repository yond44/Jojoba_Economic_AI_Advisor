import logging
from fastapi.responses import JSONResponse
from fastapi import APIRouter, Depends, HTTPException, Request, Query as QueryParam
import time
from datetime import datetime
from typing import Optional, Dict, Any
import re

from src.config.database import get_db
from src.auth.auth import get_current_user
from src.middleware.rate_limiter import check_rate_limit
from src.services.agent import (
    ask_agent, 
    get_agent_status,
    get_conversation_summary,
    clear_old_conversations,
    get_graph_app
)
from src.models.agent import (
    QueryRequest, 
    QueryResponse, 
    BatchEmailRequest,
    ConversationContext
)
from src.models.user import UserInDB
from src.services.user_queries import (
    log_user_query,
    get_user_queries,
    get_user_query_stats,
    delete_user_query,
    export_user_queries,
    search_user_queries
)
from src.services.rag import get_rag_status, get_cache_stats, clear_query_cache

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["agent"])


# ============================================
# FORMATTING HELPER FUNCTIONS
# ============================================

def clean_markdown_response(text: str) -> str:
    """Clean up ugly markdown and return formatted plain text"""
    if not text:
        return text
    
    lines = text.split('\n')
    seen = set()
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in seen:
            continue
        seen.add(stripped)
        cleaned_lines.append(line)
    text = '\n'.join(cleaned_lines)
    
    text = re.sub(r'\*\*(.*?)\*\*', r'\1', text)
    text = re.sub(r'\*(.*?)\*', r'\1', text)
    text = re.sub(r'__(.*?)__', r'\1', text)
    text = re.sub(r'_(.*?)_', r'\1', text)
    text = re.sub(r'~~(.*?)~~', r'\1', text)
    
    text = re.sub(r'^#+ ', '', text, flags=re.MULTILINE)
    
    text = re.sub(r'\[(.*?)\]\(.*?\)', r'\1', text)
    
    text = re.sub(r'`(.*?)`', r'\1', text)
    
    text = re.sub(r'^[\s]*[-*•]\s+', '• ', text, flags=re.MULTILINE)
    
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    
    text = re.sub(r'\n{3,}', '\n\n', text)
    
    lines = text.split('\n')
    cleaned = []
    for line in lines:
        line = line.strip()
        if line:
            cleaned.append(line)
    
    result = '\n'.join(cleaned)
    
    result = re.sub(r'\*\*', '', result)
    result = re.sub(r'\*', '', result)
    result = re.sub(r'__', '', result)
    result = re.sub(r'_', '', result)
    
    return result


def format_response_for_display(response: str, response_type: str = "text") -> dict:
    """
    Format response for different display types
    Returns both plain text and formatted versions
    """
    cleaned_text = clean_markdown_response(response)
    
    html_text = cleaned_text.replace('\n', '<br>')
    
    html_text = re.sub(r'• (.*?)(?=<br>|$)', r'<li>\1</li>', html_text)
    html_text = re.sub(r'(<li>.*?</li>)', r'<ul style="margin: 10px 0; padding-left: 20px;">\1</ul>', html_text, flags=re.DOTALL)
    
    html_text = re.sub(r'\*\*(.*?)\*\*', r'<strong>\1</strong>', html_text)
    
    return {
        "plain_text": cleaned_text,
        "html": html_text,
        "type": response_type
    }


# ============================================
# QUERY ENDPOINTS
# ============================================

@router.post("/ask", response_model=QueryResponse)
async def ask(
    request: QueryRequest,
    http_request: Request,
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db),
    rate_limit: bool = Depends(check_rate_limit),
):
    """
    Ask the agent a question with full context management
    """
    if not rate_limit:
        logger.warning(f"⚠️ Rate limit exceeded for user {current_user.username}")
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Maximum 10 requests per minute."
        )
    
    try:
        client_ip = http_request.client.host if http_request.client else "unknown"
        logger.info(f"👤 User: {current_user.username} ({current_user.id}) | IP: {client_ip}")
        logger.info(f"❓ Question: {request.question[:100]}...")
        logger.info(f"🔗 Thread: {request.thread_id}")
        
        start_time = time.time()
        
        try:
            request_validated = QueryRequest(**request.dict())
        except Exception as e:
            logger.error(f"❌ Request validation failed: {str(e)}")
            raise HTTPException(status_code=400, detail=f"Invalid request: {str(e)}")
        
        result = await ask_agent(
            question=request_validated.question,
            thread_id=request_validated.thread_id,
            db=db,
            user_id=str(current_user.id),
            username=current_user.username,
            language=request_validated.metadata.get("language", "en") if request_validated.metadata else "en",
            channel=request_validated.channel.value if request_validated.channel else "api"
        )
        
        if result.get("answer"):
            format_type = request_validated.metadata.get("format", "plain") if request_validated.metadata else "plain"
            
            cleaned_answer = clean_markdown_response(result["answer"])
            
            if format_type == "html":
                formatted = format_response_for_display(cleaned_answer, "html")
                result["answer"] = formatted["html"]
                result["formatted"] = formatted
                result["plain_text"] = formatted["plain_text"]
            else:
                result["answer"] = cleaned_answer
        
        processing_time = time.time() - start_time
        
        logger.info(f"✅ Processed in {processing_time:.3f}s")
        logger.info(f"📊 Type: {result.get('response_type')} | Success: {result.get('success')}")
        logger.info(f"📚 Sources: {len(result.get('sources', []))} | Recommendations: {len(result.get('recommendations', []))}")
        
        try:
            await log_user_query(
                db=db,
                user_id=str(current_user.id),
                question=request_validated.question,
                answer=result.get("answer", ""),
                processing_time=processing_time,
                attempts=result.get("attempts", 1),
                thread_id=request_validated.thread_id,
                channel=request_validated.channel.value if request_validated.channel else "api",
                success=result.get("success", False),
                validated=result.get("validated", False),
                sources_count=len(result.get("sources", [])),
                error=result.get("error"),
                response_type=result.get("response_type", "answer"),
                language_detected=result.get("language_detected", "en")
            )
        except Exception as e:
            logger.warning(f"⚠️ Failed to log query: {str(e)}")
        
        response = QueryResponse(
            question=request_validated.question,
            answer=result["answer"],
            processing_time=processing_time,
            thread_id=request_validated.thread_id,
            language_detected=result.get("language_detected", "en"),
            response_type=result.get("response_type", "answer"),
            success=result.get("success", False),
            validated=result.get("validated", False),
            greeting=result.get("greeting", False),
            gratitude=result.get("gratitude", False),
            sources=result.get("sources", []),
            recommendations=result.get("recommendations", []),
            error=result.get("error"),
            user_id=str(current_user.id),
            attempts=result.get("attempts", 1)
        )
        
        logger.info(f"✅ Response sent to {current_user.username}")
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Query error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ============================================
# CLEAN RESPONSE ENDPOINT (NEW)
# ============================================

@router.post("/ask/clean")
async def ask_clean(
    request: QueryRequest,
    http_request: Request,
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db),
    rate_limit: bool = Depends(check_rate_limit),
):
    """
    Ask the agent with clean formatted response
    Returns both plain text and HTML versions
    """
    if not rate_limit:
        logger.warning(f"⚠️ Rate limit exceeded for user {current_user.username}")
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Maximum 10 requests per minute."
        )
    
    try:
        start_time = time.time()
        
        result = await ask_agent(
            question=request.question,
            thread_id=request.thread_id,
            db=db,
            user_id=str(current_user.id),
            username=current_user.username,
            language=request.metadata.get("language", "en") if request.metadata else "en",
            channel=request.channel.value if request.channel else "api"
        )
        
        processing_time = time.time() - start_time
        
        cleaned_answer = clean_markdown_response(result.get("answer", ""))
        
        html_answer = cleaned_answer.replace('\n', '<br>')
        html_answer = re.sub(r'• (.*?)(?=<br>|$)', r'<li>\1</li>', html_answer)
        html_answer = re.sub(r'(<li>.*?</li>)', r'<ul style="margin: 10px 0; padding-left: 20px;">\1</ul>', html_answer, flags=re.DOTALL)
        
        return {
            "success": True,
            "question": request.question,
            "answer": {
                "plain": cleaned_answer,
                "html": html_answer
            },
            "processing_time": processing_time,
            "response_type": result.get("response_type", "answer"),
            "thread_id": request.thread_id,
            "sources": result.get("sources", []),
            "recommendations": result.get("recommendations", []),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Query error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/batch-email")
async def batch_email(
    request: BatchEmailRequest,
    http_request: Request,
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db),
):
    try:
        logger.info(f"📧 Batch email request from {current_user.username}")
        logger.info(f"   Recipients: {len(request.emails)} | Frequency: {request.frequency}")
        
        from src.services.agent import batch_processor
        
        batch_processor._current_user_id = str(current_user.id)
        batch_processor._current_username = current_user.username
        
        try:
            result = await batch_processor.process_batch(request, db=db)
        finally:
            batch_processor._current_user_id = None
            batch_processor._current_username = None
        
        logger.info(f"✅ Batch {result['batch_id']} created with status: {result.get('status')}")
        return result
        
    except Exception as e:
        logger.error(f"❌ Batch email error: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/conversation/{thread_id}")
async def get_conversation(
    thread_id: str,
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db)
):
    try:
        logger.info(f"📖 Fetching conversation {thread_id} for {current_user.username}")
        
        summary = get_conversation_summary(thread_id)
        
        if not summary:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        return {
            "success": True,
            "data": summary
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error fetching conversation: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/history")
async def get_query_history(
    skip: int = QueryParam(0, ge=0),
    limit: int = QueryParam(10, ge=1, le=100),
    days: Optional[int] = QueryParam(None, ge=1, le=365),
    response_type: Optional[str] = QueryParam(None),
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db)
):
    try:
        logger.info(f"📜 Fetching query history for {current_user.username}")
        
        queries, total = await get_user_queries(
            db=db,
            user_id=str(current_user.id),
            skip=skip,
            limit=limit,
            days=days,
            response_type=response_type
        )
        
        logger.info(f"✅ Retrieved {len(queries)} of {total} queries")
        
        return {
            "user_id": str(current_user.id),
            "username": current_user.username,
            "queries": queries,
            "pagination": {
                "total": total,
                "skip": skip,
                "limit": limit,
                "remaining": max(0, total - skip - limit)
            },
            "filters": {
                "days": days,
                "response_type": response_type
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Error fetching query history: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/stats")
async def get_query_stats(
    days: int = QueryParam(30, ge=1, le=365),
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db)
):
    try:
        logger.info(f"📊 Computing stats for {current_user.username}")
        
        stats = await get_user_query_stats(
            db=db,
            user_id=str(current_user.id),
            days=days
        )
        
        logger.info(f"✅ Stats computed")
        
        return {
            "user_id": str(current_user.id),
            "username": current_user.username,
            "period_days": days,
            "computed_at": datetime.utcnow().isoformat(),
            "stats": stats
        }
        
    except Exception as e:
        logger.error(f"❌ Error fetching query stats: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/search")
async def search_queries(
    q: str = QueryParam(..., min_length=1, max_length=200),
    skip: int = QueryParam(0, ge=0),
    limit: int = QueryParam(10, ge=1, le=100),
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db)
):
    try:
        logger.info(f"🔍 Searching queries for {current_user.username}")
        
        results, total = await search_user_queries(
            db=db,
            user_id=str(current_user.id),
            search_term=q,
            skip=skip,
            limit=limit
        )
        
        logger.info(f"✅ Found {total} matching queries")
        
        return {
            "search_query": q,
            "results": results,
            "total": total,
            "pagination": {
                "skip": skip,
                "limit": limit
            }
        }
        
    except Exception as e:
        logger.error(f"❌ Search error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/export")
async def export_queries(
    format: str = QueryParam("json", pattern="^(json|csv)$"),
    days: Optional[int] = QueryParam(None, ge=1, le=365),
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db)
):
    try:
        logger.info(f"📥 Exporting queries for {current_user.username}")
        
        exported_data = await export_user_queries(
            db=db,
            user_id=str(current_user.id),
            format=format,
            days=days
        )
        
        logger.info(f"✅ Export completed")
        
        return {
            "success": True,
            "format": format,
            "data": exported_data,
            "exported_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        logger.error(f"❌ Export error: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.delete("/query/{query_id}")
async def delete_query(
    query_id: str,
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db)
):
    try:
        logger.info(f"🗑️ Delete request for query {query_id}")
        
        success = await delete_user_query(
            db=db,
            query_id=query_id,
            user_id=str(current_user.id)
        )
        
        if not success:
            raise HTTPException(status_code=404, detail="Query not found")
        
        logger.info(f"✅ Query deleted")
        
        return {
            "success": True,
            "message": "Query deleted successfully",
            "query_id": query_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error deleting query: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/health")
async def health_check():
    try:
        return {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "version": "2.0.0"
        }
        
    except Exception as e:
        logger.error(f"❌ Health check failed: {str(e)}")
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "timestamp": datetime.utcnow().isoformat(),
            },
        )