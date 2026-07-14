import os
import ssl
import socket
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from typing import List, Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_original_getaddrinfo = socket.getaddrinfo

def _getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return _original_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

socket.getaddrinfo = _getaddrinfo_ipv4

EMAIL_PROVIDER = os.getenv("EMAIL_PROVIDER", "brevo").lower()
EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() == "true"
FROM_EMAIL = os.getenv("FROM_EMAIL", "")
FROM_NAME = os.getenv("FROM_NAME", "Jojoba Economic Review")

BREVO_API_KEY = os.getenv("BREVO_API_KEY", "")
BREVO_SEND_URL = "https://api.brevo.com/v3/smtp/email"
BREVO_ACCOUNT_URL = "https://api.brevo.com/v3/account"

RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
RESEND_API_URL = "https://api.resend.com/emails"
RESEND_DOMAINS_URL = "https://api.resend.com/domains"

SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")
SENDGRID_SEND_URL = "https://api.sendgrid.com/v3/mail/send"
SENDGRID_ACCOUNT_URL = "https://api.sendgrid.com/v3/user/account"

MAILGUN_API_KEY = os.getenv("MAILGUN_API_KEY", "")
MAILGUN_DOMAIN = os.getenv("MAILGUN_DOMAIN", "")
MAILGUN_BASE_URL = os.getenv("MAILGUN_BASE_URL", "https://api.mailgun.net")

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "false").lower() == "true"


async def verify_email_config() -> dict:
    """Check that the configured provider is actually reachable and
    the credentials are valid, without sending any real email."""

    if not EMAIL_ENABLED:
        return {"ok": True, "provider": None, "message": "Email sending is disabled (EMAIL_ENABLED=false)"}

    if EMAIL_PROVIDER == "brevo":
        return await _verify_brevo()
    elif EMAIL_PROVIDER == "resend":
        return await _verify_resend()
    elif EMAIL_PROVIDER == "sendgrid":
        return await _verify_sendgrid()
    elif EMAIL_PROVIDER == "mailgun":
        return await _verify_mailgun()
    elif EMAIL_PROVIDER == "smtp":
        return _verify_smtp()
    else:
        return {"ok": False, "provider": EMAIL_PROVIDER, "message": f"Unknown EMAIL_PROVIDER: {EMAIL_PROVIDER}"}


async def _verify_brevo() -> dict:
    if not BREVO_API_KEY:
        return {"ok": False, "provider": "brevo", "message": "BREVO_API_KEY not set"}

    if not FROM_EMAIL:
        return {"ok": False, "provider": "brevo", "message": "FROM_EMAIL not set (must be a verified sender in Brevo)"}

    headers = {"api-key": BREVO_API_KEY}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(BREVO_ACCOUNT_URL, headers=headers)

        if response.status_code == 200:
            logger.info("✅ Brevo API key verified")
            return {"ok": True, "provider": "brevo", "message": "Brevo API key is valid"}
        elif response.status_code == 401:
            logger.error("❌ Brevo API key rejected (401)")
            return {"ok": False, "provider": "brevo", "message": "Brevo API key invalid or expired"}
        else:
            logger.error(f"❌ Brevo verification failed: {response.status_code} - {response.text}")
            return {"ok": False, "provider": "brevo", "message": f"Brevo check failed: {response.status_code}"}

    except Exception as e:
        logger.error(f"❌ Brevo verification error: {str(e)}")
        return {"ok": False, "provider": "brevo", "message": f"Could not reach Brevo API: {str(e)}"}


