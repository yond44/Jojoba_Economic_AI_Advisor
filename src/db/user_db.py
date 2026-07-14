from motor.motor_asyncio import AsyncIOMotorDatabase
from bson import ObjectId
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import logging

from src.models.user import UserCreate, UserUpdate, UserInDB, UserRole
from src.utils.security import hash_password, verify_password

logger = logging.getLogger(__name__)


# ============================================
# CREATE USER
# ============================================

async def create_user(
    db: AsyncIOMotorDatabase,
    user_data: UserCreate
) -> UserInDB:
    """Create a new user"""
    collection = db["users"]
    
    existing = await collection.find_one({
        "$or": [
            {"email": user_data.email.lower()},
            {"username": user_data.username.lower()}
        ]
    })
    
    if existing:
        if existing.get("email") == user_data.email.lower():
            raise ValueError("Email already registered")
        else:
            raise ValueError("Username already taken")
    
    user_dict = {
        "username": user_data.username.lower(),
        "email": user_data.email.lower(),
        "full_name": user_data.full_name,
        "role": user_data.role,
        "disabled": user_data.disabled,
        "hashed_password": hash_password(user_data.password),
        "created_at": datetime.utcnow(),
        "updated_at": datetime.utcnow(),
        "last_login": None,
        "login_attempts": 0,
        "is_locked": False,
        "locked_until": None
    }
    
    result = await collection.insert_one(user_dict)
    created_user = await collection.find_one({"_id": result.inserted_id})
    
    logger.info(f"✅ User created: {user_data.username}")
    
    created_user["_id"] = str(created_user["_id"])
    return UserInDB(**created_user)


# ============================================
# READ USER
# ============================================

async def get_user_by_id(
    db: AsyncIOMotorDatabase,
    user_id: str
) -> Optional[UserInDB]:
    """Get user by ID"""
    try:
        collection = db["users"]
        user = await collection.find_one({"_id": ObjectId(user_id)})
        
        if user:
            user["_id"] = str(user["_id"])
            return UserInDB(**user)
        return None
    except Exception as e:
        logger.error(f"Error getting user by id: {str(e)}")
        return None


async def get_user_by_username(
    db: AsyncIOMotorDatabase,
    username: str
) -> Optional[UserInDB]:
    """Get user by username"""
    collection = db["users"]
    user = await collection.find_one({"username": username.lower()})
    
    if user:
        user["_id"] = str(user["_id"])
        return UserInDB(**user)
    return None


async def get_user_by_email(
    db: AsyncIOMotorDatabase,
    email: str
) -> Optional[UserInDB]:
    """Get user by email"""
    collection = db["users"]
    user = await collection.find_one({"email": email.lower()})
    
    if user:
        user["_id"] = str(user["_id"])
        return UserInDB(**user)
    return None


async def get_all_users(
    db: AsyncIOMotorDatabase,
    skip: int = 0,
    limit: int = 10,
    role: Optional[UserRole] = None
) -> Tuple[List[UserInDB], int]:
    """Get all users with pagination"""
    collection = db["users"]
    
    query = {"disabled": False}
    if role:
        query["role"] = role
    
    total = await collection.count_documents(query)
    users_cursor = collection.find(query).skip(skip).limit(limit)
    users = []
    
    async for user in users_cursor:
        user["_id"] = str(user["_id"])
        users.append(UserInDB(**user))
    
    return users, total


# ============================================
# UPDATE USER
# ============================================

async def update_user(
    db: AsyncIOMotorDatabase,
    user_id: str,
    update_data: UserUpdate
) -> Optional[UserInDB]:
    """Update user"""
    try:
        collection = db["users"]
        
        update_dict = {}
        if update_data.email:
            update_dict["email"] = update_data.email.lower()
        if update_data.full_name:
            update_dict["full_name"] = update_data.full_name
        if update_data.disabled is not None:
            update_dict["disabled"] = update_data.disabled
        if update_data.role:
            update_dict["role"] = update_data.role
        if update_data.password:
            update_dict["hashed_password"] = hash_password(update_data.password)
        
        update_dict["updated_at"] = datetime.utcnow()
        
        result = await collection.find_one_and_update(
            {"_id": ObjectId(user_id)},
            {"$set": update_dict},
            return_document=True
        )
        
        if result:
            logger.info(f"✅ User updated: {user_id}")
            result["_id"] = str(result["_id"])
            return UserInDB(**result)
        return None
    except Exception as e:
        logger.error(f"Error updating user: {str(e)}")
        return None


