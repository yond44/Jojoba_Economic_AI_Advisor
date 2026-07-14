"""
n8n manager — deploy/activate/deactivate workflows on a USER'S OWN n8n instance.
===============================================================================

THE PRODUCT REQUIREMENT (and how each part is met)
--------------------------------------------------
"user inputs their n8n API key"            -> save_credentials()
"encrypt the key, I can't read it"         -> stored via utils/crypto (Fernet);
                                              only key_hint is ever returned/logged
"workflow auto-uploads to their n8n"       -> deploy_workflow() POSTs the template
"activate/deactivate without the dashboard"-> set_active() hits n8n activate/deactivate
"only usable through this project"         -> the deployed workflow calls back to
                                              OUR backend with a per-user webhook JWT

NO-VPS / FREE-TIER DESIGN
-------------------------
The deployed workflow is deliberately minimal: Schedule Trigger -> HTTP POST to
this backend's /api/webhook/process-next with the user's webhook token. The
BACKEND does the LLM answer + email send. So the user's n8n needs NO SMTP
credential and NO knowledge of our internals — it's just a scheduler that pokes
us. That's what makes it work on n8n Cloud's free tier with our HF Space backend.

n8n PUBLIC API (v1) USED
------------------------
  GET    {base}/api/v1/workflows            verify key / list
  POST   {base}/api/v1/workflows            create
  POST   {base}/api/v1/workflows/{id}/activate
  POST   {base}/api/v1/workflows/{id}/deactivate
  DELETE {base}/api/v1/workflows/{id}
Header on every call: X-N8N-API-KEY: <decrypted key, in memory only>
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from motor.motor_asyncio import AsyncIOMotorDatabase

from src.config.settings import get_settings
from src.utils.crypto import decrypt_secret, encrypt_secret, mask_secret
from src.utils.ownership import as_object_id, scope_filter

logger = logging.getLogger(__name__)

CREDS = "user_n8n_credentials"
WORKFLOWS = "user_n8n_workflows"

_TEMPLATE_DIR = Path(__file__).parent.parent.parent / "n8n" / "workflows"
_TEMPLATES = {
    "economic-report": {
        "file": "economic-report-user.json",
        "name": "Jojoba Economic Report",
    },
}


def available_templates() -> List[str]:
    return list(_TEMPLATES.keys())


def _now() -> datetime:
    return datetime.utcnow()


async def _n8n_request(
    base_url: str, api_key: str, method: str, path: str,
    json_body: Optional[dict] = None, timeout: float = 20.0,
) -> httpx.Response:
    url = f"{base_url.rstrip('/')}/api/v1{path}"
    headers = {"X-N8N-API-KEY": api_key, "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.request(method, url, headers=headers, json=json_body)


async def _verify_key(base_url: str, api_key: str) -> bool:
    try:
        resp = await _n8n_request(base_url, api_key, "GET", "/workflows?limit=1")
        return resp.status_code == 200
    except Exception as exc:
        logger.warning("n8n verify failed: %s", exc)
        return False


async def save_credentials(
    db: AsyncIOMotorDatabase, user_id: str, base_url: str, api_key: str,
    is_default: bool = False,
) -> Dict[str, Any]:
    """Encrypt + store the user's n8n key. Verifies it against their instance."""
    verified = await _verify_key(base_url, api_key)

    doc = {
        "user_id": as_object_id(user_id),
        "base_url": base_url,
        "api_key_encrypted": encrypt_secret(api_key),
        "key_hint": "default" if is_default else mask_secret(api_key),
        "is_default": is_default,
        "verified": verified,
        "verified_at": _now() if verified else None,
        "updated_at": _now(),
    }
    await db[CREDS].update_one(
        scope_filter(user_id), {"$set": doc, "$setOnInsert": {"created_at": _now()}},
        upsert=True,
    )
    logger.info("🔐 n8n credentials stored for user %s (verified=%s)", user_id, verified)
    return {"connected": True, "verified": verified, "key_hint": doc["key_hint"],
            "is_default": is_default,
            "base_url": None if is_default else base_url}


async def save_default_credentials(
    db: AsyncIOMotorDatabase, user_id: str
) -> Dict[str, Any]:
    """Mode "default": hubungkan user ke instance n8n MILIK APLIKASI.

    Kredensial dibaca dari .env backend (N8N_DEFAULT_BASE_URL + N8N_API_KEY),
    tidak pernah melewati browser, dan disimpan per-user dengan flag
    is_default agar status tidak menampilkan URL/hint aslinya.
    """
    _s = get_settings()
    if not _s.n8n_api_key:
        raise ValueError(
            "Mode default belum dikonfigurasi: set N8N_API_KEY (dan "
            "N8N_DEFAULT_BASE_URL) di .env backend."
        )
    return await save_credentials(
        db, user_id, _s.n8n_default_base_url.rstrip("/"), _s.n8n_api_key,
        is_default=True,
    )


