"""
Chat session manager — all DB logic for ChatGPT-style conversations.
====================================================================

Every function takes user_id and scopes to it via ownership.scope_filter, so
there is no code path that touches another user's chats. The route layer stays
thin; this module owns the data rules.

Operations:
  create_chat            — new conversation (optionally titled from 1st message)
  list_chats             — sidebar list, newest first, paginated
  get_chat                — one conversation + its messages (ownership-checked)
  append_turn             — save one full exchange (question + answer) as a
                             single chat_messages document; bumps counters
  update_turn_answer      — fill in the answer on a turn saved question-first
                             (streaming route), same document, no new row
  rename_chat             — set a title
  delete_chat             — remove conversation AND its messages (cascade)
  clear_chats             — nuke all of a user's chats

Auto-title: if no title is given, we derive one from the first user message
(first ~6 words), like the other assistants do.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.utils.ownership import assert_owner, as_object_id, scope_filter

logger = logging.getLogger(__name__)

SESSIONS = "chat_sessions"
MESSAGES = "chat_messages"


def _now() -> datetime:
    return datetime.utcnow()


def _derive_title(text: str) -> str:
    words = text.strip().split()
    title = " ".join(words[:6])
    if len(words) > 6:
        title += "…"
    return title or "New chat"


def _clean(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    out["id"] = str(out.pop("_id"))
    out.pop("user_id", None)
    if "session_id" in out:
        out["session_id"] = str(out["session_id"])
    return out


async def ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Idempotent — safe to call at startup alongside create_indexes()."""
    await db[SESSIONS].create_index([("user_id", 1), ("updated_at", -1)])
    await db[MESSAGES].create_index([("session_id", 1), ("created_at", 1)])
    await db[MESSAGES].create_index([("user_id", 1)])


async def create_chat(
    db: AsyncIOMotorDatabase,
    user_id: str,
    title: Optional[str] = None,
    first_message: Optional[str] = None,
) -> Dict[str, Any]:
    now = _now()
    if not title:
        title = _derive_title(first_message) if first_message else "New chat"
    doc = {
        "user_id": as_object_id(user_id),
        "title": title,
        "message_count": 0,
        "last_message_preview": "",
        "created_at": now,
        "updated_at": now,
    }
    res = await db[SESSIONS].insert_one(doc)
    doc["_id"] = res.inserted_id
    logger.info("💬 Chat created %s for user %s", res.inserted_id, user_id)
    return _clean(doc)


async def list_chats(
    db: AsyncIOMotorDatabase,
    user_id: str,
    skip: int = 0,
    limit: int = 50,
) -> Tuple[List[Dict[str, Any]], int]:
    col = db[SESSIONS]
    f = scope_filter(user_id)
    total = await col.count_documents(f)
    cursor = col.find(f).sort("updated_at", -1).skip(skip).limit(limit)
    chats = [_clean(d) async for d in cursor]
    return chats, total


async def _get_session_raw(
    db: AsyncIOMotorDatabase, user_id: str, chat_id: str
) -> Dict[str, Any]:
    if not ObjectId.is_valid(chat_id):
        assert_owner(None, user_id)
    doc = await db[SESSIONS].find_one({"_id": ObjectId(chat_id)})
    return assert_owner(doc, user_id)


async def get_chat(
    db: AsyncIOMotorDatabase, user_id: str, chat_id: str
) -> Dict[str, Any]:
    """Return the session plus its messages.

    Each row in `chat_messages` is one full turn — a single document holding
    both the question and its answer, not two separate rows. This expands
    each turn into a (user, assistant) pair on the way out, so the API
    response shape callers already expect doesn't change.
    """
    session = await _get_session_raw(db, user_id, chat_id)
    cursor = db[MESSAGES].find({"session_id": ObjectId(chat_id)}).sort("created_at", 1)
    messages: List[Dict[str, Any]] = []
    async for doc in cursor:
        turn = _clean(doc)
        messages.append({
            "id": f"{turn['id']}_q",
            "role": "user",
            "content": turn.get("question", ""),
            "sources": [],
            "groundedness": None,
            "created_at": turn["created_at"],
        })
        if turn.get("answer"):
            messages.append({
                "id": f"{turn['id']}_a",
                "role": "assistant",
                "content": turn.get("answer", ""),
                "sources": turn.get("sources", []),
                "groundedness": turn.get("groundedness"),
                "created_at": turn.get("updated_at", turn["created_at"]),
            })
    out = _clean(session)
    out["messages"] = messages
    return out