async def delete_user(
    db: AsyncIOMotorDatabase,
    user_id: str
) -> bool:
    """Delete user (soft delete)"""
    collection = db["users"]
    
    result = await collection.find_one_and_update(
        {"_id": ObjectId(user_id)},
        {"$set": {"disabled": True, "updated_at": datetime.utcnow()}},
        return_document=True
    )
    
    if result:
        logger.info(f"✅ User deleted (soft): {user_id}")
        return True
    return False


# ============================================
# AUTHENTICATION
# ============================================

async def verify_user_password(
    db: AsyncIOMotorDatabase,
    user_id: str,
    password: str
) -> bool:
    """Verify user password"""
    user = await get_user_by_id(db, user_id)
    if not user:
        return False
    return verify_password(password, user.hashed_password)


async def update_last_login(
    db: AsyncIOMotorDatabase,
    user_id: str
) -> bool:
    """Update user's last login"""
    collection = db["users"]
    
    result = await collection.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "last_login": datetime.utcnow(),
                "login_attempts": 0,
                "is_locked": False
            }
        }
    )
    return result.modified_count > 0


# ============================================
# ACCOUNT LOCKING
# ============================================

async def increment_login_attempts(
    db: AsyncIOMotorDatabase,
    user_id: str,
    max_attempts: int = 5
) -> bool:
    """Increment failed login attempts"""
    collection = db["users"]
    user = await get_user_by_id(db, user_id)
    
    if not user:
        return False
    
    attempts = user.login_attempts + 1
    
    if attempts >= max_attempts:
        await collection.update_one(
            {"_id": ObjectId(user_id)},
            {
                "$set": {
                    "login_attempts": attempts,
                    "is_locked": True,
                    "locked_until": datetime.utcnow() + timedelta(minutes=15)
                }
            }
        )
        logger.warning(f"⚠️ Account locked: {user_id}")
    else:
        await collection.update_one(
            {"_id": ObjectId(user_id)},
            {"$set": {"login_attempts": attempts}}
        )
    
    return True


async def reset_login_attempts(
    db: AsyncIOMotorDatabase,
    user_id: str
) -> bool:
    """Reset login attempts"""
    collection = db["users"]
    
    result = await collection.update_one(
        {"_id": ObjectId(user_id)},
        {
            "$set": {
                "login_attempts": 0,
                "is_locked": False,
                "locked_until": None
            }
        }
    )
    return result.modified_count > 0


async def is_account_locked(
    db: AsyncIOMotorDatabase,
    user_id: str
) -> bool:
    """Check if account is locked"""
    user = await get_user_by_id(db, user_id)
    
    if not user or not user.is_locked:
        return False
    
    if user.locked_until and user.locked_until < datetime.utcnow():
        await reset_login_attempts(db, user_id)
        return False
    
    return True


# ============================================
# LOGIN HISTORY
# ============================================

async def log_login(
    db: AsyncIOMotorDatabase,
    user_id: str,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    success: bool = True
):
    """Log user login"""
    collection = db["login_history"]
    
    login_record = {
        "user_id": ObjectId(user_id),
        "login_at": datetime.utcnow(),
        "ip_address": ip_address,
        "user_agent": user_agent,
        "success": success
    }
    await collection.insert_one(login_record)


async def get_login_history(
    db: AsyncIOMotorDatabase,
    user_id: str,
    limit: int = 10
) -> List[Dict]:
    """Get user login history"""
    collection = db["login_history"]
    
    history = []
    cursor = collection.find(
        {"user_id": ObjectId(user_id)}
    ).sort("login_at", -1).limit(limit)
    
    async for record in cursor:
        record["user_id"] = str(record["user_id"])
        record["_id"] = str(record["_id"])
        history.append(record)
    
    return history