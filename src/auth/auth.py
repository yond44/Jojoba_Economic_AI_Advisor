from fastapi import HTTPException, Security, Depends, status
from fastapi.security import APIKeyHeader, HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials
from datetime import datetime, timedelta
from typing import Optional, Dict
import logging
import jwt

from src.config.database import get_db
from src.config.settings import (
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    API_KEY
)
from src.db.user_db import (
    get_user_by_username,
    update_last_login,
    increment_login_attempts,
    is_account_locked,
    log_login,
    get_user_by_id
)
from src.models.user import UserInDB
from src.utils.security import verify_password

logger = logging.getLogger(__name__)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
http_bearer = HTTPBearer(auto_error=False)

JWT_EXPIRE_HOURS = 24
JWT_EXPIRE_SECONDS = JWT_EXPIRE_HOURS * 3600


# ============================================
# JWT TOKEN FUNCTIONS
# ============================================

def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None
) -> str:
    """Create JWT access token (default: 24 hours)"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(hours=JWT_EXPIRE_HOURS)
    
    to_encode.update({"exp": expire})
    
    try:
        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt
    except Exception as e:
        logger.error(f"Error creating token: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create access token"
        )


def verify_token(token: str) -> Dict:
    """Verify and decode JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        user_id: str = payload.get("user_id")
        
        if not username or not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )


# ============================================
# USER AUTHENTICATION
# ============================================

async def authenticate_user(
    username: str,
    password: str,
    db
) -> Optional[UserInDB]:
    """Authenticate user with username and password"""
    user = await get_user_by_username(db, username)
    
    if not user:
        logger.warning(f"❌ Login attempt with non-existent user: {username}")
        return None
    
    if not verify_password(password, user.hashed_password):
        logger.warning(f"❌ Wrong password for user: {username}")
        await increment_login_attempts(db, user.id)
        return None
    
    if user.disabled:
        logger.warning(f"❌ Login attempt for disabled user: {username}")
        return None
    
    locked = await is_account_locked(db, user.id)
    if locked:
        logger.warning(f"❌ Account locked: {username}")
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail="Account is locked. Try again later."
        )
    
    logger.info(f"✅ User authenticated: {username}")
    return user


async def get_current_user(
    token: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer),
    db = Depends(get_db)
) -> UserInDB:
    """Get current user from JWT token"""
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"}
        )
    
    payload = verify_token(token.credentials)
    user_id = payload.get("user_id")
    
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
    user = await get_user_by_id(db, user_id)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found"
        )
    
    if user.disabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled"
        )
    
    return user


# ============================================
# API KEY VALIDATION
# ============================================

async def validate_api_key(api_key: str = Security(api_key_header)) -> bool:
    """Validate API key from X-API-Key header"""
    if not api_key:
        logger.warning("❌ Missing API key in request")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing API Key. Provide X-API-Key header."
        )
    
    if api_key != API_KEY:
        logger.warning(f"❌ Invalid API key attempt: {api_key[:10]}...")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key"
        )
    
    return True


async def validate_credentials(
    api_key: Optional[str] = Security(api_key_header),
    token: Optional[HTTPAuthorizationCredentials] = Depends(http_bearer)
) -> Dict:
    """Validate either API key OR JWT token"""
    if api_key:
        try:
            await validate_api_key(api_key)
            return {"type": "api_key", "authenticated": True}
        except HTTPException:
            pass
    
    if token:
        try:
            payload = verify_token(token.credentials)
            user_id = payload.get("user_id")
            if user_id:
                return {"type": "bearer", "user_id": user_id, "authenticated": True}
        except HTTPException:
            pass
    
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing or invalid credentials",
        headers={"WWW-Authenticate": "Bearer"}
    )


# ============================================
# N8N TOKEN VALIDATION (For webhook endpoints)
# ============================================

async def validate_n8n_token(
    token: Optional[str] = Depends(APIKeyHeader(name="X-Webhook-Token", auto_error=False))
) -> Dict:
    """
    Validate n8n webhook token.
    This token is generated by /api/v1/auth/n8n-token endpoint.
    It uses the same JWT verification but with specific purpose check.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Webhook-Token header"
        )
    
    try:
        payload = verify_token(token)
        
        purpose = payload.get("purpose")
        if purpose and purpose != "n8n-webhook":
            logger.warning(f"Token used for wrong purpose: {purpose}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Token not intended for n8n webhook"
            )
        
        return payload
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"N8N token validation error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired n8n token"
        )