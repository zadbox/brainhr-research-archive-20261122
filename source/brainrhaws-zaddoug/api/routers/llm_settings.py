from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session

from api.dependencies import get_current_user
from brainrh.database import get_session_dependency
from brainrh.models.auth import UserDB, UserRole
from brainrh.services.audit_service import AuditService
from brainrh.services.llm_settings_service import (
    list_llm_process_settings,
    update_llm_process_setting,
)

router = APIRouter(prefix="/admin/llm-settings", tags=["Administration"])


class UpdateLLMProcessSettingRequest(BaseModel):
    provider: str
    model: str


def _require_platform_admin(current_user: UserDB) -> None:
    if current_user.role != UserRole.platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès réservé au platform_admin.",
        )


@router.get("")
def list_settings(
    current_user: UserDB = Depends(get_current_user),
    session: Session = Depends(get_session_dependency),
):
    _require_platform_admin(current_user)
    return {"processes": list_llm_process_settings(session)}


@router.patch("/{process_id}")
def update_setting(
    process_id: str,
    body: UpdateLLMProcessSettingRequest,
    current_user: UserDB = Depends(get_current_user),
    session: Session = Depends(get_session_dependency),
):
    _require_platform_admin(current_user)
    try:
        update_llm_process_setting(
            session,
            process_id=process_id,
            provider=body.provider,
            model=body.model,
            actor_user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    AuditService.create_event(
        session,
        enterprise_id="SYSTEM",
        actor_user_id=current_user.id,
        action="llm_settings.updated",
        resource_type="llm_process",
        resource_id=process_id,
        metadata={"provider": body.provider, "model": body.model},
    )
    return {"processes": list_llm_process_settings(session)}
