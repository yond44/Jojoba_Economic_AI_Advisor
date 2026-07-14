"""
n8n routes — connect an n8n instance, deploy, and toggle workflows from the app.
================================================================================

All endpoints require a JWT and are scoped to the authenticated user. The API
key is write-only: you can POST it, but no endpoint ever returns it — only a
masked hint.

  POST   /api/v1/n8n/credentials                 save my n8n URL + key (encrypted)
  GET    /api/v1/n8n/status                       my connection + deployed workflows
  DELETE /api/v1/n8n/credentials                  forget my n8n key
  POST   /api/v1/n8n/deploy                        upload a workflow to my n8n
  POST   /api/v1/n8n/workflows/{key}/active        activate/deactivate  {"active": true}
  DELETE /api/v1/n8n/workflows/{key}               remove a deployed workflow
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException

from src.auth.auth import get_current_user
from src.config.database import get_db
from src.models.n8n import (
    ActiveToggle,
    DeployRequest,
    N8nCredentialCreate,
)
from src.models.user import UserInDB
from src.services import n8n_manager as nm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/n8n", tags=["n8n"])


@router.post("/credentials")
async def save_credentials(
    body: N8nCredentialCreate,
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    try:
        if body.use_default:
            # Kredensial diambil dari .env backend — tidak pernah dari browser.
            result = await nm.save_default_credentials(db, str(current_user.id))
        else:
            result = await nm.save_credentials(
                db, str(current_user.id), body.base_url, body.api_key
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not result.get("verified"):
        return {
            **result,
            "warning": "Saved, but the key could not be verified against your n8n "
                       "instance. Check the URL and that the key has API access.",
        }
    return result


@router.get("/status")
async def status(
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    return await nm.get_status(db, str(current_user.id))


@router.delete("/credentials")
async def delete_credentials(
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    ok = await nm.delete_credentials(db, str(current_user.id))
    return {"success": ok}


@router.post("/deploy")
async def deploy(
    body: DeployRequest,
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    try:
        return await nm.deploy_workflow(
            db, str(current_user.id), body.workflow_key, body.cron or "0 8 * * *",
            smtp=body.smtp.model_dump() if body.smtp else None,
            language=body.language,
            use_default_smtp=body.use_default_smtp,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"n8n error: {exc}")


@router.post("/workflows/{workflow_key}/active")
async def set_active(
    workflow_key: str,
    body: ActiveToggle,
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    try:
        return await nm.set_active(db, str(current_user.id), workflow_key, body.active)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"n8n error: {exc}")


@router.delete("/workflows/{workflow_key}")
async def delete_workflow(
    workflow_key: str,
    current_user: UserInDB = Depends(get_current_user),
    db=Depends(get_db),
):
    ok = await nm.delete_workflow(db, str(current_user.id), workflow_key)
    return {"success": ok, "workflow_key": workflow_key}