async def _verify_resend() -> dict:
    if not RESEND_API_KEY:
        return {"ok": False, "provider": "resend", "message": "RESEND_API_KEY not set"}

    headers = {"Authorization": f"Bearer {RESEND_API_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(RESEND_DOMAINS_URL, headers=headers)

        if response.status_code == 200:
            logger.info("✅ Resend API key verified")
            return {"ok": True, "provider": "resend", "message": "Resend API key is valid"}
        elif response.status_code == 401:
            logger.error("❌ Resend API key rejected (401)")
            return {"ok": False, "provider": "resend", "message": "Resend API key invalid or expired"}
        else:
            logger.error(f"❌ Resend verification failed: {response.status_code} - {response.text}")
            return {"ok": False, "provider": "resend", "message": f"Resend check failed: {response.status_code}"}

    except Exception as e:
        logger.error(f"❌ Resend verification error: {str(e)}")
        return {"ok": False, "provider": "resend", "message": f"Could not reach Resend API: {str(e)}"}


async def _verify_sendgrid() -> dict:
    if not SENDGRID_API_KEY:
        return {"ok": False, "provider": "sendgrid", "message": "SENDGRID_API_KEY not set"}

    if not FROM_EMAIL:
        return {"ok": False, "provider": "sendgrid", "message": "FROM_EMAIL not set (must be a Verified Sender in SendGrid)"}

    headers = {"Authorization": f"Bearer {SENDGRID_API_KEY}"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(SENDGRID_ACCOUNT_URL, headers=headers)

        if response.status_code == 200:
            logger.info("✅ SendGrid API key verified")
            return {"ok": True, "provider": "sendgrid", "message": "SendGrid API key is valid"}
        elif response.status_code == 401:
            logger.error("❌ SendGrid API key rejected (401)")
            return {"ok": False, "provider": "sendgrid", "message": "SendGrid API key invalid or expired"}
        else:
            logger.error(f"❌ SendGrid verification failed: {response.status_code} - {response.text}")
            return {"ok": False, "provider": "sendgrid", "message": f"SendGrid check failed: {response.status_code}"}

    except Exception as e:
        logger.error(f"❌ SendGrid verification error: {str(e)}")
        return {"ok": False, "provider": "sendgrid", "message": f"Could not reach SendGrid API: {str(e)}"}


async def _verify_mailgun() -> dict:
    if not MAILGUN_API_KEY:
        return {"ok": False, "provider": "mailgun", "message": "MAILGUN_API_KEY not set"}

    if not MAILGUN_DOMAIN:
        return {"ok": False, "provider": "mailgun", "message": "MAILGUN_DOMAIN not set (e.g. sandboxXXXX.mailgun.org)"}

    url = f"{MAILGUN_BASE_URL}/v3/domains/{MAILGUN_DOMAIN}"

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, auth=("api", MAILGUN_API_KEY))

        if response.status_code == 200:
            logger.info("✅ Mailgun domain and API key verified")
            return {"ok": True, "provider": "mailgun", "message": "Mailgun domain and API key are valid"}
        elif response.status_code == 401:
            logger.error("❌ Mailgun API key rejected (401)")
            return {"ok": False, "provider": "mailgun", "message": "Mailgun API key invalid"}
        elif response.status_code == 404:
            logger.error("❌ Mailgun domain not found (404)")
            return {"ok": False, "provider": "mailgun", "message": f"Mailgun domain not found: {MAILGUN_DOMAIN}"}
        else:
            logger.error(f"❌ Mailgun verification failed: {response.status_code} - {response.text}")
            return {"ok": False, "provider": "mailgun", "message": f"Mailgun check failed: {response.status_code}"}

    except Exception as e:
        logger.error(f"❌ Mailgun verification error: {str(e)}")
        return {"ok": False, "provider": "mailgun", "message": f"Could not reach Mailgun API: {str(e)}"}


def _verify_smtp() -> dict:
    if not SMTP_USER or not SMTP_PASSWORD:
        return {"ok": False, "provider": "smtp", "message": "SMTP_USER or SMTP_PASSWORD not set"}

    server = None
    try:
        if SMTP_USE_SSL or SMTP_PORT == 465:
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=10)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10)
            server.ehlo()
            server.starttls()
            server.ehlo()

        server.login(SMTP_USER, SMTP_PASSWORD)
        server.quit()

        logger.info("✅ SMTP credentials verified")
        return {"ok": True, "provider": "smtp", "message": "SMTP login successful"}

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ SMTP auth failed: {str(e)}")
        return {"ok": False, "provider": "smtp", "message": "SMTP authentication failed"}
    except (TimeoutError, socket.timeout, OSError) as e:
        logger.error(f"❌ SMTP unreachable: {str(e)}")
        return {"ok": False, "provider": "smtp", "message": f"SMTP host unreachable: {str(e)}"}
    except Exception as e:
        logger.error(f"❌ SMTP verification error: {str(e)}")
        return {"ok": False, "provider": "smtp", "message": f"SMTP check failed: {str(e)}"}
    finally:
        if server:
            try:
                server.close()
            except Exception:
                pass


