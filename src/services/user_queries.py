"""User Query Logging and Analytics"""
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import logging

logger = logging.getLogger(__name__)


async def log_user_query(
    db: AsyncIOMotorDatabase,
    user_id: str,
    question: str,
    answer: str,
    processing_time: float,
    attempts: int,
    thread_id: Optional[str] = None,
    channel: str = "api",
    success: bool = True,
    validated: bool = True,
    sources_count: int = 0,
    error: Optional[str] = None,
    response_type: str = "answer",
    language_detected: str = "en"
) -> Dict:
    """Log a user query with detailed metadata"""
    collection = db["user_queries"]
    
    query_record = {
        "user_id": ObjectId(user_id),
        "question": question,
        "answer": answer,
        "processing_time": processing_time,
        "attempts": attempts,
        "thread_id": thread_id,
        "channel": channel,
        "success": success,
        "validated": validated,
        "sources_count": sources_count,
        "error": error,
        "response_type": response_type,
        "language_detected": language_detected,
        "created_at": datetime.utcnow(),
        "timestamp": datetime.utcnow()
    }
    
    result = await collection.insert_one(query_record)
    
    logger.info(f"✅ Query logged for user {user_id}")
    
    return {
        "_id": str(result.inserted_id),
        **query_record
    }


async def get_user_queries(
    db: AsyncIOMotorDatabase,
    user_id: str,
    skip: int = 0,
    limit: int = 10,
    days: Optional[int] = None,
    response_type: Optional[str] = None
) -> Tuple[List[Dict], int]:
    """Get user's query history"""
    collection = db["user_queries"]
    
    query = {"user_id": ObjectId(user_id)}
    
    if days:
        since = datetime.utcnow() - timedelta(days=days)
        query["created_at"] = {"$gte": since}
    
    if response_type:
        query["response_type"] = response_type
    
    total = await collection.count_documents(query)
    
    cursor = collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
    
    queries = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        doc["user_id"] = str(doc["user_id"])
        queries.append(doc)
    
    return queries, total


async def get_user_query_stats(
    db: AsyncIOMotorDatabase,
    user_id: str,
    days: int = 30
) -> Dict:
    """Get user's query statistics"""
    collection = db["user_queries"]
    
    since = datetime.utcnow() - timedelta(days=days)
    
    query = {
        "user_id": ObjectId(user_id),
        "created_at": {"$gte": since}
    }
    
    pipeline = [
        {"$match": query},
        {
            "$group": {
                "_id": "$user_id",
                "total_queries": {"$sum": 1},
                "successful_queries": {
                    "$sum": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}
                },
                "validated_queries": {
                    "$sum": {"$cond": [{"$eq": ["$validated", True]}, 1, 0]}
                },
                "avg_processing_time": {"$avg": "$processing_time"},
                "total_processing_time": {"$sum": "$processing_time"},
                "avg_attempts": {"$avg": "$attempts"},
                "total_sources": {"$sum": "$sources_count"},
                "errors": {
                    "$sum": {"$cond": [{"$ne": ["$error", None]}, 1, 0]}
                }
            }
        }
    ]
    
    result = list(await collection.aggregate(pipeline).to_list(None))
    
    if result:
        stats = result[0]
        stats.pop("_id", None)
        return stats
    
    return {
        "total_queries": 0,
        "successful_queries": 0,
        "validated_queries": 0,
        "avg_processing_time": 0,
        "total_processing_time": 0,
        "avg_attempts": 0,
        "total_sources": 0,
        "errors": 0
    }


async def delete_user_query(
    db: AsyncIOMotorDatabase,
    query_id: str,
    user_id: str
) -> bool:
    """Delete a user query (permission check)"""
    collection = db["user_queries"]
    
    result = await collection.delete_one({
        "_id": ObjectId(query_id),
        "user_id": ObjectId(user_id)
    })
    
    if result.deleted_count > 0:
        logger.info(f"✅ Query deleted: {query_id}")
        return True
    
    return False


async def get_user_query_by_id(
    db: AsyncIOMotorDatabase,
    query_id: str,
    user_id: str
) -> Optional[Dict]:
    """Get a specific query"""
    collection = db["user_queries"]
    
    doc = await collection.find_one({
        "_id": ObjectId(query_id),
        "user_id": ObjectId(user_id)
    })
    
    if doc:
        doc["_id"] = str(doc["_id"])
        doc["user_id"] = str(doc["user_id"])
        return doc
    
    return None


async def get_top_questions(
    db: AsyncIOMotorDatabase,
    limit: int = 10,
    days: int = 30
) -> List[Dict]:
    """Get most asked questions across all users"""
    collection = db["user_queries"]
    
    since = datetime.utcnow() - timedelta(days=days)
    
    pipeline = [
        {
            "$match": {
                "created_at": {"$gte": since}
            }
        },
        {
            "$group": {
                "_id": "$question",
                "count": {"$sum": 1},
                "avg_time": {"$avg": "$processing_time"},
                "success_rate": {
                    "$avg": {"$cond": [{"$eq": ["$success", True]}, 1, 0]}
                }
            }
        },
        {"$sort": {"count": -1}},
        {"$limit": limit}
    ]
    
    results = await collection.aggregate(pipeline).to_list(None)
    
    return [
        {
            "question": doc["_id"],
            "count": doc["count"],
            "avg_processing_time": round(doc["avg_time"], 2),
            "success_rate": round(doc["success_rate"] * 100, 2)
        }
        for doc in results
    ]


async def export_user_queries(
    db: AsyncIOMotorDatabase,
    user_id: str,
    format: str = "json",
    days: Optional[int] = None
):
    """Export user queries as a list of dicts (json) or a CSV string."""
    queries, _ = await get_user_queries(
        db=db,
        user_id=user_id,
        skip=0,
        limit=10000,
        days=days
    )

    if format == "csv":
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["created_at", "question", "answer", "success", "processing_time", "channel"])
        for q in queries:
            writer.writerow([
                q.get("created_at", ""),
                q.get("question", ""),
                q.get("answer", ""),
                q.get("success", ""),
                q.get("processing_time", ""),
                q.get("channel", ""),
            ])
        return output.getvalue()

    return queries


async def search_user_queries(
    db: AsyncIOMotorDatabase,
    user_id: str,
    search_term: str,
    skip: int = 0,
    limit: int = 10
) -> Tuple[List[Dict], int]:
    """Search user's query history by question or answer"""
    collection = db["user_queries"]
    
    query = {
        "user_id": ObjectId(user_id),
        "$or": [
            {"question": {"$regex": search_term, "$options": "i"}},
            {"answer": {"$regex": search_term, "$options": "i"}}
        ]
    }
    
    total = await collection.count_documents(query)
    
    cursor = collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
    
    queries = []
    async for doc in cursor:
        doc["_id"] = str(doc["_id"])
        doc["user_id"] = str(doc["user_id"])
        queries.append(doc)
    
    logger.info(f"✅ Search found {total} results for '{search_term}'")
    
    return queries, total