"""Question generation/serving logs."""
import os
import logging
import random
import re
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path
from bson import ObjectId

logger = logging.getLogger(__name__)

async def log_question(
    db: "AsyncIOMotorDatabase",
    question: str,
    answer: str,
    processing_time: float,
    iterations: int,
    thread_id: Optional[str] = None,
    channel: Optional[str] = "api",
    success: bool = True
) -> bool:
    """Log question and answer to MongoDB"""
    try:
        collection = db["question_logs"]
        
        log_doc = {
            "question": question,
            "answer": answer,
            "processing_time": processing_time,
            "iterations": iterations,
            "thread_id": thread_id or "anonymous",
            "channel": channel,
            "success": success,
            "logged_at": datetime.utcnow()
        }
        
        result = await collection.insert_one(log_doc)
        logger.info(f"📝 Question logged: {result.inserted_id}")
        return bool(result.inserted_id)
    except Exception as e:
        logger.error(f"❌ Error logging question: {str(e)}")
        return False

async def get_question_logs(
    db: "AsyncIOMotorDatabase",
    limit: int = 100,
    success_only: bool = False
) -> List[Dict[str, Any]]:
    """Get question logs from MongoDB"""
    try:
        collection = db["question_logs"]
        
        query = {}
        if success_only:
            query["success"] = True
        
        logs = []
        cursor = collection.find(query).sort("logged_at", -1).limit(limit)
        
        async for log in cursor:
            log["_id"] = str(log["_id"])
            logs.append(log)
        
        logger.info(f"📋 Retrieved {len(logs)} question logs")
        return logs
    except Exception as e:
        logger.error(f"❌ Error getting logs: {str(e)}")
        return []

async def get_question_log_stats(
    db: "AsyncIOMotorDatabase"
) -> Dict[str, Any]:
    """Get statistics on question logs"""
    try:
        collection = db["question_logs"]
        
        total = await collection.count_documents({})
        successful = await collection.count_documents({"success": True})
        failed = await collection.count_documents({"success": False})
        
        pipeline = [
            {
                "$group": {
                    "_id": None,
                    "avg_time": {"$avg": "$processing_time"},
                    "avg_iterations": {"$avg": "$iterations"}
                }
            }
        ]
        
        avg_stats = []
        async for doc in collection.aggregate(pipeline):
            avg_stats.append(doc)
        
        return {
            "total_questions": total,
            "successful": successful,
            "failed": failed,
            "success_rate": (successful / total * 100) if total > 0 else 0,
            "avg_processing_time": avg_stats[0]["avg_time"] if avg_stats else 0,
            "avg_iterations": avg_stats[0]["avg_iterations"] if avg_stats else 0
        }
    except Exception as e:
        logger.error(f"❌ Error getting stats: {str(e)}")
        return {}

async def clear_question_logs(db: "AsyncIOMotorDatabase") -> bool:
    """Clear all question logs (DESTRUCTIVE)"""
    try:
        collection = db["question_logs"]
        result = await collection.delete_many({})
        logger.warning(f"🗑️ Cleared {result.deleted_count} question logs")
        return True
    except Exception as e:
        logger.error(f"❌ Error clearing logs: {str(e)}")
        return False

async def export_question_logs(
    db: "AsyncIOMotorDatabase",
    format: str = "json"
) -> Optional[str]:
    """Export question logs"""
    try:
        import json
        
        logs = await get_question_logs(db, limit=10000)
        
        if format == "json":
            return json.dumps(logs, indent=2, default=str)
        elif format == "csv":
            if not logs:
                return "question,answer,processing_time,iterations,thread_id,channel,success,logged_at"
            
            lines = ["question,answer,processing_time,iterations,thread_id,channel,success,logged_at"]
            for log in logs:
                question = log.get("question", "").replace(",", ";")
                answer = log.get("answer", "")[:100].replace(",", ";")
                processing_time = log.get("processing_time", 0)
                iterations = log.get("iterations", 0)
                thread_id = log.get("thread_id", "")
                channel = log.get("channel", "")
                success = log.get("success", False)
                logged_at = log.get("logged_at", "")
                
                lines.append(
                    f"{question},{answer},{processing_time},{iterations},{thread_id},{channel},{success},{logged_at}"
                )
            
            return "\n".join(lines)
        
        return None
    except Exception as e:
        logger.error(f"❌ Error exporting logs: {str(e)}")
        return None
