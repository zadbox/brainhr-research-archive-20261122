from __future__ import annotations

import json
import logging
import hmac
import mimetypes
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse

from api.dependencies import get_current_user, require_project_reader, require_project_writer
from brainrh.models.auth import UserDB
from brainrh.models.interview_appointment import (
    HumanInterviewAppointmentCreateRequest,
    InterviewAppointmentCancelRequest,
    InterviewAppointmentCreateRequest,
    InterviewAppointmentOutcomeRequest,
    WorkerEventRequest,
)
from brainrh.services.interview_sheet_service import InterviewSheetService
from brainrh.services.calcom_client import (
    CalcomAPIError,
    CalcomConfigurationError,
    verify_calcom_webhook_signature,
)
from brainrh.services.interview_appointment_service import (
    InterviewAppointmentConflictError,
    InterviewAppointmentNotFoundError,
    InterviewAppointmentService,
    calcom_webhook_secret,
    worker_event_secret,
)


router = APIRouter()
logger = logging.getLogger(__name__)


def _require_appointment_reader(appointment: dict, current_user: UserDB) -> None:
    sheet = InterviewSheetService.get(appointment["interview_sheet_id"])
    if not sheet:
        raise HTTPException(status_code=404, detail=f"Fiche {appointment['interview_sheet_id']} introuvable")
    require_project_reader(sheet["job_id"], current_user)


def _require_appointment_writer(appointment: dict, current_user: UserDB) -> None:
    sheet = InterviewSheetService.get(appointment["interview_sheet_id"])
    if not sheet:
        raise HTTPException(status_code=404, detail=f"Fiche {appointment['interview_sheet_id']} introuvable")
    require_project_writer(sheet["job_id"], current_user)


@router.post("/from-sheet/{sheet_id}/calcom", status_code=201)
def create_calcom_appointment(
    sheet_id: str,
    payload: InterviewAppointmentCreateRequest,
    current_user: UserDB = Depends(get_current_user),
):
    try:
        sheet = InterviewSheetService.get(sheet_id)
        if not sheet:
            raise HTTPException(status_code=404, detail=f"Fiche {sheet_id} introuvable")
        require_project_writer(sheet["job_id"], current_user)
        return InterviewAppointmentService.create_from_sheet(
            sheet_id,
            payload,
            owner_user_id=str(current_user.id),
        )
    except HTTPException:
        raise
    except InterviewAppointmentConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CalcomConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CalcomAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Interview appointment creation failed")
        raise HTTPException(status_code=500, detail=f"Erreur création appointment: {exc}") from exc


@router.post("/from-sheet/{sheet_id}/human", status_code=201)
def create_human_appointment(
    sheet_id: str,
    payload: HumanInterviewAppointmentCreateRequest,
    current_user: UserDB = Depends(get_current_user),
):
    """Planifie un entretien mené par un recruteur (sans agent IA ni enregistrement)."""
    try:
        sheet = InterviewSheetService.get(sheet_id)
        if not sheet:
            raise HTTPException(status_code=404, detail=f"Fiche {sheet_id} introuvable")
        require_project_writer(sheet["job_id"], current_user)
        return InterviewAppointmentService.create_human_from_sheet(
            sheet_id,
            payload,
            owner_user_email=current_user.email,
        )
    except HTTPException:
        raise
    except InterviewAppointmentConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Human interview appointment creation failed")
        raise HTTPException(status_code=500, detail="Erreur lors de la planification de l'entretien.") from exc


@router.post("/{appointment_id}/outcome")
def record_appointment_outcome(
    appointment_id: str,
    payload: InterviewAppointmentOutcomeRequest,
    current_user: UserDB = Depends(get_current_user),
):
    """Clôture un entretien recruteur : réalisé ou candidat absent."""
    try:
        appointment = InterviewAppointmentService.get(appointment_id)
        _require_appointment_writer(appointment, current_user)
        return InterviewAppointmentService.record_outcome(appointment_id, payload.outcome)
    except HTTPException:
        raise
    except InterviewAppointmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InterviewAppointmentConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{appointment_id}")
