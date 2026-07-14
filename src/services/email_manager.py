import logging
from datetime import datetime
from typing import Optional, List, Dict
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)


# ============================================
# CRUD OPERATIONS
# ============================================

async def get_all_emails(db: AsyncIOMotorDatabase) -> List[Dict]:
    """Get all emails"""
    try:
        collection = db["emails"]
        emails = await collection.find({}).to_list(None)
        
        for email in emails:
            email["_id"] = str(email["_id"])
        
        logger.info(f"Retrieved {len(emails)} emails")
        return emails
    except Exception as e:
        logger.error(f"Error getting all emails: {str(e)}")
        return []


async def get_email_by_id(db: AsyncIOMotorDatabase, email_id: str) -> Optional[Dict]:
    """Get email by ID"""
    try:
        from bson import ObjectId
        
        collection = db["emails"]
        email = await collection.find_one({"_id": ObjectId(email_id)})
        
        if email:
            email["_id"] = str(email["_id"])
            logger.info(f"Retrieved email: {email_id}")
            return email
        
        logger.warning(f"Email not found: {email_id}")
        return None
    except Exception as e:
        logger.error(f"Error getting email {email_id}: {str(e)}")
        return None


async def add_email(
    db: AsyncIOMotorDatabase,
    name: str,
    email: str
) -> Optional[Dict]:
    """Add new email"""
    try:
        collection = db["emails"]
        
        existing = await collection.find_one({"email": email.lower()})
        if existing:
            logger.warning(f"Email already exists: {email}")
            return None
        
        new_email = {
            "name": name,
            "email": email.lower(),
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        result = await collection.insert_one(new_email)
        new_email["_id"] = str(result.inserted_id)
        
        logger.info(f"Email added: {result.inserted_id}")
        return new_email
    except Exception as e:
        logger.error(f"Error adding email: {str(e)}")
        return None


async def update_email(
    db: AsyncIOMotorDatabase,
    email_id: str,
    name: Optional[str] = None,
    email: Optional[str] = None
) -> Optional[Dict]:
    """Update email"""
    try:
        from bson import ObjectId
        
        collection = db["emails"]
        
        update_dict = {"updated_at": datetime.utcnow()}
        
        if name:
            update_dict["name"] = name
        if email:
            existing = await collection.find_one({
                "_id": {"$ne": ObjectId(email_id)},
                "email": email.lower()
            })
            if existing:
                logger.warning(f"Email already exists: {email}")
                return None
            
            update_dict["email"] = email.lower()
        
        updated = await collection.find_one_and_update(
            {"_id": ObjectId(email_id)},
            {"$set": update_dict},
            return_document=True
        )
        
        if updated:
            updated["_id"] = str(updated["_id"])
            logger.info(f"Email updated: {email_id}")
            return updated
        
        logger.warning(f"Email not found for update: {email_id}")
        return None
    except Exception as e:
        logger.error(f"Error updating email: {str(e)}")
        return None


async def delete_email(db: AsyncIOMotorDatabase, email_id: str) -> bool:
    try:
        from bson import ObjectId
        
        collection = db["emails"]
        result = await collection.delete_one({"_id": ObjectId(email_id)})
        
        if result.deleted_count > 0:
            logger.info(f"Email deleted: {email_id}")
            return True
        
        logger.warning(f"Email not found for deletion: {email_id}")
        return False
    except Exception as e:
        logger.error(f"Error deleting email: {str(e)}")
        return False


# ============================================
# UTILITY FUNCTIONS
# ============================================

async def get_email_string(db: AsyncIOMotorDatabase) -> str:
    """Get all emails as comma-separated string"""
    try:
        emails = await get_all_emails(db)
        email_list = [e.get("email") for e in emails if e.get("email")]
        return ", ".join(email_list)
    except Exception as e:
        logger.error(f"Error getting email string: {str(e)}")
        return ""


async def get_email_count(db: AsyncIOMotorDatabase) -> int:
    """Get total email count"""
    try:
        collection = db["emails"]
        count = await collection.count_documents({})
        return count
    except Exception as e:
        logger.error(f"Error getting email count: {str(e)}")
        return 0


async def reset_email_file(db: AsyncIOMotorDatabase) -> bool:
    """Reset (delete all) emails"""
    try:
        collection = db["emails"]
        result = await collection.delete_many({})
        logger.info(f"Reset emails - deleted {result.deleted_count} documents")
        return True
    except Exception as e:
        logger.error(f"Error resetting emails: {str(e)}")
        return False


async def initialize_email_file(
    db: AsyncIOMotorDatabase,
    initial_emails: Optional[List[Dict]] = None
) -> bool:
    """Initialize emails with default list"""
    try:
        if initial_emails is None:
            initial_emails = []
        
        collection = db["emails"]
        
        await collection.delete_many({})
        
        for email in initial_emails:
            email_doc = {
                "name": email.get("name"),
                "email": email.get("email", "").lower(),
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            await collection.insert_one(email_doc)
        
        logger.info(f"Emails initialized with {len(initial_emails)} contacts")
        return True
    except Exception as e:
        logger.error(f"Error initializing emails: {str(e)}")
        return False


async def search_emails(
    db: AsyncIOMotorDatabase,
    query: str
) -> List[Dict]:
    """Search emails by name or email address"""
    try:
        collection = db["emails"]
        query_lower = query.lower()
        
        emails = await collection.find({
            "$or": [
                {"name": {"$regex": query_lower, "$options": "i"}},
                {"email": {"$regex": query_lower, "$options": "i"}}
            ]
        }).to_list(None)
        
        for email in emails:
            email["_id"] = str(email["_id"])
        
        logger.info(f"Search found {len(emails)} emails for: {query}")
        return emails
    except Exception as e:
        logger.error(f"Error searching emails: {str(e)}")
        return []


async def export_emails(
    db: AsyncIOMotorDatabase,
    format: str = "json"
) -> Optional[str]:
    """Export emails in specified format"""
    try:
        import json
        
        emails = await get_all_emails(db)
        
        if format == "json":
            return json.dumps(emails, indent=2, default=str)
        elif format == "csv":
            if not emails:
                return "name,email"
            
            lines = ["name,email"]
            for email in emails:
                name = email.get("name", "").replace(",", ";")
                email_addr = email.get("email", "")
                lines.append(f"{name},{email_addr}")
            
            return "\n".join(lines)
        
        logger.warning(f"Unsupported format: {format}")
        return None
    except Exception as e:
        logger.error(f"Error exporting emails: {str(e)}")
        return None


async def get_email_stats(db: AsyncIOMotorDatabase) -> Dict:
    """Get email statistics"""
    try:
        total = await get_email_count(db)
        email_string = await get_email_string(db)
        
        return {
            "total_emails": total,
            "email_string": email_string,
            "sample": email_string[:100] if email_string else ""
        }
    except Exception as e:
        logger.error(f"Error getting stats: {str(e)}")
        return {"total_emails": 0, "email_string": "", "sample": ""}