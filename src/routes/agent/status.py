import logging
from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime
from typing import Dict, Any
from bson import ObjectId

from src.config.database import get_db
from src.services.agent import get_agent_status
from src.services.rag import get_rag_status, get_cache_stats
from src.services.question_manager import get_question_count, get_archive

logger = logging.getLogger(__name__)

router = APIRouter(tags=["agent-status"])

# ============================================
# HELPER FUNCTIONS
# ============================================

def serialize_mongo(obj: Any) -> Any:
    """Convert MongoDB objects to JSON serializable format"""
    if obj is None:
        return None
    if isinstance(obj, ObjectId):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {key: serialize_mongo(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [serialize_mongo(item) for item in obj]
    if hasattr(obj, '__dict__'):
        return {key: serialize_mongo(value) for key, value in obj.__dict__.items() if not key.startswith('_')}
    return obj

def safe_response(data: Any) -> Any:
    """Ensure response is JSON serializable"""
    return serialize_mongo(data)


# ============================================
# PUBLIC STATUS ENDPOINTS (No Auth Required)
# ============================================

@router.get("/status")
async def get_agent_status_public(db=Depends(get_db)):
    """
    Get agent status - PUBLIC endpoint (no authentication required)
    """
    try:
        logger.info("🔍 Public status check requested")
        
        agent_status = await get_agent_status(db=db)
        agent_status = safe_response(agent_status)
        
        rag_status = get_rag_status()
        rag_status = safe_response(rag_status)
        
        cache_stats = get_cache_stats()
        cache_stats = safe_response(cache_stats)
        
        overall_health = "healthy"
        if not agent_status.get("initialized"):
            overall_health = "degraded"
        if not rag_status.get("initialized"):
            overall_health = "critical"
        
        response = {
            "status": "operational",
            "overall_health": overall_health,
            "initialized": agent_status.get("initialized", False),
            "graph_compiled": agent_status.get("graph_compiled", False),
            "agents": agent_status.get("agents", {}),
            "agents_count": len(agent_status.get("agents", {})),
            "active_conversations": agent_status.get("conversation_contexts", 0),
            "rag": {
                "initialized": rag_status.get("initialized", False),
                "documents": rag_status.get("metrics", {}).get("total_documents", 0),
                "chunks": rag_status.get("metrics", {}).get("total_chunks", 0)
            },
            "cache": {
                "hit_rate": cache_stats.get("hit_rate", "0%"),
                "total_queries": cache_stats.get("total_cached_queries", 0)
            },
            "metrics": {
                "total_queries": agent_status.get("metrics", {}).get("total_queries", 0),
                "successful_queries": agent_status.get("metrics", {}).get("successful_queries", 0),
                "failed_queries": agent_status.get("metrics", {}).get("failed_queries", 0),
                "success_rate": agent_status.get("metrics", {}).get("success_rate", "N/A"),
            },
            "timestamp": datetime.utcnow().isoformat(),
            "version": "1.0.0"
        }
        
        return safe_response(response)
        
    except Exception as e:
        logger.error(f"❌ Status error: {str(e)}", exc_info=True)
        return safe_response({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500


@router.get("/health")
async def health_check_public(db=Depends(get_db)):
    """
    Health check - PUBLIC endpoint (no authentication required)
    """
    try:
        logger.debug("🏥 Public health check initiated")
        
        checks = {
            "agent": False,
            "rag": False,
            "database": False
        }
        
        try:
            agent_status = await get_agent_status(db=db)
            agent_status = safe_response(agent_status)
            checks["agent"] = agent_status.get("initialized", False)
        except Exception as e:
            logger.warning(f"⚠️ Agent check failed: {str(e)}")
        
        try:
            rag_status = get_rag_status()
            rag_status = safe_response(rag_status)
            checks["rag"] = rag_status.get("initialized", False)
        except Exception as e:
            logger.warning(f"⚠️ RAG check failed: {str(e)}")
        
        checks["database"] = db is not None
        
        healthy_checks = sum(1 for v in checks.values() if v)
        total_checks = len(checks)
        
        if healthy_checks == total_checks:
            overall_status = "healthy"
            status_code = 200
        elif healthy_checks >= total_checks - 1:
            overall_status = "degraded"
            status_code = 200
        else:
            overall_status = "unhealthy"
            status_code = 503
        
        response = {
            "status": overall_status,
            "checks": checks,
            "healthy_components": healthy_checks,
            "total_components": total_checks,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        response = safe_response(response)
        
        if status_code != 200:
            return response, status_code
        
        return response
        
    except Exception as e:
        logger.error(f"❌ Health check failed: {str(e)}", exc_info=True)
        return safe_response({
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 503


@router.get("/ready")
async def readiness_check_public(db=Depends(get_db)):
    """
    Readiness check - PUBLIC endpoint (no authentication required)
    """
    try:
        logger.debug("🚀 Public readiness check initiated")
        
        agent_ok = False
        rag_ok = False
        db_ok = db is not None
        
        try:
            agent_status = await get_agent_status(db=db)
            agent_status = safe_response(agent_status)
            agent_ok = agent_status.get("initialized", False) and agent_status.get("graph_compiled", False)
        except:
            pass
        
        try:
            rag_status = get_rag_status()
            rag_status = safe_response(rag_status)
            rag_ok = rag_status.get("initialized", False)
        except:
            pass
        
        ready = agent_ok and rag_ok and db_ok
        
        response = {
            "ready": ready,
            "checks": {
                "agent": agent_ok,
                "rag": rag_ok,
                "database": db_ok
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        response = safe_response(response)
        
        if not ready:
            return response, 503
        
        return response
        
    except Exception as e:
        logger.error(f"❌ Readiness check failed: {str(e)}")
        return safe_response({
            "ready": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 503


@router.get("/live")
async def liveness_check_public():
    """
    Liveness check - PUBLIC endpoint (no authentication required)
    """
    try:
        return {
            "alive": True,
            "timestamp": datetime.utcnow().isoformat(),
            "service": "Economic Advisor API"
        }
    except Exception as e:
        logger.error(f"❌ Liveness check failed: {str(e)}")
        return {
            "alive": False,
            "error": str(e)
        }, 503


@router.get("/queue")
async def get_queue_status_public():
    """
    Queue status - PUBLIC endpoint (no authentication required)
    """
    try:
        from src.services.question_manager import get_question_count, get_archive
        
        current = get_question_count()
        archived = len(get_archive())
        
        health = "healthy"
        if current == 0:
            health = "empty"
        elif current > 5000:
            health = "warning"
        elif current > 10000:
            health = "critical"
        
        response = {
            "status": health,
            "queue": {
                "current": current,
                "archived": archived,
                "total_processed": current + archived
            },
            "health": health,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return safe_response(response)
        
    except Exception as e:
        logger.error(f"❌ Queue status error: {str(e)}")
        return safe_response({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500


@router.get("/cache")
async def get_cache_status_public():
    """
    Cache status - PUBLIC endpoint (no authentication required)
    """
    try:
        cache_stats = get_cache_stats()
        cache_stats = safe_response(cache_stats)
        
        response = {
            "status": "operational",
            "statistics": {
                "total_cached": cache_stats.get("total_cached_queries"),
                "valid_entries": cache_stats.get("valid_entries"),
                "expired_entries": cache_stats.get("expired_entries")
            },
            "performance": {
                "hit_rate": cache_stats.get("hit_rate"),
                "total_hits": cache_stats.get("total_hits"),
                "total_misses": cache_stats.get("total_misses")
            },
            "memory": {
                "used_mb": cache_stats.get("total_size_mb"),
                "max_mb": cache_stats.get("max_size_mb"),
                "ttl_seconds": cache_stats.get("cache_ttl_seconds")
            },
            "top_queries": cache_stats.get("top_cached_queries", []),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return safe_response(response)
        
    except Exception as e:
        logger.error(f"❌ Cache status error: {str(e)}")
        return safe_response({
            "status": "error",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }), 500