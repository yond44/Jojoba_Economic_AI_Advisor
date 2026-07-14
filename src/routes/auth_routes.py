
from fastapi import APIRouter, Depends, HTTPException, status, Request
from datetime import timedelta
import logging
import os
import secrets

from src.config.database import get_db
from src.models.user import (
    LoginRequest,
    LoginResponse,
    UserCreate,
    UserResponse,
    UserInDB
)

from src.auth.auth import authenticate_user as db_authenticate_user
from src.db.user_db import (
    create_user,
    get_user_by_id,
    update_last_login,
    log_login,
    get_login_history
)
from src.auth.auth import (
    create_access_token,
    get_current_user,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

N8N_WEBHOOK_TOKEN = os.getenv("N8N_WEBHOOK_TOKEN", secrets.token_urlsafe(32))


@router.post("/register", response_model=UserResponse)
async def register(user_data: UserCreate, db = Depends(get_db)):
    """Register a new user"""
    try:
        user = await create_user(db, user_data)
        logger.info(f"✅ New user registered: {user.username}")
        
        return UserResponse(
            _id=user.id,
            username=user.username,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            disabled=user.disabled,
            created_at=user.created_at,
            updated_at=user.updated_at,
            last_login=user.last_login
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Registration failed"
        )


@router.post("/login", response_model=LoginResponse)
async def login(
    credentials: LoginRequest,
    request: Request,
    db = Depends(get_db)
):
    """Login - returns JWT token and n8n webhook token"""
    try:
        user = await db_authenticate_user(
            credentials.username,
            credentials.password,
            db
        )
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password"
            )
        
        await update_last_login(db, user.id)
        await log_login(
            db,
            user.id,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            success=True
        )
        
        access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = create_access_token(
            data={
                "sub": user.username,
                "user_id": user.id
            },
            expires_delta=access_token_expires
        )
        
        n8n_token = access_token
        
        logger.info(f"✅ User logged in: {user.username}")
        
        return LoginResponse(
            access_token=access_token,
            token_type="bearer",
            expires_in=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            n8n_token=n8n_token,
            user=UserResponse(
                _id=user.id,
                username=user.username,
                email=user.email,
                full_name=user.full_name,
                role=user.role,
                disabled=user.disabled,
                created_at=user.created_at,
                updated_at=user.updated_at,
                last_login=user.last_login
            )
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed"
        )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: UserInDB = Depends(get_current_user)):
    """Get current user info"""
    return UserResponse(
        _id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        full_name=current_user.full_name,
        role=current_user.role,
        disabled=current_user.disabled,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
        last_login=current_user.last_login
    )


@router.get("/login-history")
async def get_user_login_history(
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db),
    limit: int = 10
):
    """Get user login history"""
    history = await get_login_history(db, current_user.id, limit)
    return {"history": history}


@router.post("/logout")
async def logout(
    current_user: UserInDB = Depends(get_current_user),
    db = Depends(get_db)
):
    """Logout endpoint"""
    logger.info(f"✅ User logged out: {current_user.username}")
    return {"message": "Successfully logged out"}


@router.get("/n8n-token")
async def get_n8n_token(
    current_user: UserInDB = Depends(get_current_user)
):
    """Get n8n webhook token for the current user"""
    n8n_token = create_access_token(
        data={
            "sub": current_user.username,
            "user_id": current_user.id,
            "purpose": "n8n-webhook"
        },
        expires_delta=timedelta(days=30)
    )
    
    return {
        "token": n8n_token,
        "expires_in": 30 * 24 * 60 * 60
    }