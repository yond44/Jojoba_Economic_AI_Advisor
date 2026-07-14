"""
Chat session models — the ChatGPT/Claude-style conversation store.
==================================================================

A "chat" here is exactly what it is in ChatGPT: a titled thread that holds an
ordered list of (user question, assistant answer) turns. Two collections:

  chat_sessions  — one document per conversation (title, counts, timestamps)
  chat_messages  — one document per turn, linked by session_id

Both carry user_id so every read/write is isolated per user (see ownership.py).
Splitting messages into their own collection (instead of an array inside the
session) keeps session listing fast and lets a long chat grow without rewriting
a huge document on every turn.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


class ChatCreate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    first_message: Optional[str] = Field(default=None, max_length=2000)


class ChatRename(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class SendMessage(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    language: Optional[str] = Field(default=None)


class MessageResponse(BaseModel):
    id: str
    role: MessageRole
    content: str
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    groundedness: Optional[Dict[str, Any]] = None
    created_at: datetime


class ChatSummary(BaseModel):
    id: str
    title: str
    message_count: int
    last_message_preview: str = ""
    created_at: datetime
    updated_at: datetime


class ChatDetail(ChatSummary):
    messages: List[MessageResponse] = Field(default_factory=list)
