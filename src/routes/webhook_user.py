"""
Per-user n8n webhook — the endpoint the deployed workflow calls on a schedule.
==============================================================================

WHY A SEPARATE ENDPOINT (not the existing /api/webhook/process-next)
-------------------------------------------------------------------
The existing process-next is global + unauthenticated (single-tenant briefing).
The n8n integration is multi-tenant: each user's workflow must act as THAT user
and touch only THAT user's data. So this endpoint:

  1. authenticates via X-Webhook-Token (a per-user JWT with purpose=n8n-webhook,
     minted by n8n_manager when the workflow is deployed) -> gives us user_id.
     This is what makes the token "only usable through this project": it's
     signed with OUR SECRET_KEY and scoped to one purpose + one user.
  2. picks that user's next queued question (or generates one),
  3. runs the agent for them,
  4. emails THEIR saved recipient list from the backend (so the user's n8n needs
     no SMTP credential — the free-tier/no-VPS win),
  5. logs to their history.

Mounted at /api/webhook/user/process-next (see main.py). The deployed workflow
template points here with the user's token.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from src.auth.auth import validate_n8n_token
from src.config.database import get_db
from src.services.agent import ask_agent
from src.services.email_sender import send_batch_emails
from src.utils.markdown_email import markdown_to_email_html
from src.utils.user_data_manager import get_user_email_string, get_user_queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhook/user", tags=["webhook-user"])


async def process_next_for_user(
    db, user_id: str, language: str = "en", send_email: bool = False,
) -> dict:
    """Per-user process-next core — reused by BOTH webhook routes:

      * POST /api/webhook/user/process-next        (this router)
      * POST /api/webhook/process-next             (legacy URL, when it receives
                                                    an X-Webhook-Token header)

    Answers the user's next queued question and returns THEIR isolated
    recipient list; only sends from the backend when send_email=True.
    """
    start = time.time()

    queue = await get_user_queue(db, user_id)
    pending = [q for q in queue if q.get("status") == "pending"]
    question = pending[0]["question"] if pending else "What are today's key economic trends?"

    result = await ask_agent(
        question=question, thread_id=f"n8n:{user_id}", db=db,
        user_id=user_id, language=language, channel="webhook",
    )
    answer = result.get("answer", "")
    answer_html = markdown_to_email_html(answer)

    email_string = await get_user_email_string(db, user_id)
    recipients = [e.strip() for e in email_string.split(",") if e.strip()]
    email_result = {"sent_count": 0, "recipients": recipients}
    if send_email and recipients:
        email_result = await send_batch_emails(
            to_emails=recipients,
            subject=f"Jojoba Economic News — {question[:60]}",
            body=answer,
        )

    if pending:
        from bson import ObjectId
        try:
            await db["user_question_queue"].update_one(
                {"_id": ObjectId(pending[0]["_id"])},
                {"$set": {"status": "processed", "processed_at": datetime.utcnow()}},
            )
        except Exception as exc:
            logger.warning("Could not mark queue item processed: %s", exc)

    return {
        "status": "ok",
        "question": question,
        "response": answer,
        "response_html": answer_html,
        "email_string": email_string,
        "email_count": len(recipients),
        "recipients": recipients,
        "sent_count": email_result.get("sent_count", 0),
        "processing_time": round(time.time() - start, 2),
        "iterations": result.get("attempts", 1),
        "queue_remaining": max(0, len(pending) - 1),
        "next_question": pending[1]["question"] if len(pending) > 1 else None,
    }


@router.post("/process-next")
async def user_process_next(
    payload: dict = Depends(validate_n8n_token),
    language: str = Query("en"),
    send_email: bool = Query(False),
    db=Depends(get_db),
):
    """Triggered by a user's n8n schedule. Answers a question and emails them."""
    return await process_next_for_user(
        db, payload.get("user_id"), language=language, send_email=send_email
    )