async def send_batch_emails(
    to_emails: List[str],
    subject: str,
    body: str,
    html_body: Optional[str] = None
) -> dict:

    if not to_emails:
        return {
            "sent_count": 0,
            "failed_emails": [],
            "error": "No recipients provided"
        }

    if not EMAIL_ENABLED:
        logger.info(f"📧 [DISABLED] Would send to {len(to_emails)} recipients")
        for email in to_emails:
            logger.info(f"  📧 {email}")
        return {
            "sent_count": len(to_emails),
            "failed_emails": [],
            "simulated": True,
            "message": "Email sending is disabled (EMAIL_ENABLED=false)"
        }

    verification = await verify_email_config()
    if not verification["ok"]:
        logger.warning(f"⚠️ Email config verification failed: {verification['message']}")
        for email in to_emails:
            logger.info(f"📧 [SIMULATED] Would send to: {email}")
        return {
            "sent_count": 0,
            "failed_emails": to_emails,
            "simulated": True,
            "error": verification["message"],
            "message": f"{EMAIL_PROVIDER} verification failed, emails not sent"
        }

    content_html = html_body if html_body else body.replace("\n", "<br>")

    if EMAIL_PROVIDER == "brevo":
        return await _send_via_brevo(to_emails, subject, content_html)
    elif EMAIL_PROVIDER == "resend":
        return await _send_via_resend(to_emails, subject, content_html)
    elif EMAIL_PROVIDER == "sendgrid":
        return await _send_via_sendgrid(to_emails, subject, content_html)
    elif EMAIL_PROVIDER == "mailgun":
        return await _send_via_mailgun(to_emails, subject, content_html)
    elif EMAIL_PROVIDER == "smtp":
        return _send_via_smtp(to_emails, subject, content_html)
    else:
        return {
            "sent_count": 0,
            "failed_emails": to_emails,
            "error": f"Unknown EMAIL_PROVIDER: {EMAIL_PROVIDER}",
            "emails": to_emails
        }


