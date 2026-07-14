"""
Chat routes — the REST surface for ChatGPT-style conversations.
===============================================================

Endpoints (all require a JWT; all scoped to the authenticated user):

  POST   /api/v1/chats                 create a new chat            (New chat)
  GET    /api/v1/chats                 list my chats (sidebar)
  GET    /api/v1/chats/{id}            get one chat + messages
  PATCH  /api/v1/chats/{id}            rename a chat
  DELETE /api/v1/chats/{id}            delete a chat                (Delete chat)
  DELETE /api/v1/chats                 clear all my chats
  POST   /api/v1/chats/{id}/messages   send a message -> answer, both saved
  POST   /api/v1/chats/{id}/stream     send a message -> SSE token stream

The send-message flow saves the user turn, runs the agent (full guardrails +
multi-agent graph), saves the assistant turn (with sources + groundedness), and
returns both. The stream flow uses the modular RAG pipeline for token streaming.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from src.auth.auth import get_current_user
from src.config.database import get_db
from src.models.chat import (
    ChatCreate,
    ChatRename,
    SendMessage,
)
from src.models.user import UserInDB
from src.services import chat_manager as cm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chats", tags=["chats"])


@router.post("")
async def create_chat(
    body: ChatCreate,
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    return await cm.create_chat(
        db, str(current_user.id), title=body.title, first_message=body.first_message
    )


@router.get("")
async def list_chats(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    chats, total = await cm.list_chats(db, str(current_user.id), skip=skip, limit=limit)
    return {"chats": chats, "total": total, "skip": skip, "limit": limit}


@router.get("/{chat_id}")
async def get_chat(
    chat_id: str,
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    return await cm.get_chat(db, str(current_user.id), chat_id)


@router.patch("/{chat_id}")
async def rename_chat(
    chat_id: str,
    body: ChatRename,
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    return await cm.rename_chat(db, str(current_user.id), chat_id, body.title)


@router.delete("/{chat_id}")
async def delete_chat(
    chat_id: str,
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    await cm.delete_chat(db, str(current_user.id), chat_id)
    return {"success": True, "deleted": chat_id}


@router.delete("")
async def clear_chats(
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    n = await cm.clear_chats(db, str(current_user.id))
    return {"success": True, "cleared": n}


@router.post("/{chat_id}/messages")
async def send_message(
    chat_id: str,
    body: SendMessage,
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    """Send a user message; return the saved user + assistant turns."""
    from src.services.agent import ask_agent

    user_id = str(current_user.id)

    result = await ask_agent(
        question=body.content,
        thread_id=chat_id,
        db=db,
        user_id=user_id,
        username=current_user.username,
        language=body.language,
        channel="web",
    )

    turn = await cm.append_turn(
        db, user_id, chat_id,
        body.content,
        result.get("answer", ""),
        sources=result.get("sources", []),
        groundedness=result.get("groundedness"),
    )

    user_msg = {
        "id": f"{turn['id']}_q",
        "role": "user",
        "content": turn["question"],
        "sources": [],
        "groundedness": None,
        "created_at": turn["created_at"],
    }
    assistant_msg = {
        "id": f"{turn['id']}_a",
        "role": "assistant",
        "content": turn["answer"],
        "sources": turn.get("sources", []),
        "groundedness": turn.get("groundedness"),
        "created_at": turn.get("updated_at", turn["created_at"]),
    }

    return {
        "chat_id": chat_id,
        "user_message": user_msg,
        "assistant_message": assistant_msg,
        "meta": {
            "processing_time": result.get("processing_time"),
            "response_type": result.get("response_type"),
            "success": result.get("success"),
        },
    }


@router.post("/{chat_id}/stream")
async def stream_message(
    chat_id: str,
    body: SendMessage,
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    """Send a message and stream the answer token-by-token as SSE.

    The question is saved up front as one chat_messages document (answer
    left blank), and the same document is filled in with the answer once
    the stream completes — never a second row for the same exchange.
    """
    from src.services.rag import answer_stream

    user_id = str(current_user.id)
    turn = await cm.append_turn(db, user_id, chat_id, body.content, "")
    turn_id = turn["id"]

    language = body.language or "en"
    collected: list[str] = []

    async def event_source():
        async for event in answer_stream(
            body.content, language=language, bucket_key=user_id
        ):
            if '"text"' in event:
                collected.append(event)
            yield event
        try:
            joined = "".join(
                __import__("json").loads(line[len("data: "):]).get("text", "")
                for chunk in collected
                for line in chunk.splitlines()
                if line.startswith("data: ")
            )
            await cm.update_turn_answer(db, user_id, chat_id, turn_id, joined)
        except Exception as exc:
            logger.warning("stream persistence failed: %s", exc)

    return StreamingResponse(event_source(), media_type="text/event-stream")

@router.get("/export/qa")
async def export_all_qa(
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
    include_pending: bool = Query(False),
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    """Return every question/answer pair across all of the user's chats.
 
    Lightweight export — no sources or groundedness, just question, answer,
    and which chat each turn belongs to. Paginated, newest first.
    """
    user_id = str(current_user.id)
    turns, total = await cm.export_all_turns(
        db, user_id, skip=skip, limit=limit, include_pending=include_pending
    )
 
    return {
        "user_id": user_id,
        "total": total,
        "skip": skip,
        "limit": limit,
        "turns": [
            {
                "chat_id": t["chat_id"],
                "question": t["question"],
                "answer": t["answer"],
            }
            for t in turns
        ],
    }