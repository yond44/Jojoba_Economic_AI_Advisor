"""User Data Manager - Reusable across routes"""
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId

logger = logging.getLogger(__name__)


# ============================================
# USER QUESTIONS
# ============================================

async def log_user_question(
    db: AsyncIOMotorDatabase,
    user_id: str,
    question: str,
    answer: str,
    processing_time: float,
    iterations: int,
    thread_id: Optional[str] = None,
    channel: Optional[str] = "api",
    success: bool = True
) -> bool:
    """Log question to user's data"""
    try:
        collection = db["user_questions"]
        
        log_doc = {
            "user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id,
            "question": question,
            "answer": answer,
            "processing_time": processing_time,
            "iterations": iterations,
            "thread_id": thread_id or "anonymous",
            "channel": channel,
            "success": success,
            "created_at": datetime.utcnow()
        }
        
        result = await collection.insert_one(log_doc)
        logger.info(f"📝 Question logged for user {user_id}: {result.inserted_id}")
        return bool(result.inserted_id)
    except Exception as e:
        logger.error(f"❌ Error logging question: {str(e)}")
        return False


async def get_user_questions(
    db: AsyncIOMotorDatabase,
    user_id: str,
    limit: int = 100,
    success_only: bool = False
) -> List[Dict[str, Any]]:
    """Get user's questions"""
    try:
        collection = db["user_questions"]
        
        query = {"user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id}
        if success_only:
            query["success"] = True
        
        questions = []
        cursor = collection.find(query).sort("created_at", -1).limit(limit)
        
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            doc["user_id"] = str(doc["user_id"])
            questions.append(doc)
        
        logger.info(f"📋 Retrieved {len(questions)} questions for user {user_id}")
        return questions
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return []


async def get_user_question_stats(
    db: AsyncIOMotorDatabase,
    user_id: str
) -> Dict[str, Any]:
    """Get user's question statistics"""
    try:
        collection = db["user_questions"]
        
        query = {"user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id}
        
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
        logger.error(f"❌ Error: {str(e)}")
        return {}


async def delete_user_questions(
    db: AsyncIOMotorDatabase,
    user_id: str
) -> bool:
    """Delete all user's questions"""
    try:
        collection = db["user_questions"]
        result = await collection.delete_many(
            {"user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id}
        )
        logger.warning(f"🗑️ Deleted {result.deleted_count} questions for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return False


# ============================================
# USER EMAILS
# ============================================

async def add_user_email(
    db: AsyncIOMotorDatabase,
    user_id: str,
    name: str,
    email: str
) -> Optional[Dict[str, Any]]:
    """Add email to user's list"""
    try:
        collection = db["user_emails"]
        
        existing = await collection.find_one({
            "user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id,
            "email": email.lower()
        })
        
        if existing:
            logger.warning(f"⚠️ Email already exists for user {user_id}")
            return None
        
        email_doc = {
            "user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id,
            "name": name,
            "email": email.lower(),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        result = await collection.insert_one(email_doc)
        email_doc["_id"] = str(result.inserted_id)
        email_doc["user_id"] = str(email_doc["user_id"])
        
        logger.info(f"➕ Email added for user {user_id}: {email}")
        return email_doc
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return None


async def get_user_emails(
    db: AsyncIOMotorDatabase,
    user_id: str
) -> List[Dict[str, Any]]:
    """Get user's email list"""
    try:
        collection = db["user_emails"]
        
        emails = []
        cursor = collection.find(
            {"user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id}
        ).sort("created_at", -1)
        
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            doc["user_id"] = str(doc["user_id"])
            emails.append(doc)
        
        logger.info(f"📧 Retrieved {len(emails)} emails for user {user_id}")
        return emails
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return []


async def delete_user_email(
    db: AsyncIOMotorDatabase,
    user_id: str,
    email_id: str
) -> bool:
    """Delete email from user's list"""
    try:
        collection = db["user_emails"]
        
        result = await collection.delete_one({
            "_id": ObjectId(email_id),
            "user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id
        })
        
        if result.deleted_count > 0:
            logger.info(f"🗑️ Email deleted for user {user_id}")
            return True
        
        logger.warning(f"⚠️ Email not found for user {user_id}")
        return False
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return False


async def get_user_email_string(
    db: AsyncIOMotorDatabase,
    user_id: str
) -> str:
    """Get user's emails as comma-separated string"""
    try:
        emails = await get_user_emails(db, user_id)
        email_list = [e.get("email") for e in emails if e.get("email")]
        return ", ".join(email_list)
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return ""


# ============================================
# USER QUEUE
# ============================================

async def add_user_question_to_queue(
    db: AsyncIOMotorDatabase,
    user_id: str,
    question: str
) -> bool:
    """Add question to user's queue"""
    try:
        collection = db["user_question_queue"]
        
        queue_doc = {
            "user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id,
            "question": question,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "processed_at": None
        }
        
        result = await collection.insert_one(queue_doc)
        logger.info(f"➕ Question added to queue for user {user_id}")
        return bool(result.inserted_id)
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return False


async def get_user_queue(
    db: AsyncIOMotorDatabase,
    user_id: str
) -> List[Dict[str, Any]]:
    """Get user's question queue"""
    try:
        collection = db["user_question_queue"]
        
        queue = []
        cursor = collection.find(
            {"user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id}
        ).sort("created_at", -1)
        
        async for doc in cursor:
            doc["_id"] = str(doc["_id"])
            doc["user_id"] = str(doc["user_id"])
            queue.append(doc)
        
        return queue
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return []


async def get_user_queue_count(
    db: AsyncIOMotorDatabase,
    user_id: str
) -> int:
    """Get user's pending queue count"""
    try:
        collection = db["user_question_queue"]
        
        return await collection.count_documents({
            "user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id,
            "status": "pending"
        })
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return 0


# ============================================
# USER PREFERENCES
# ============================================

async def set_user_preferences(
    db: AsyncIOMotorDatabase,
    user_id: str,
    preferences: Dict[str, Any]
) -> bool:
    """Set user preferences"""
    try:
        collection = db["user_preferences"]
        
        pref_doc = {
            "user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id,
            **preferences,
            "updated_at": datetime.utcnow()
        }
        
        result = await collection.update_one(
            {"user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id},
            {"$set": pref_doc},
            upsert=True
        )
        
        logger.info(f"⚙️ Preferences updated for user {user_id}")
        return True
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return False


async def get_user_preferences(
    db: AsyncIOMotorDatabase,
    user_id: str
) -> Dict[str, Any]:
    """Get user preferences"""
    try:
        collection = db["user_preferences"]
        
        doc = await collection.find_one(
            {"user_id": ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id}
        )
        
        if doc:
            doc["_id"] = str(doc["_id"])
            doc["user_id"] = str(doc["user_id"])
            return doc
        
        return {"user_id": user_id}
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return {}


# ============================================
# USER OVERVIEW
# ============================================

async def get_user_overview(
    db: AsyncIOMotorDatabase,
    user_id: str
) -> Dict[str, Any]:
    """Get complete user overview"""
    try:
        questions_stats = await get_user_question_stats(db, user_id)
        queue_count = await get_user_queue_count(db, user_id)
        emails = await get_user_emails(db, user_id)
        preferences = await get_user_preferences(db, user_id)
        
        return {
            "user_id": user_id,
            "questions": questions_stats,
            "queue": {
                "pending": queue_count
            },
            "emails": {
                "total": len(emails),
                "list": emails
            },
            "preferences": preferences,
            "last_updated": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"❌ Error: {str(e)}")
        return {}