async def _load_creds(db: AsyncIOMotorDatabase, user_id: str) -> Optional[Dict[str, Any]]:
    return await db[CREDS].find_one(scope_filter(user_id))


async def _decrypted_key(db: AsyncIOMotorDatabase, user_id: str) -> Optional[tuple]:
    """Return (base_url, plaintext_key) transiently, or None. Plaintext lives
    only in the caller's stack frame and is never persisted/logged."""
    creds = await _load_creds(db, user_id)
    if not creds:
        return None
    try:
        return creds["base_url"], decrypt_secret(creds["api_key_encrypted"])
    except ValueError as exc:
        logger.error("Cannot decrypt n8n key for user %s: %s", user_id, exc)
        return None


async def get_status(db: AsyncIOMotorDatabase, user_id: str) -> Dict[str, Any]:
    creds = await _load_creds(db, user_id)
    _is_default = bool(creds.get("is_default")) if creds else False
    credential = {
        "connected": bool(creds),
        "base_url": (None if _is_default else creds.get("base_url")) if creds else None,
        "is_default": _is_default,
        "key_hint": creds.get("key_hint") if creds else None,
        "verified": creds.get("verified", False) if creds else False,
        "verified_at": creds.get("verified_at") if creds else None,
        "updated_at": creds.get("updated_at") if creds else None,
    }
    wf_docs = [w async for w in db[WORKFLOWS].find(scope_filter(user_id))]
    workflows = [
        {
            "workflow_key": w["workflow_key"],
            "name": w.get("name", w["workflow_key"]),
            "n8n_workflow_id": w.get("n8n_workflow_id"),
            "active": w.get("active", False),
            "deployed": bool(w.get("n8n_workflow_id")),
            "smtp_attached": w.get("smtp_attached", False),
            "updated_at": w.get("updated_at"),
        }
        for w in wf_docs
    ]
    return {"credential": credential, "workflows": workflows,
            "available_templates": available_templates()}


async def delete_credentials(db: AsyncIOMotorDatabase, user_id: str) -> bool:
    res = await db[CREDS].delete_one(scope_filter(user_id))
    return res.deleted_count > 0


def _mint_webhook_token(user_id: str, days: int = 365) -> str:
    from src.auth.auth import create_access_token
    return create_access_token(
        {"sub": f"n8n:{user_id}", "user_id": user_id, "purpose": "n8n-webhook"},
        expires_delta=timedelta(days=days),
    )


def _render_template(workflow_key: str, user_id: str, cron: str, language: str = "en") -> Dict[str, Any]:
    tpl = _TEMPLATES[workflow_key]
    raw = (_TEMPLATE_DIR / tpl["file"]).read_text(encoding="utf-8")
    settings = get_settings()
    raw = (
        raw.replace("__PUBLIC_BASE_URL__", settings.public_base_url)
        .replace("__WEBHOOK_TOKEN__", _mint_webhook_token(user_id))
        .replace("__CRON__", cron or "0 8 * * *")
        .replace("__LANGUAGE__", language or "en")
    )
    return json.loads(raw)


async def _create_smtp_credential(
    base_url: str, api_key: str, smtp: Dict[str, Any], user_id: str,
) -> Dict[str, str]:
    """Create an SMTP credential ON THE USER'S n8n via its public API.

    Workflow JSON can only *reference* credentials by id — secrets can't ride
    inside the workflow itself — so this is the programmatic path: create the
    credential first, then attach {id, name} to the Email Send node. The
    password is forwarded once to the user's own n8n and never stored by us.
    """
    name = f"Jojoba SMTP ({smtp.get('user', 'smtp')})"
    body = {
        "name": name,
        "type": "smtp",
        "data": {
            "user": smtp["user"],
            "password": smtp["password"],
            "host": smtp["host"],
            "port": int(smtp.get("port", 465)),
            "secure": bool(smtp.get("secure", True)),
        },
    }
    resp = await _n8n_request(base_url, api_key, "POST", "/credentials", json_body=body)
    if resp.status_code not in (200, 201):
        logger.error("n8n credential create failed %s: %s", resp.status_code, resp.text[:300])
        raise RuntimeError(f"n8n credential create returned {resp.status_code}")
    cred_id = resp.json().get("id")
    logger.info("🔑 Created SMTP credential on user's n8n (user %s)", user_id)
    return {"id": cred_id, "name": name}


def _attach_smtp(payload: Dict[str, Any], cred: Dict[str, str], from_email: str) -> None:
    """Point every Email Send node in the rendered workflow at the credential."""
    for node in payload.get("nodes", []):
        if node.get("type") == "n8n-nodes-base.emailSend":
            node["credentials"] = {"smtp": {"id": cred["id"], "name": cred["name"]}}
            if from_email:
                node.setdefault("parameters", {})["fromEmail"] = from_email