def get_appointment(
    appointment_id: str,
    request: Request,
    x_brainrh_worker_secret: Optional[str] = Header(default=None, alias="X-BrainRH-Worker-Secret"),
):
    try:
        appointment = InterviewAppointmentService.get(appointment_id)
        if x_brainrh_worker_secret:
            _verify_worker_secret(x_brainrh_worker_secret)
        else:
            current_user = get_current_user(request)
            _require_appointment_reader(appointment, current_user)
        return appointment
    except InterviewAppointmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{appointment_id}/recordings/{recording_id}")
def get_local_recording(
    appointment_id: str,
    recording_id: str,
    download: bool = False,
    current_user: UserDB = Depends(get_current_user),
):
    try:
        appointment = InterviewAppointmentService.get(appointment_id)
        _require_appointment_reader(appointment, current_user)
        resolved = InterviewAppointmentService.resolve_recording_download(
            appointment_id,
            recording_id,
            disposition="attachment" if download else "inline",
        )
    except InterviewAppointmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if resolved["kind"] == "redirect":
        return RedirectResponse(url=resolved["url"], status_code=307)

    path = resolved["path"]
    artifact = resolved["artifact"]
    content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    response = FileResponse(
        path=str(path),
        filename=artifact.get("name") or path.name,
        media_type=content_type,
    )
    disposition = "attachment" if download else "inline"
    response.headers["Content-Disposition"] = f'{disposition}; filename="{artifact.get("name") or path.name}"'
    return response


@router.post("/{appointment_id}/cancel")
def cancel_appointment(
    appointment_id: str,
    payload: Optional[InterviewAppointmentCancelRequest] = None,
    current_user: UserDB = Depends(get_current_user),
):
    try:
        appointment = InterviewAppointmentService.get(appointment_id)
        _require_appointment_writer(appointment, current_user)
        return InterviewAppointmentService.cancel(
            appointment_id,
            reason=payload.reason if payload else None,
        )
    except HTTPException:
        raise
    except InterviewAppointmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _verify_worker_secret(header_secret: Optional[str]) -> None:
    secret = worker_event_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="BRAINRH_WORKER_EVENT_SECRET manquant")
    if not header_secret or not hmac.compare_digest(header_secret, secret):
        raise HTTPException(status_code=401, detail="Secret worker invalide")


@router.post("/{appointment_id}/worker-events")
def push_worker_event(
    appointment_id: str,
    payload: WorkerEventRequest,
    x_brainrh_worker_secret: Optional[str] = Header(default=None, alias="X-BrainRH-Worker-Secret"),
):
    _verify_worker_secret(x_brainrh_worker_secret)
    try:
        return InterviewAppointmentService.handle_worker_event(appointment_id, payload)
    except InterviewAppointmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{appointment_id}/worker-realtime-config")
def get_worker_realtime_config(
    appointment_id: str,
    x_brainrh_worker_secret: Optional[str] = Header(default=None, alias="X-BrainRH-Worker-Secret"),
):
    _verify_worker_secret(x_brainrh_worker_secret)
    try:
        return InterviewAppointmentService.worker_realtime_config(appointment_id)
    except InterviewAppointmentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/calcom/webhook")
async def receive_calcom_webhook(request: Request):
    raw_body = await request.body()
    signature = request.headers.get("x-cal-signature-256")
    secret = calcom_webhook_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="CALCOM_WEBHOOK_SECRET manquant")
    if not verify_calcom_webhook_signature(raw_body, signature, secret):
        raise HTTPException(status_code=401, detail="Signature webhook Cal.com invalide")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Payload webhook Cal.com invalide") from exc

    try:
        return InterviewAppointmentService.handle_calcom_webhook(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except CalcomAPIError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
