"""
Data-isolation helpers — one place that enforces "this row belongs to this user".
================================================================================

WHY
---
"Isolate all data for every user" is not one feature, it's an invariant that
must hold on EVERY read and write. Scattering `{"user_id": ObjectId(uid)}`
filters across 20 route handlers means one forgotten filter = a data leak.

These helpers centralize the two operations that matter:
  - scope_filter(user_id): the Mongo clause every user-owned query must include.
  - assert_owner(doc, user_id): raises 404 (not 403 — don't reveal existence)
    if a fetched document isn't owned by the caller.

Use them in every user-facing route. See chat_manager.py / n8n_manager.py for
the pattern in practice.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import HTTPException, status


def as_object_id(user_id: str) -> Any:
    """Coerce a user_id string to ObjectId when valid; else return as-is.

    The codebase stores user_id sometimes as ObjectId (user_queries) and
    sometimes as str (sent_history). This keeps callers from caring.
    """
    return ObjectId(user_id) if ObjectId.is_valid(user_id) else user_id


def scope_filter(user_id: str, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a Mongo filter scoped to one owner, merged with `extra`."""
    f: Dict[str, Any] = {"user_id": as_object_id(user_id)}
    if extra:
        f.update(extra)
    return f


def assert_owner(doc: Optional[Dict[str, Any]], user_id: str) -> Dict[str, Any]:
    """Return the doc if owned by user_id, else 404.

    We return 404 (not 403) on purpose: a 403 confirms the resource exists,
    which leaks information across tenants. To the caller, someone else's row
    simply "does not exist".
    """
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    owner = doc.get("user_id")
    owner_str = str(owner)
    if owner_str != str(user_id) and owner_str != str(as_object_id(user_id)):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return doc
