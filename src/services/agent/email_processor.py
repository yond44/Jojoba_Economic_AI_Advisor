"""Batch email processor — renders the newspaper edition and sends it."""
import logging
import time
import asyncio
import uuid
from typing import Dict, Any, Optional, List
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.services.agent.util import _utcnow
from src.services.agent.models import BatchEmailRequest
from src.services.agent.email_render import (
    _esc, _md_inline, _apply_drop_cap, _render_article_html,
)
from src.services.question_manager import (
    get_next_question, remove_first_question, get_all_questions, get_question_count,
)
from src.services.agent.runtime import ask_agent

logger = logging.getLogger(__name__)


def _default_db():
    """Live handle to the agent's default Mongo db (set at init)."""
    from src.services.agent import runtime
    return runtime._mongo_db


class BatchEmailProcessor:
    """Process batch email requests"""

    def __init__(self):
        pass

    async def process_batch(
        self,
        request: BatchEmailRequest,
        db: Optional[AsyncIOMotorDatabase] = None,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process batch email request: ask agent, send via SMTP, log history.

        Note on user attribution: the original read
        getattr(self, "_current_user_id", None) — attributes that were
        never set anywhere in the codebase, so history rows always had
        user_id=None while LOOKING like attribution was implemented.
        Hidden state on a shared singleton is also a race condition
        waiting to happen. Explicit parameters, with the getattr kept
        only as a backward-compatible fallback.
        """
        from src.services.email_sender import send_batch_emails
        from src.services.history_manager import create_history_entry as create_history
        from src.models.history import SentHistoryCreate, ChannelType as HistoryChannel, DeliveryStatus

        batch_id = str(uuid.uuid4())
        thread_id = str(uuid.uuid4())

        effective_db = db if db is not None else _default_db()

        response = await ask_agent(
            question=request.question,
            thread_id=thread_id,
            db=effective_db,
            language=request.language,
        )

        answer = response.get("answer", "")

        email_content = self._prepare_email_content(
            request.question,
            response,
            request.subject,
        )

        plain_text_fallback = (
            f"Question: {request.question}\n\n"
            f"{answer}\n\n"
            f"-- The Jojoba Economic Review"
        )

        subject = request.subject or f"Economic Analysis: {request.question[:60]}"

        send_result = await send_batch_emails(
            to_emails=request.emails,
            subject=subject,
            body=plain_text_fallback,
            html_body=email_content,
        )

        sent_count = send_result.get("sent_count", 0)
        failed_emails = send_result.get("failed_emails", [])
        simulated = send_result.get("simulated", False)
        smtp_error = send_result.get("error")

        if simulated:
            overall_status = "simulated"
            delivery_status = DeliveryStatus.PENDING
        elif sent_count > 0 and not failed_emails:
            overall_status = "sent"
            delivery_status = DeliveryStatus.SENT
        elif sent_count > 0 and failed_emails:
            overall_status = "partial"
            delivery_status = DeliveryStatus.SENT
        else:
            overall_status = "failed"
            delivery_status = DeliveryStatus.FAILED

        logger.info(f"📧 Batch {batch_id}: {overall_status} - sent {sent_count}/{len(request.emails)}")

        try:
            history_payload = SentHistoryCreate(
                question=request.question,
                answer=answer or "(no answer generated)",
                channel=HistoryChannel.BATCH,
                status=delivery_status,
                processing_time=response.get("processing_time", 0),
                iterations=response.get("attempts", 1),
                response_type=response.get("response_type", "answer"),
                language=request.language or "en",
                recipients=request.emails,
                recipient_count=len(request.emails),
                sources=response.get("sources", []),
                thread_id=thread_id,
                metadata={
                    "batch_id": batch_id,
                    "subject": subject,
                    "frequency": request.frequency,
                    "include_pdf": request.include_pdf,
                    "sent_count": sent_count,
                    "failed_emails": failed_emails,
                    "simulated": simulated,
                    "smtp_error": smtp_error,
                },
            )

            history_id = await create_history(
                db=effective_db,
                history_data=history_payload,
                user_id=user_id or getattr(self, "_current_user_id", None),
                username=username or getattr(self, "_current_username", None),
            )
            logger.info(f"📝 History logged: {history_id}")
        except Exception as e:
            logger.warning(f"⚠️ Failed to log batch history: {str(e)}")
            history_id = None

        return {
            "batch_id": batch_id,
            "history_id": history_id,
            "thread_id": thread_id,
            "status": overall_status,
            "email_count": len(request.emails),
            "sent_count": sent_count,
            "failed_count": len(failed_emails),
            "failed_emails": failed_emails,
            "emails": request.emails,
            "question": request.question,
            "response_preview": answer[:500] if answer else "",
            "frequency": request.frequency,
            "include_pdf": request.include_pdf,
            "created_at": _utcnow().isoformat(),
            "simulated": simulated,
            "error": smtp_error,
        }

    def _prepare_email_content(self, question: str, response: Dict[str, Any], subject: Optional[str] = None) -> str:
        """Prepare email content in newspaper-style HTML format (email-client safe)."""

        answer = response.get("answer", "No analysis available at the time of publication.")
        processing_time = response.get("processing_time", 0)
        response_type = response.get("response_type", "answer")
        recommendations = response.get("recommendations") or []
        sources = response.get("sources") or []
        language = response.get("language_detected", "en")

        now = _utcnow()
        date_long = now.strftime("%A, %d %B %Y")
        time_short = now.strftime("%H:%M")

        article_body = _render_article_html(answer)

        recs_html = ""
        if recommendations:
            rec_lines = "<br/>".join([f"&bull; {_esc(rec)}" for rec in recommendations[:5]])
            recs_html = f"""
  <tr>
    <td style="padding:0 32px 24px 32px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f5f1e3" style="background-color:#f5f1e3;border-left:4px solid #8b6914;">
        <tr>
          <td style="padding:14px 18px;">
            <div style="font-family:Georgia,serif;font-size:10px;text-transform:uppercase;letter-spacing:2px;color:#8b6914;font-weight:700;margin-bottom:8px;">
              &#128204; Further Reading &middot; Suggested Questions
            </div>
            <div style="font-family:Georgia,serif;font-size:14px;font-style:italic;color:#4a4233;line-height:1.7;">
              {rec_lines}
            </div>
          </td>
        </tr>
      </table>
    </td>
  </tr>"""

        sources_count = len(sources)
        sources_label = f"{sources_count} source{'s' if sources_count != 1 else ''} consulted" if sources_count else "Synthesized analysis"

        headline_text = _esc(question.strip().rstrip("?.!") if question else "Market Analysis")

        language_safe = _esc(language)
        response_type_safe = _esc(response_type)

        html_doc = f"""<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0 Transitional//EN" "http://www.w3.org/TR/xhtml1/DTD/xhtml1-transitional.dtd">
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>The Jojoba Economic Review</title>
</head>
<body style="margin:0;padding:0;background-color:#e8e4d8;font-family:Georgia,'Times New Roman',Times,serif;color:#1a1a1a;">

<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#e8e4d8" style="background-color:#e8e4d8;">
<tr><td align="center" style="padding:24px 12px;">

<table role="presentation" width="640" cellpadding="0" cellspacing="0" border="0" bgcolor="#fdfcf7" style="max-width:640px;width:100%;background-color:#fdfcf7;border:1px solid #c8c2b0;">

  <tr>
    <td style="padding:18px 32px 0 32px;border-bottom:1px solid #d4cdb5;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td align="left" style="font-family:Georgia,serif;font-size:10px;text-transform:uppercase;letter-spacing:2px;color:#6b5d3f;font-weight:700;padding-bottom:10px;">Vol. I &mdash; Reader Edition</td>
          <td align="center" style="font-family:Georgia,serif;font-size:10px;text-transform:uppercase;letter-spacing:1px;color:#6b5d3f;font-style:italic;padding-bottom:10px;">Est. MMXXVI</td>
          <td align="right" style="font-family:Georgia,serif;font-size:10px;text-transform:uppercase;letter-spacing:2px;color:#6b5d3f;font-weight:700;padding-bottom:10px;">On-Demand</td>
        </tr>
      </table>
    </td>
  </tr>

  <tr>
    <td align="center" style="padding:18px 32px 6px 32px;background-color:#fdfcf7;">
      <div style="font-family:Georgia,'Times New Roman',serif;font-size:42px;font-weight:900;letter-spacing:-1px;line-height:1;color:#0d0d0d;">
        The Jojoba <span style="color:#8b6914;font-style:italic;">Economic</span> Review
      </div>
    </td>
  </tr>

  <tr>
    <td align="center" style="padding:0 32px 18px 32px;border-bottom:3px solid #1a1a1a;">
      <div style="font-family:Georgia,serif;font-style:italic;font-size:13px;color:#5a4f3a;letter-spacing:0.5px;">
        &mdash; Intelligence for the Discerning Investor &mdash;
      </div>
    </td>
  </tr>

  <tr>
    <td style="padding:2px 32px 0 32px;border-bottom:1px solid #1a1a1a;font-size:0;line-height:0;">&nbsp;</td>
  </tr>

  <tr>
    <td bgcolor="#1a1a1a" style="background-color:#1a1a1a;padding:10px 32px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr>
          <td align="left" style="font-family:Georgia,serif;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#fdfcf7;">{date_long}</td>
          <td align="center" style="font-family:Georgia,serif;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#d4a542;font-weight:700;">&#9733; AI Edition &#9733;</td>
          <td align="right" style="font-family:Georgia,serif;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#fdfcf7;">{time_short} WIB</td>
        </tr>
      </table>
    </td>
  </tr>

  <tr>
    <td style="padding:28px 32px 0 32px;">
      <div style="font-family:Georgia,serif;font-size:11px;text-transform:uppercase;letter-spacing:2.5px;color:#8b6914;font-weight:700;padding-bottom:6px;border-bottom:1px solid #d4cdb5;">
        Reader Inquiry &middot; Economic Intelligence
      </div>
    </td>
  </tr>

  <tr>
    <td style="padding:8px 32px 0 32px;">
      <h1 style="margin:0;font-family:Georgia,'Times New Roman',serif;font-size:30px;line-height:1.15;font-weight:700;color:#0d0d0d;letter-spacing:-0.3px;">
        {headline_text}
      </h1>
    </td>
  </tr>

  <tr>
    <td style="padding:12px 32px 14px 32px;border-bottom:1px solid #d4cdb5;">
      <p style="margin:0;font-family:Georgia,serif;font-size:15px;line-height:1.5;font-style:italic;color:#4a4233;">
        An AI-assisted analysis prepared in response to a reader's inquiry, drawing on current economic data, sector indicators, and contextual market intelligence.
      </p>
    </td>
  </tr>

  <tr>
    <td style="padding:14px 32px 18px 32px;">
      <div style="font-family:Georgia,serif;font-size:11px;text-transform:uppercase;letter-spacing:1.5px;color:#6b5d3f;">
        <span style="font-weight:700;color:#1a1a1a;">By Jojoba AI Desk</span>
        &nbsp;|&nbsp; Filed {time_short} WIB
        &nbsp;|&nbsp; {processing_time:.2f}s analysis
        &nbsp;|&nbsp; {sources_label}
      </div>
    </td>
  </tr>

  <tr>
    <td style="padding:0 32px 8px 32px;">
      {article_body}
    </td>
  </tr>

  <tr>
    <td style="padding:8px 32px 8px 32px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr><td style="border-top:2px solid #1a1a1a;font-size:0;line-height:0;">&nbsp;</td></tr>
        <tr>
          <td align="center" style="padding:14px 24px;font-family:Georgia,serif;font-style:italic;font-size:18px;line-height:1.4;color:#4a4233;">
            &ldquo;Read the data. Question the narrative. Decide for yourself.&rdquo;
          </td>
        </tr>
        <tr><td style="border-top:1px solid #1a1a1a;font-size:0;line-height:0;">&nbsp;</td></tr>
      </table>
    </td>
  </tr>

  <tr>
    <td style="padding:16px 32px 24px 32px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid #1a1a1a;border-bottom:1px solid #1a1a1a;">
        <tr>
          <td align="center" width="25%" style="padding:14px 4px;border-right:1px solid #d4cdb5;font-family:Georgia,serif;">
            <div style="font-size:9px;text-transform:uppercase;letter-spacing:1.2px;color:#6b5d3f;margin-bottom:4px;">Processing</div>
            <div style="font-size:18px;font-weight:700;color:#0d0d0d;">{processing_time:.2f}s</div>
          </td>
          <td align="center" width="25%" style="padding:14px 4px;border-right:1px solid #d4cdb5;font-family:Georgia,serif;">
            <div style="font-size:9px;text-transform:uppercase;letter-spacing:1.2px;color:#6b5d3f;margin-bottom:4px;">Sources</div>
            <div style="font-size:18px;font-weight:700;color:#0d0d0d;">{sources_count}</div>
          </td>
          <td align="center" width="25%" style="padding:14px 4px;border-right:1px solid #d4cdb5;font-family:Georgia,serif;">
            <div style="font-size:9px;text-transform:uppercase;letter-spacing:1.2px;color:#6b5d3f;margin-bottom:4px;">Type</div>
            <div style="font-size:13px;font-weight:700;color:#0d0d0d;text-transform:uppercase;">{response_type_safe}</div>
          </td>
          <td align="center" width="25%" style="padding:14px 4px;font-family:Georgia,serif;">
            <div style="font-size:9px;text-transform:uppercase;letter-spacing:1.2px;color:#6b5d3f;margin-bottom:4px;">Language</div>
            <div style="font-size:15px;font-weight:700;color:#0d0d0d;text-transform:uppercase;">{language_safe}</div>
          </td>
        </tr>
      </table>
    </td>
  </tr>
{recs_html}
  <tr>
    <td bgcolor="#1a1a1a" style="background-color:#1a1a1a;padding:20px 32px;text-align:center;">
      <div style="font-family:Georgia,serif;font-size:10px;text-transform:uppercase;letter-spacing:1.5px;color:#d4a542;font-style:italic;font-weight:700;margin-bottom:8px;">
        &#9888; Not Financial Advice &middot; For Educational Purposes Only
      </div>
      <div style="font-family:Georgia,serif;font-size:11px;line-height:1.5;color:#c8c2b0;">
        Always consult a licensed financial advisor before making investment decisions. Past performance is not indicative of future results.
      </div>
      <div style="font-family:Georgia,serif;font-size:10px;letter-spacing:0.5px;color:#8a8270;margin-top:10px;padding-top:10px;border-top:1px solid #4a4233;">
        The Jojoba Economic Review &middot; Published by Jojoba AI &middot; Reader-Requested Edition
      </div>
    </td>
  </tr>

</table>

</td></tr>
</table>

</body>
</html>"""

        return html_doc


batch_processor = BatchEmailProcessor()
