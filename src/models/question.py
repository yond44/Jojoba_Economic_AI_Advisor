"""Question Models"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class QuestionBase(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    source: Optional[str] = Field(default="api", description="Source of the question")
    status: Optional[str] = Field(default="pending", description="pending, processing, completed, archived")


class QuestionCreate(QuestionBase):
    pass


class QuestionResponse(QuestionBase):
    id: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    processed_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class QuestionListResponse(BaseModel):
    status: str = "success"
    count: int
    questions: list[QuestionResponse]


class QuestionSingleResponse(BaseModel):
    status: str = "success"
    question: QuestionResponse


class QuestionStatsResponse(BaseModel):
    status: str = "success"
    stats: dict


class QuestionGenerateResponse(BaseModel):
    status: str = "success"
    question: str
    source: Optional[str] = None


class SuccessMessageResponse(BaseModel):
    status: str = "success"
    message: str