async def deploy_workflow(
    db: AsyncIOMotorDatabase, user_id: str,
    workflow_key: str = "economic-report", cron: str = "0 8 * * *",
    smtp: Optional[Dict[str, Any]] = None,
    language: str = "en",
    use_default_smtp: bool = False,
) -> Dict[str, Any]:
    if workflow_key not in _TEMPLATES:
        raise ValueError(f"Unknown workflow_key: {workflow_key}")

    creds = await _decrypted_key(db, user_id)
    if not creds:
        raise ValueError("No verified n8n credentials on file")
    base_url, api_key = creds

    # SMTP default aplikasi (dari .env backend) — user tidak melihat kredensial.
    if use_default_smtp:
        _sd = get_settings()
        if not (_sd.smtp_user and _sd.smtp_password):
            raise ValueError(
                "SMTP default belum dikonfigurasi: set SMTP_USER dan "
                "SMTP_PASSWORD di .env backend."
            )
        smtp = {
            "host": _sd.smtp_host,
            "port": _sd.smtp_port,
            "user": _sd.smtp_user,
            "password": _sd.smtp_password,
            "secure": int(_sd.smtp_port) == 465,
            "from_email": _sd.smtp_user,
        }

    payload = _render_template(workflow_key, user_id, cron, language)

    smtp_attached = False
    if smtp:
        cred = await _create_smtp_credential(base_url, api_key, smtp, user_id)
        _attach_smtp(payload, cred, smtp.get("from_email") or smtp.get("user", ""))
        smtp_attached = True

    resp = await _n8n_request(base_url, api_key, "POST", "/workflows", json_body=payload)
    if resp.status_code not in (200, 201):
        logger.error("n8n deploy failed %s: %s", resp.status_code, resp.text[:300])
        raise RuntimeError(f"n8n returned {resp.status_code}")

    n8n_id = resp.json().get("id")
    await db[WORKFLOWS].update_one(
        scope_filter(user_id, {"workflow_key": workflow_key}),
        {
            "$set": {
                "user_id": as_object_id(user_id),
                "workflow_key": workflow_key,
                "name": _TEMPLATES[workflow_key]["name"],
                "n8n_workflow_id": n8n_id,
                "active": False,
                "smtp_attached": smtp_attached,
                "updated_at": _now(),
            },
            "$setOnInsert": {"created_at": _now()},
        },
        upsert=True,
    )
    logger.info("🚀 Deployed workflow %s -> n8n id %s (user %s)", workflow_key, n8n_id, user_id)
    return {"deployed": True, "workflow_key": workflow_key, "n8n_workflow_id": n8n_id,
            "active": False, "smtp_attached": smtp_attached}


async def set_active(
    db: AsyncIOMotorDatabase, user_id: str, workflow_key: str, active: bool
) -> Dict[str, Any]:
    creds = await _decrypted_key(db, user_id)
    if not creds:
        raise ValueError("No verified n8n credentials on file")
    base_url, api_key = creds

    wf = await db[WORKFLOWS].find_one(scope_filter(user_id, {"workflow_key": workflow_key}))
    if not wf or not wf.get("n8n_workflow_id"):
        raise ValueError("Workflow not deployed yet")

    action = "activate" if active else "deactivate"
    resp = await _n8n_request(
        base_url, api_key, "POST", f"/workflows/{wf['n8n_workflow_id']}/{action}"
    )
    if resp.status_code not in (200, 201):
        logger.error("n8n %s failed %s: %s", action, resp.status_code, resp.text[:200])
        raise RuntimeError(f"n8n {action} returned {resp.status_code}")

    await db[WORKFLOWS].update_one(
        scope_filter(user_id, {"workflow_key": workflow_key}),
        {"$set": {"active": active, "updated_at": _now()}},
    )
    logger.info("🎚️ Workflow %s %sd (user %s)", workflow_key, action, user_id)
    return {"workflow_key": workflow_key, "active": active}


async def delete_workflow(
    db: AsyncIOMotorDatabase, user_id: str, workflow_key: str
) -> bool:
    creds = await _decrypted_key(db, user_id)
    wf = await db[WORKFLOWS].find_one(scope_filter(user_id, {"workflow_key": workflow_key}))
    if wf and wf.get("n8n_workflow_id") and creds:
        base_url, api_key = creds
        try:
            await _n8n_request(base_url, api_key, "DELETE",
                               f"/workflows/{wf['n8n_workflow_id']}")
        except Exception as exc:
            logger.warning("n8n delete call failed (removing local record anyway): %s", exc)
    res = await db[WORKFLOWS].delete_one(scope_filter(user_id, {"workflow_key": workflow_key}))
    return res.deleted_count > 0