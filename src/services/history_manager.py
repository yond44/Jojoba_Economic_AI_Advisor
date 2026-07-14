
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from bson import ObjectId

from src.models.history import (
    SentHistoryCreate,
    SentHistoryUpdate,
    SentHistoryResponse,
    DeliveryStatus,
    ChannelType
)

logger = logging.getLogger(__name__)


def convert_history_doc(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not doc:
        return None
    
    def _clean(value):
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, dict):
            return {k: _clean(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_clean(item) for item in value]
        return value
    
    return _clean(dict(doc))


def _build_user_filter(
    user_id: Optional[str],
    include_system: bool = True,
) -> Dict[str, Any]:
    """Build a user_id filter clause.
    
    - user_id=None → no filter (admin view)
    - user_id='x', include_system=True → match 'x' OR 'system' OR missing user_id
    - user_id='x', include_system=False → exact match on 'x'
    """
    if user_id is None:
        return {}
    
    if include_system:
        return {
            "$or": [
                {"user_id": user_id},
                {"user_id": "system"},
                {"user_id": {"$exists": False}},
                {"user_id": None},
            ]
        }
    
    return {"user_id": user_id}


async def create_history_entry(
    db,
    history_data: SentHistoryCreate,
    user_id: Optional[str] = None,
    username: Optional[str] = None
) -> Optional[str]:
    try:
        collection = db["sent_history"]
        
        if hasattr(history_data, "model_dump"):
            history_doc = history_data.model_dump()
        else:
            history_doc = history_data.dict()
        
        now = datetime.utcnow()
        history_doc["created_at"] = now
        history_doc["sent_at"] = now
        history_doc["updated_at"] = now
        
        if user_id:
            history_doc["user_id"] = user_id
        if username:
            history_doc["username"] = username
        
        if "status" not in history_doc or history_doc["status"] is None:
            history_doc["status"] = DeliveryStatus.SENT.value
        elif hasattr(history_doc["status"], "value"):
            history_doc["status"] = history_doc["status"].value
        
        if hasattr(history_doc.get("channel"), "value"):
            history_doc["channel"] = history_doc["channel"].value
        
        if history_doc.get("recipients"):
            history_doc["recipient_count"] = len(history_doc["recipients"])
        
        if "metadata" not in history_doc or not history_doc["metadata"]:
            history_doc["metadata"] = {}
        
        result = await collection.insert_one(history_doc)
        logger.info(f"📝 History entry created: {result.inserted_id} (user={user_id})")
        return str(result.inserted_id)
        
    except Exception as e:
        logger.error(f"Error creating history entry: {str(e)}", exc_info=True)
        return None


async def get_history_entries(
    db,
    limit: int = 50,
    skip: int = 0,
    status: Optional[str] = None,
    channel: Optional[str] = None,
    user_id: Optional[str] = None,
    include_system: bool = True,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> List[Dict[str, Any]]:
    try:
        collection = db["sent_history"]
        
        filter_query: Dict[str, Any] = {}
        
        if status:
            filter_query["status"] = status
        if channel:
            filter_query["channel"] = channel
        
        user_clause = _build_user_filter(user_id, include_system)
        filter_query.update(user_clause)
        
        if start_date or end_date:
            date_filter: Dict[str, Any] = {}
            if start_date:
                date_filter["$gte"] = start_date
            if end_date:
                date_filter["$lte"] = end_date
            filter_query["sent_at"] = date_filter
        
        cursor = collection.find(filter_query).sort("sent_at", -1).skip(skip).limit(limit)
        
        histories = []
        async for doc in cursor:
            cleaned = convert_history_doc(doc)
            if cleaned:
                histories.append(cleaned)
        
        return histories
        
    except Exception as e:
        logger.error(f"Error getting history entries: {str(e)}", exc_info=True)
        return []


async def count_history_entries(
    db,
    status: Optional[str] = None,
    channel: Optional[str] = None,
    user_id: Optional[str] = None,
    include_system: bool = True,
) -> int:
    try:
        collection = db["sent_history"]
        
        filter_query: Dict[str, Any] = {}
        if status:
            filter_query["status"] = status
        if channel:
            filter_query["channel"] = channel
        
        user_clause = _build_user_filter(user_id, include_system)
        filter_query.update(user_clause)
        
        return await collection.count_documents(filter_query)
    except Exception as e:
        logger.error(f"Error counting history entries: {str(e)}")
        return 0


async def get_history_entry(db, history_id: str) -> Optional[Dict[str, Any]]:
    """Get a single history entry by ID"""
    try:
        collection = db["sent_history"]
        
        if not ObjectId.is_valid(history_id):
            return None
        
        doc = await collection.find_one({"_id": ObjectId(history_id)})
        return convert_history_doc(doc) if doc else None
        
    except Exception as e:
        logger.error(f"Error getting history entry: {str(e)}")
        return None


async def update_history_entry(
    db,
    history_id: str,
    update_data: SentHistoryUpdate
) -> bool:
    """Update a history entry"""
    try:
        collection = db["sent_history"]
        
        if not ObjectId.is_valid(history_id):
            return False
        
        if hasattr(update_data, "model_dump"):
            update_dict = update_data.model_dump(exclude_unset=True)
        else:
            update_dict = update_data.dict(exclude_unset=True)
        
        if "status" in update_dict and hasattr(update_dict["status"], "value"):
            update_dict["status"] = update_dict["status"].value
        
        update_dict["updated_at"] = datetime.utcnow()
        
        new_status = update_dict.get("status")
        if new_status == DeliveryStatus.DELIVERED.value:
            update_dict["delivered_at"] = datetime.utcnow()
        elif new_status == DeliveryStatus.OPENED.value:
            update_dict["opened_at"] = datetime.utcnow()
        elif new_status == DeliveryStatus.CLICKED.value:
            update_dict["clicked_at"] = datetime.utcnow()
        
        result = await collection.update_one(
            {"_id": ObjectId(history_id)},
            {"$set": update_dict}
        )
        
        return result.modified_count > 0
        
    except Exception as e:
        logger.error(f"Error updating history entry: {str(e)}")
        return False


async def get_history_stats(
    db,
    days: int = 7,
    user_id: Optional[str] = None,
    include_system: bool = True,
) -> Dict[str, Any]:
    """Get statistics for sent history"""
    try:
        collection = db["sent_history"]
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        filter_query: Dict[str, Any] = {
            "sent_at": {"$gte": start_date, "$lte": end_date}
        }
        filter_query.update(_build_user_filter(user_id, include_system))
        
        pipeline = [
            {"$match": filter_query},
            {"$group": {"_id": "$status", "count": {"$sum": 1}}}
        ]
        status_counts: Dict[str, int] = {}
        async for doc in collection.aggregate(pipeline):
            key = doc.get("_id") or "unknown"
            status_counts[key] = doc.get("count", 0)
        
        pipeline = [
            {"$match": filter_query},
            {"$group": {"_id": "$channel", "count": {"$sum": 1}}}
        ]
        channel_counts: Dict[str, int] = {}
        async for doc in collection.aggregate(pipeline):
            key = doc.get("_id") or "unknown"
            channel_counts[key] = doc.get("count", 0)
        
        daily_counts: Dict[str, int] = {}
        for i in range(days):
            day = start_date + timedelta(days=i)
            next_day = day + timedelta(days=1)
            
            day_filter = {"sent_at": {"$gte": day, "$lt": next_day}}
            day_filter.update(_build_user_filter(user_id, include_system))
            
            count = await collection.count_documents(day_filter)
            daily_counts[day.strftime("%Y-%m-%d")] = count
        
        total = await collection.count_documents(filter_query)
        
        return {
            "total_sent": total,
            "delivered": status_counts.get(DeliveryStatus.DELIVERED.value, 0),
            "failed": status_counts.get(DeliveryStatus.FAILED.value, 0),
            "bounced": status_counts.get(DeliveryStatus.BOUNCED.value, 0),
            "opened": status_counts.get(DeliveryStatus.OPENED.value, 0),
            "clicked": status_counts.get(DeliveryStatus.CLICKED.value, 0),
            "by_channel": channel_counts,
            "by_status": status_counts,
            "last_7_days": daily_counts
        }
        
    except Exception as e:
        logger.error(f"Error getting history stats: {str(e)}", exc_info=True)
        return {
            "total_sent": 0, "delivered": 0, "failed": 0, "bounced": 0,
            "opened": 0, "clicked": 0,
            "by_channel": {}, "by_status": {}, "last_7_days": {},
        }


async def delete_history_entry(db, history_id: str) -> bool:
    try:
        collection = db["sent_history"]
        if not ObjectId.is_valid(history_id):
            return False
        result = await collection.delete_one({"_id": ObjectId(history_id)})
        return result.deleted_count > 0
    except Exception as e:
        logger.error(f"Error deleting history entry: {str(e)}")
        return False


async def clear_history(db, user_id: Optional[str] = None) -> int:
    try:
        collection = db["sent_history"]
        filter_query: Dict[str, Any] = {}
        if user_id is not None:
            filter_query["user_id"] = user_id
        result = await collection.delete_many(filter_query)
        logger.warning(f"🗑️ Cleared {result.deleted_count} history entries")
        return result.deleted_count
    except Exception as e:
        logger.error(f"Error clearing history: {str(e)}")
        return 0