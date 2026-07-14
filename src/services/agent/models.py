"""Pydantic request/response models + conversation context."""
import re
import uuid
from typing import Dict, Any, Optional, List
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from src.services.agent.util import _utcnow


class ChannelType(str, Enum):
    API = "api"
    WEB = "web"
    MOBILE = "mobile"
    EMAIL = "email"
    BATCH = "batch"
    GRAPH = "graph"
    WEBHOOK = "webhook"
    BATCH_EMAIL = "batch_email"

class QueryRequest(BaseModel):
    """Request model for user queries"""
    question: str = Field(..., min_length=1, max_length=2000, description="User's question")
    thread_id: Optional[str] = Field(None, description="Conversation thread identifier")
    channel: Optional[ChannelType] = Field(ChannelType.API, description="Source channel")
    user_id: Optional[str] = Field(None, description="Optional user identifier")
    username: Optional[str] = Field(None, description="Optional username")
    language: Optional[str] = Field(default="en", description="Language (en/id)")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional context")

    @field_validator('question')
    @classmethod
    def question_not_empty(cls, v):
        if not v.strip():
            raise ValueError('Question cannot be empty or whitespace')
        return v.strip()

    @field_validator('thread_id', mode='before')
    @classmethod
    def set_thread_id(cls, v):
        return v or str(uuid.uuid4())

    @field_validator('language')
    @classmethod
    def validate_language(cls, v):
        if v not in ["en", "id"]:
            raise ValueError('Language must be "en" or "id"')
        return v

class QueryResponse(BaseModel):
    """Response model for queries"""
    question: str = Field(..., description="Original question")
    answer: str = Field(..., description="Generated answer")
    processing_time: float = Field(..., description="Time taken to process in seconds")
    thread_id: str = Field(..., description="Conversation thread identifier")
    language_detected: str = Field(default="en", description="Detected language")
    response_type: str = Field(default="answer", description="Type of response")
    success: bool = Field(default=True, description="Whether processing succeeded")
    validated: bool = Field(default=True, description="Whether query was validated")
    greeting: bool = Field(default=False, description="Whether this was a greeting")
    gratitude: bool = Field(default=False, description="Whether this was gratitude")
    sources: Optional[List[Dict[str, Any]]] = Field(None, description="Referenced sources")
    recommendations: Optional[List[str]] = Field(None, description="Follow-up recommendations")
    queue_info: Optional[Dict[str, Any]] = Field(None, description="Queue information")
    error: Optional[str] = Field(None, description="Error message if applicable")
    user_id: Optional[str] = Field(None, description="User identifier")
    attempts: int = Field(default=1, description="Number of processing attempts")
    timestamp: str = Field(default_factory=lambda: _utcnow().isoformat())

class BatchEmailRequest(BaseModel):
    """Request model for batch email processing"""
    question: str = Field(..., min_length=1, max_length=2000, description="Question to analyze")
    emails: List[str] = Field(..., min_length=1, max_length=100, description="Email addresses")
    phone: Optional[str] = Field(None, description="Contact phone number")
    subject: Optional[str] = Field(None, description="Email subject line")
    include_pdf: Optional[bool] = Field(False, description="Include PDF report")
    frequency: Optional[str] = Field("once", description="Delivery frequency")
    language: Optional[str] = Field(default="en", description="Language preference")

    @field_validator('emails')
    @classmethod
    def validate_emails(cls, v):
        """Validate email format"""
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        for email in v:
            if not re.match(email_pattern, email):
                raise ValueError(f'Invalid email format: {email}')
        return list(set(v))

class ConversationContext(BaseModel):
    """Track conversation context for intelligent recommendations"""
    thread_id: str
    user_id: Optional[str] = None
    username: Optional[str] = None
    questions_history: List[str] = Field(default_factory=list)
    topics_discussed: List[str] = Field(default_factory=list)
    user_level: str = Field(default="beginner")
    language: str = Field(default="en")
    channel: ChannelType = Field(default=ChannelType.API)
    created_at: str = Field(default_factory=lambda: _utcnow().isoformat())
    last_interaction: str = Field(default_factory=lambda: _utcnow().isoformat())
    interaction_count: int = Field(default=0)
