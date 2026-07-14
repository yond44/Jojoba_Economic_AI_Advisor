from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
from pydantic import ConfigDict 


class DeliveryStatus(str, Enum):
    """Delivery status enum"""
    PENDING = "pending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"
    BOUNCED = "bounced"
    OPENED = "opened"
    CLICKED = "clicked"


class ChannelType(str, Enum):
    """Channel type enum"""
    EMAIL = "email"
    WEBHOOK = "webhook"
    API = "api"
    BATCH = "batch"
    N8N = "n8n"

class SentHistoryBase(BaseModel):
    """Base sent history model"""
    question: str = Field(..., min_length=1, max_length=2000)
    answer: str = Field(..., min_length=1)
    channel: ChannelType
    status: DeliveryStatus = Field(default=DeliveryStatus.SENT)
    
    processing_time: Optional[float] = None
    iterations: Optional[int] = 0
    response_type: Optional[str] = "answer"
    language: Optional[str] = "en"
    
    recipients: Optional[List[str]] = Field(default_factory=list)
    recipient_count: Optional[int] = 0
    
    sources: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    
    thread_id: Optional[str] = None
    
    user_id: Optional[str] = None
    username: Optional[str] = None
    
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)
    
    
class SentHistoryCreate(SentHistoryBase):
    """Create a new sent history entry"""
    pass


class SentHistoryUpdate(BaseModel):
    """Update sent history entry"""
    status: Optional[DeliveryStatus] = None
    opened_at: Optional[datetime] = None
    clicked_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    failed_reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SentHistoryResponse(SentHistoryBase):
    """Sent history response model"""
    id: str = Field(..., alias="_id")
    created_at: datetime
    updated_at: Optional[datetime] = None
    sent_at: datetime
    delivered_at: Optional[datetime] = None
    opened_at: Optional[datetime] = None
    clicked_at: Optional[datetime] = None
    failed_reason: Optional[str] = None
    
    class SentHistoryResponse(SentHistoryBase):
        model_config = ConfigDict(from_attributes=True, populate_by_name=True)

class SentHistoryListResponse(BaseModel):
    """Sent history list response"""
    status: str = "success"
    count: int
    total: int
    histories: List[SentHistoryResponse]


class SentHistoryStats(BaseModel):
    """Sent history statistics"""
    total_sent: int
    delivered: int
    failed: int
    bounced: int
    opened: int
    clicked: int
    by_channel: Dict[str, int]
    by_status: Dict[str, int]
    last_7_days: Dict[str, int]