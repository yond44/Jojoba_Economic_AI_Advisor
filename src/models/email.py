from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional
from datetime import datetime


class EmailBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr


class EmailCreate(EmailBase):
    pass


class EmailUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None


class EmailResponse(EmailBase):
    id: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class EmailListResponse(BaseModel):
    status: str = "success"
    count: int
    emails: list[EmailResponse]


class EmailSingleResponse(BaseModel):
    status: str = "success"
    email: EmailResponse


class EmailStringResponse(BaseModel):
    status: str = "success"
    email_string: str
    count: int


class ErrorResponse(BaseModel):
    status: str = "error"
    message: str


class SuccessMessageResponse(BaseModel):
    status: str = "success"
    message: str