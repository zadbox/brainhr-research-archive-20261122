from __future__ import annotations

import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status

from api.dependencies import get_current_user, require_project_reader, require_project_writer
from brainrh.database import get_session
from brainrh.models.auth import UserDB, UserRole
from brainrh.models.realtime_interview import InterviewPlan, RealtimeInterviewDB
from brainrh.services.interview_sheet_service import InterviewSheetService

from brainrh.models.realtime_interview import (
    RealtimeInterviewSetupRequest,
    RealtimeToolCallsPayload,
    UpdateRealtimeInterviewPlanRequest,
)
from brainrh.services.realtime_interview_service import (
    RealtimeInterviewNotFoundError,
    RealtimeInterviewPreparationError,
    RealtimeInterviewService,
    RealtimeInterviewToolError,
)
from brainrh.services.interview_appointment_service import worker_event_secret


router = APIRouter()
logger = logging.getLogger(__name__)


def _resolve_realtime_project_id(
    interview_id: str,
    *,
    allow_legacy_plan_fallback: bool,
) -> tuple[str, str | None]:
    with get_session() as session:
        record = session.get(RealtimeInterviewDB, interview_id)
        if not record:
            raise RealtimeInterviewNotFoundError(f"Entretien {interview_id} introuvable")
        if record.interview_sheet_id:
            sheet = InterviewSheetService.get(record.interview_sheet_id)
            if sheet:
                return record.owner_user_id, sheet["job_id"]
        if record.project_id:
            return record.owner_user_id, record.project_id
        if not allow_legacy_plan_fallback:
            return record.owner_user_id, None
        try:
            plan = InterviewPlan.model_validate(record.plan_data)
        except Exception:
            return record.owner_user_id, None
        owner_user_id = record.owner_user_id

    registry_context = plan.registryContext
    if registry_context:
        if registry_context.interviewSheetId:
            sheet = InterviewSheetService.get(registry_context.interviewSheetId)
            if sheet:
                return owner_user_id, sheet["job_id"]
        if registry_context.projectId:
            return owner_user_id, registry_context.projectId
    return owner_user_id, None


def _require_realtime_reader(interview_id: str, current_user: UserDB) -> None:
    owner_user_id, project_id = _resolve_realtime_project_id(
        interview_id,
        allow_legacy_plan_fallback=True,
    )
    if project_id:
        require_project_reader(project_id, current_user)
        return
    if current_user.role != UserRole.platform_admin and str(owner_user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Accès entretien refusé")


def _require_realtime_writer(interview_id: str, current_user: UserDB) -> None:
    owner_user_id, project_id = _resolve_realtime_project_id(
        interview_id,
        allow_legacy_plan_fallback=False,
    )
    if project_id:
        require_project_writer(project_id, current_user)
        return
    if current_user.role != UserRole.platform_admin and str(owner_user_id) != str(current_user.id):
        raise HTTPException(status_code=403, detail="Accès entretien refusé")


def _has_valid_worker_secret(header_secret: Optional[str]) -> bool:
    if not header_secret:
        return False
    secret = worker_event_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="BRAINRH_WORKER_EVENT_SECRET manquant")
    return hmac.compare_digest(header_secret, secret)


@router.post("/setup", status_code=201)
def setup_realtime_interview(
    payload: RealtimeInterviewSetupRequest,
    response: Response,
    current_user: UserDB = Depends(get_current_user),
):
    try:
        project_id = payload.projectId or payload.jobId
        if payload.interviewSheetId:
            sheet = InterviewSheetService.get(payload.interviewSheetId)
            if not sheet:
                raise HTTPException(status_code=404, detail=f"Fiche {payload.interviewSheetId} introuvable")
            require_project_writer(sheet["job_id"], current_user)
        elif project_id:
            require_project_writer(project_id, current_user)
        return RealtimeInterviewService.create_interview_session(payload, owner_user_id=str(current_user.id))
    except HTTPException:
        raise
    except RealtimeInterviewPreparationError as exc:
        response.status_code = status.HTTP_202_ACCEPTED
        return {
            "interviewId": exc.interview_id,
            "plan": None,
            "preparationState": exc.preparation_state,
            "message": str(exc),
            "retryable": exc.retryable,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Realtime interview setup failed")
        raise HTTPException(status_code=500, detail=f"Erreur setup realtime interview: {exc}") from exc


@router.get("/token")
def mint_realtime_token(
    interviewId: str = Query(..., min_length=1),
    current_user: UserDB = Depends(get_current_user),
):
    try:
        _require_realtime_reader(interviewId, current_user)
        return RealtimeInterviewService.mint_realtime_client_secret(interviewId)
    except RealtimeInterviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        status_code = 500 if "OPENAI_API_KEY" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/{interview_id}/token")
def mint_realtime_token_by_id(
    interview_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    try:
        _require_realtime_reader(interview_id, current_user)
        return RealtimeInterviewService.mint_realtime_client_secret(interview_id)
    except RealtimeInterviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        status_code = 500 if "OPENAI_API_KEY" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.get("/{interview_id}/prompt")
def preview_realtime_prompt(
    interview_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    try:
        _require_realtime_reader(interview_id, current_user)
        return RealtimeInterviewService.preview_realtime_prompt(interview_id)
    except RealtimeInterviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{interview_id}")
def get_realtime_interview_context(
    interview_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    try:
        _require_realtime_reader(interview_id, current_user)
        return RealtimeInterviewService.get_interview_context(interview_id)
    except RealtimeInterviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{interview_id}/plan")
def update_realtime_interview_plan(
    interview_id: str,
    payload: UpdateRealtimeInterviewPlanRequest,
    current_user: UserDB = Depends(get_current_user),
):
    try:
        _require_realtime_writer(interview_id, current_user)
        return RealtimeInterviewService.update_interview_plan(
            interview_id,
            payload.plan.model_dump(mode="json"),
        )
    except RealtimeInterviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{interview_id}/tool-calls")
def execute_tool_calls(
    interview_id: str,
    payload: RealtimeToolCallsPayload,
    request: Request,
    x_brainrh_worker_secret: Optional[str] = Header(default=None, alias="X-BrainRH-Worker-Secret"),
):
    try:
        worker_authenticated = _has_valid_worker_secret(x_brainrh_worker_secret)
        if not worker_authenticated:
            current_user = get_current_user(request)
            _require_realtime_writer(interview_id, current_user)
        elif not payload.appointmentId and any(call.name == "finalizeInterview" for call in payload.calls):
            raise HTTPException(
                status_code=400,
                detail="appointmentId requis pour finaliser depuis un worker",
            )
        return RealtimeInterviewService.execute_tool_calls(
            interview_id,
            payload.calls,
            appointment_id=payload.appointmentId,
        )
    except RealtimeInterviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (RealtimeInterviewToolError, ValueError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{interview_id}/finalize")
def finalize_realtime_interview(
    interview_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    try:
        _require_realtime_writer(interview_id, current_user)
        result = RealtimeInterviewService.finalize_interview(interview_id)
        summary = result.get("summary")
        summary_text = summary.get("summaryText") if isinstance(summary, dict) else summary
        overall_appreciation = summary.get("overallAppreciation") if isinstance(summary, dict) else None
        return {
            **result,
            "summary": summary_text or "",
            "summaryData": summary,
            "overallAppreciation": overall_appreciation or "",
        }
    except RealtimeInterviewNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