async def _send_via_brevo(to_emails: List[str], subject: str, content_html: str) -> dict:
    sent_count = 0
    failed_emails = []
    errors = []

    headers = {
        "api-key": BREVO_API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        for email in to_emails:
            payload = {
                "sender": {"name": FROM_NAME, "email": FROM_EMAIL},
                "to": [{"email": email}],
                "subject": subject,
                "htmlContent": content_html,
            }

            try:
                response = await client.post(BREVO_SEND_URL, json=payload, headers=headers)

                if response.status_code in (200, 201):
                    sent_count += 1
                    logger.info(f"✅ Email sent to: {email}")
                else:
                    failed_emails.append(email)
                    error_msg = f"Failed to send to {email}: {response.status_code} - {response.text}"
                    errors.append(error_msg)
                    logger.error(f"❌ {error_msg}")

            except httpx.TimeoutException:
                failed_emails.append(email)
                error_msg = f"Failed to send to {email}: request timed out"
                errors.append(error_msg)
                logger.error(f"❌ {error_msg}")
            except Exception as e:
                failed_emails.append(email)
                error_msg = f"Failed to send to {email}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"❌ {error_msg}")

    return {
        "sent_count": sent_count,
        "failed_emails": failed_emails,
        "errors": errors,
        "emails": to_emails
    }


async def _send_via_resend(to_emails: List[str], subject: str, content_html: str) -> dict:
    sent_count = 0
    failed_emails = []
    errors = []

    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        for email in to_emails:
            payload = {
                "from": FROM_EMAIL,
                "to": [email],
                "subject": subject,
                "html": content_html,
            }

            try:
                response = await client.post(RESEND_API_URL, json=payload, headers=headers)

                if response.status_code in (200, 201):
                    sent_count += 1
                    logger.info(f"✅ Email sent to: {email}")
                else:
                    failed_emails.append(email)
                    error_msg = f"Failed to send to {email}: {response.status_code} - {response.text}"
                    errors.append(error_msg)
                    logger.error(f"❌ {error_msg}")

            except httpx.TimeoutException:
                failed_emails.append(email)
                error_msg = f"Failed to send to {email}: request timed out"
                errors.append(error_msg)
                logger.error(f"❌ {error_msg}")
            except Exception as e:
                failed_emails.append(email)
                error_msg = f"Failed to send to {email}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"❌ {error_msg}")

    return {
        "sent_count": sent_count,
        "failed_emails": failed_emails,
        "errors": errors,
        "emails": to_emails
    }


async def _send_via_sendgrid(to_emails: List[str], subject: str, content_html: str) -> dict:
    sent_count = 0
    failed_emails = []
    errors = []

    headers = {
        "Authorization": f"Bearer {SENDGRID_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        for email in to_emails:
            payload = {
                "personalizations": [
                    {"to": [{"email": email}]}
                ],
                "from": {"email": FROM_EMAIL},
                "subject": subject,
                "content": [
                    {"type": "text/html", "value": content_html}
                ],
            }

            try:
                response = await client.post(SENDGRID_SEND_URL, json=payload, headers=headers)

                if response.status_code in (200, 201, 202):
                    sent_count += 1
                    logger.info(f"✅ Email sent to: {email}")
                else:
                    failed_emails.append(email)
                    error_msg = f"Failed to send to {email}: {response.status_code} - {response.text}"
                    errors.append(error_msg)
                    logger.error(f"❌ {error_msg}")

            except httpx.TimeoutException:
                failed_emails.append(email)
                error_msg = f"Failed to send to {email}: request timed out"
                errors.append(error_msg)
                logger.error(f"❌ {error_msg}")
            except Exception as e:
                failed_emails.append(email)
                error_msg = f"Failed to send to {email}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"❌ {error_msg}")

    return {
        "sent_count": sent_count,
        "failed_emails": failed_emails,
        "errors": errors,
        "emails": to_emails
    }


async def _send_via_mailgun(to_emails: List[str], subject: str, content_html: str) -> dict:
    sent_count = 0
    failed_emails = []
    errors = []

    url = f"{MAILGUN_BASE_URL}/v3/{MAILGUN_DOMAIN}/messages"

    async with httpx.AsyncClient(timeout=30) as client:
        for email in to_emails:
            data = {
                "from": FROM_EMAIL,
                "to": [email],
                "subject": subject,
                "html": content_html,
            }

            try:
                response = await client.post(url, auth=("api", MAILGUN_API_KEY), data=data)

                if response.status_code == 200:
                    sent_count += 1
                    logger.info(f"✅ Email sent to: {email}")
                else:
                    failed_emails.append(email)
                    error_msg = f"Failed to send to {email}: {response.status_code} - {response.text}"
                    errors.append(error_msg)
                    logger.error(f"❌ {error_msg}")

            except httpx.TimeoutException:
                failed_emails.append(email)
                error_msg = f"Failed to send to {email}: request timed out"
                errors.append(error_msg)
                logger.error(f"❌ {error_msg}")
            except Exception as e:
                failed_emails.append(email)
                error_msg = f"Failed to send to {email}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"❌ {error_msg}")

    return {
        "sent_count": sent_count,
        "failed_emails": failed_emails,
        "errors": errors,
        "emails": to_emails
    }


def _send_via_smtp(to_emails: List[str], subject: str, content_html: str) -> dict:
    sent_count = 0
    failed_emails = []
    errors = []
    server = None

    try:
        logger.info(f"📧 Connecting to {SMTP_HOST}:{SMTP_PORT}")

        if SMTP_USE_SSL or SMTP_PORT == 465:
            context = ssl.create_default_context()
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=30)
            logger.info("✅ Using SSL connection")
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30)
            logger.info("✅ Using STARTTLS connection")
            server.ehlo()
            server.starttls()
            server.ehlo()

        server.login(SMTP_USER, SMTP_PASSWORD)
        logger.info("✅ SMTP Login successful")

        for email in to_emails:
            try:
                msg = MIMEMultipart()
                msg["From"] = FROM_EMAIL or SMTP_USER
                msg["To"] = email
                msg["Subject"] = subject
                msg.attach(MIMEText(content_html, "html"))

                server.send_message(msg)
                sent_count += 1
                logger.info(f"✅ Email sent to: {email}")

            except Exception as e:
                failed_emails.append(email)
                error_msg = f"Failed to send to {email}: {str(e)}"
                errors.append(error_msg)
                logger.error(f"❌ {error_msg}")

        server.quit()

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"❌ SMTP Authentication failed: {str(e)}")
        return {
            "sent_count": sent_count,
            "failed_emails": to_emails[sent_count:] if sent_count < len(to_emails) else to_emails,
            "error": "SMTP Authentication failed. Check your credentials.",
            "emails": to_emails
        }
    except smtplib.SMTPException as e:
        logger.error(f"❌ SMTP error: {str(e)}")
        return {
            "sent_count": sent_count,
            "failed_emails": to_emails[sent_count:] if sent_count < len(to_emails) else to_emails,
            "error": f"SMTP error: {str(e)}",
            "emails": to_emails
        }
    except (TimeoutError, socket.timeout):
        logger.error("❌ SMTP connection timeout")
        return {
            "sent_count": sent_count,
            "failed_emails": to_emails[sent_count:] if sent_count < len(to_emails) else to_emails,
            "error": "Connection timeout. Check network/firewall (Render free tier blocks SMTP ports).",
            "emails": to_emails
        }
    except Exception as e:
        logger.error(f"❌ SMTP connection error: {str(e)}")
        return {
            "sent_count": sent_count,
            "failed_emails": to_emails[sent_count:] if sent_count < len(to_emails) else to_emails,
            "error": f"Connection error: {str(e)}",
            "emails": to_emails
        }

    return {
        "sent_count": sent_count,
        "failed_emails": failed_emails,
        "errors": errors,
        "emails": to_emails
    }


def get_email_list_from_contacts(contacts: List[dict]) -> List[str]:
    return [c.get("email") for c in contacts if c.get("email")]