async def append_turn(
    db: AsyncIOMotorDatabase,
    user_id: str,
    chat_id: str,
    question: str,
    answer: str = "",
    sources: Optional[List[Dict[str, Any]]] = None,
    groundedness: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Save one full exchange — question AND answer — as a single document.

    Pass `answer=""` if the answer isn't known yet (e.g. streaming, where the
    question is saved before the response is generated); fill it in later
    with update_turn_answer using the returned turn's "id".
    """
    await _get_session_raw(db, user_id, chat_id)
    now = _now()
    turn = {
        "session_id": ObjectId(chat_id),
        "user_id": as_object_id(user_id),
        "question": question,
        "answer": answer,
        "sources": sources or [],
        "groundedness": groundedness,
        "created_at": now,
        "updated_at": now,
    }
    res = await db[MESSAGES].insert_one(turn)
    turn["_id"] = res.inserted_id

    await db[SESSIONS].update_one(
        {"_id": ObjectId(chat_id)},
        {
            "$set": {
                "updated_at": now,
                "last_message_preview": (answer or question)[:120],
            },
            "$inc": {"message_count": 1},
        },
    )
    return _clean(turn)


async def update_turn_answer(
    db: AsyncIOMotorDatabase,
    user_id: str,
    chat_id: str,
    turn_id: str,
    answer: str,
    sources: Optional[List[Dict[str, Any]]] = None,
    groundedness: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fill in the answer on a turn whose question was saved up front
    (used by the streaming route once the full response is known)."""
    await _get_session_raw(db, user_id, chat_id)
    now = _now()
    await db[MESSAGES].update_one(
        {"_id": ObjectId(turn_id), "session_id": ObjectId(chat_id)},
        {
            "$set": {
                "answer": answer,
                "sources": sources or [],
                "groundedness": groundedness,
                "updated_at": now,
            }
        },
    )
    await db[SESSIONS].update_one(
        {"_id": ObjectId(chat_id)},
        {"$set": {"updated_at": now, "last_message_preview": answer[:120]}},
    )
    doc = await db[MESSAGES].find_one({"_id": ObjectId(turn_id)})
    return _clean(doc)


async def rename_chat(
    db: AsyncIOMotorDatabase, user_id: str, chat_id: str, title: str
) -> Dict[str, Any]:
    await _get_session_raw(db, user_id, chat_id)
    await db[SESSIONS].update_one(
        {"_id": ObjectId(chat_id)},
        {"$set": {"title": title, "updated_at": _now()}},
    )
    return await get_chat(db, user_id, chat_id)


async def delete_chat(
    db: AsyncIOMotorDatabase, user_id: str, chat_id: str
) -> bool:
    """Delete the session and cascade-delete its messages."""
    await _get_session_raw(db, user_id, chat_id)
    await db[MESSAGES].delete_many({"session_id": ObjectId(chat_id)})
    res = await db[SESSIONS].delete_one({"_id": ObjectId(chat_id)})
    logger.info("🗑️ Chat %s deleted for user %s", chat_id, user_id)
    return res.deleted_count > 0


async def clear_chats(db: AsyncIOMotorDatabase, user_id: str) -> int:
    f = scope_filter(user_id)
    await db[MESSAGES].delete_many(f)
    res = await db[SESSIONS].delete_many(f)
    logger.warning("🗑️ Cleared %d chats for user %s", res.deleted_count, user_id)
    return res.deleted_count


async def export_all_turns(
    db: AsyncIOMotorDatabase,
    user_id: str,
    skip: int = 0,
    limit: int = 200,
    include_pending: bool = False,
) -> Tuple[List[Dict[str, Any]], int]:
    """Return question/answer pairs across ALL of a user's chats, newest first.
 
    Set include_pending=True to also return turns whose answer hasn't been
    filled in yet (e.g. a stream still in progress).
    """
    f: Dict[str, Any] = {"user_id": as_object_id(user_id)}
    if not include_pending:
        f["answer"] = {"$ne": ""}
 
    col = db[MESSAGES]
    total = await col.count_documents(f)
    cursor = col.find(f).sort("created_at", -1).skip(skip).limit(limit)
 
    turns = []
    async for doc in cursor:
        turn = _clean(doc)
        turns.append({
            "chat_id": turn.pop("session_id"),
            "question": turn.get("question", ""),
            "answer": turn.get("answer", ""),
            "created_at": turn["created_at"],
        })
    return turns, total