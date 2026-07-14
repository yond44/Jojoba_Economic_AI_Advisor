"""Question Logger Utility - Reusable across routes"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

logger = logging.getLogger(__name__)


async def log_question(
    db: AsyncIOMotorDatabase,
    question: str,
    answer: str,
    processing_time: float,
    iterations: int,
    thread_id: Optional[str] = None,
    channel: Optional[str] = "api",
    success: bool = True,
    user_id: Optional[str] = None
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
            "user_id": ObjectId(user_id) if user_id and ObjectId.is_valid(user_id) else user_id,
            "logged_at": datetime.utcnow()
        }
        
        result = await collection.insert_one(log_doc)
        logger.info(f"📝 Question logged: {result.inserted_id}")
        return bool(result.inserted_id)
    except Exception as e:
        logger.error(f"❌ Error logging question: {str(e)}")
        return False


async def get_question_logs(
    db: AsyncIOMotorDatabase,
    limit: int = 100,
    success_only: bool = False,
    user_id: Optional[str] = None,
    channel: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get question logs from MongoDB"""
    try:
        collection = db["question_logs"]
        
        query = {}
        if success_only:
            query["success"] = True
        if user_id:
            query["user_id"] = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        if channel:
            query["channel"] = channel
        
        logs = []
        cursor = collection.find(query).sort("logged_at", -1).limit(limit)
        
        async for log in cursor:
            log["_id"] = str(log["_id"])
            if log.get("user_id"):
                log["user_id"] = str(log["user_id"])
            logs.append(log)
        
        logger.info(f"📋 Retrieved {len(logs)} question logs")
        return logs
    except Exception as e:
        logger.error(f"❌ Error getting logs: {str(e)}")
        return []


async def get_question_log_stats(
    db: AsyncIOMotorDatabase,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Get statistics on question logs"""
    try:
        collection = db["question_logs"]
        
        query = {}
        if user_id:
            query["user_id"] = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        
        total = await collection.count_documents(query)
        successful = await collection.count_documents({**query, "success": True})
        failed = await collection.count_documents({**query, "success": False})
        
        pipeline = [
            {"$match": query},
            {
                "$group": {
                    "_id": None,
                    "avg_time": {"$avg": "$processing_time"},
                    "avg_iterations": {"$avg": "$iterations"},
                    "max_time": {"$max": "$processing_time"},
                    "min_time": {"$min": "$processing_time"}
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
            "success_rate": round((successful / total * 100), 2) if total > 0 else 0,
            "avg_processing_time": round(avg_stats[0]["avg_time"], 2) if avg_stats else 0,
            "max_processing_time": round(avg_stats[0]["max_time"], 2) if avg_stats else 0,
            "min_processing_time": round(avg_stats[0]["min_time"], 2) if avg_stats else 0,
            "avg_iterations": round(avg_stats[0]["avg_iterations"], 2) if avg_stats else 0
        }
    except Exception as e:
        logger.error(f"❌ Error getting stats: {str(e)}")
        return {}


async def get_logs_by_channel(
    db: AsyncIOMotorDatabase,
    channel: str,
    limit: int = 100,
    user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get logs filtered by channel"""
    try:
        collection = db["question_logs"]
        
        query = {"channel": channel}
        if user_id:
            query["user_id"] = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        
        logs = []
        cursor = collection.find(query).sort("logged_at", -1).limit(limit)
        
        async for log in cursor:
            log["_id"] = str(log["_id"])
            if log.get("user_id"):
                log["user_id"] = str(log["user_id"])
            logs.append(log)
        
        return logs
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return []


async def clear_question_logs(
    db: AsyncIOMotorDatabase,
    user_id: Optional[str] = None
) -> bool:
    """Clear question logs"""
    try:
        collection = db["question_logs"]
        
        query = {}
        if user_id:
            query["user_id"] = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        
        result = await collection.delete_many(query)
        logger.warning(f"🗑️ Cleared {result.deleted_count} question logs")
        return True
    except Exception as e:
        logger.error(f"❌ Error clearing logs: {str(e)}")
        return False


async def export_question_logs(
    db: AsyncIOMotorDatabase,
    format: str = "json",
    user_id: Optional[str] = None
) -> Optional[str]:
    """Export question logs"""
    try:
        import json
        
        logs = await get_question_logs(db, limit=10000, user_id=user_id)
        
        if format == "json":
            return json.dumps(logs, indent=2, default=str)
        elif format == "csv":
            if not logs:
                return "question,answer,processing_time,iterations,thread_id,channel,success,logged_at"
            
            lines = ["question,answer,processing_time,iterations,thread_id,channel,success,logged_at"]
            for log in logs:
                question = log.get("question", "").replace(",", ";").replace("\n", " ")
                answer = log.get("answer", "")[:100].replace(",", ";").replace("\n", " ")
                processing_time = log.get("processing_time", 0)
                iterations = log.get("iterations", 0)
                thread_id = log.get("thread_id", "")
                channel = log.get("channel", "")
                success = log.get("success", False)
                logged_at = log.get("logged_at", "")
                
                lines.append(
                    f'"{question}","{answer}",{processing_time},{iterations},{thread_id},{channel},{success},{logged_at}'
                )
            
            return "\n".join(lines)
        
        return None
    except Exception as e:
        logger.error(f"❌ Error exporting logs: {str(e)}")
        return None


async def get_channel_stats(
    db: AsyncIOMotorDatabase,
    user_id: Optional[str] = None
) -> Dict[str, Any]:
    """Get statistics grouped by channel"""
    try:
        collection = db["question_logs"]
        
        match_query = {}
        if user_id:
            match_query["user_id"] = ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        
        pipeline = [
            {"$match": match_query},
            {
                "$group": {
                    "_id": "$channel",
                    "count": {"$sum": 1},
                    "successful": {
                        "$sum": {"$cond": ["$success", 1, 0]}
                    },
                    "avg_time": {"$avg": "$processing_time"}
                }
            },
            {"$sort": {"count": -1}}
        ]
        
        stats = {}
        async for doc in collection.aggregate(pipeline):
            stats[doc["_id"]] = {
                "total": doc["count"],
                "successful": doc["successful"],
                "failed": doc["count"] - doc["successful"],
                "success_rate": round((doc["successful"] / doc["count"] * 100), 2),
                "avg_processing_time": round(doc["avg_time"], 2)
            }
        
        return stats
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return {}