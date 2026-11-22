from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
import json
import mimetypes
import os
import uuid
from urllib.parse import quote

from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from brainrh.database import get_session
from brainrh.models import InterviewSheetDB
from brainrh.models.interview_appointment import (
    HumanInterviewAppointmentCreateRequest,
    InterviewAppointmentCreateRequest,
    InterviewAppointmentDB,
    InterviewAppointmentStatus,
    InterviewMode,
    WorkerEventRequest,
    utc_now,
)
from brainrh.models.realtime_interview import (
    InterviewContextMode,
    InterviewStatus,
    RealtimeInterviewDB,
    RealtimeInterviewSetupRequest,
)
from brainrh.paths import PROJECT_ROOT, STORAGE_ROOT
from brainrh.services.calcom_client import (
    CalcomAPIError,
    CalcomClient,
    CalcomConfigurationError,
    extract_calcom_video_url,
    get_calcom_settings,
)
from brainrh.services.cal_video_worker_launcher import CalVideoWorkerLauncher
from brainrh.services.email_sender import (
    EmailConfigurationError,
    EmailDeliveryError,
    EmailSender,
    InterviewInvitationEmail,
    get_email_sender,
    validate_mailbox,
)
from brainrh.services.file_storage import FileStorage
from brainrh.services.interview_invitation_email import (
    InterviewInvitationDetails,
    build_interview_ics,
    render_interview_invitation,
)
from brainrh.services.interview_meeting_provider import (
    HumanMeetingProvider,
    HumanMeetingRequest,
    get_human_meeting_provider,
)
from brainrh.services.interview_sheet_service import InterviewSheetService
from brainrh.services.project_file_service import ProjectFileService
from brainrh.services.project_service import ProjectService
from brainrh.services.realtime_interview_service import (
    RealtimeInterviewService,
)
from brainrh.services.realtime_interview_registry_service import (
    RealtimeInterviewRegistryError,
    RealtimeInterviewRegistryService,
)
from brainrh.settings import use_s3_storage


AI_INTERVIEWER_NAME = "BrainRH AI Interviewer"
DISCLOSURE_TEXT = (
    "Cet entretien sera conduit par un agent IA BrainRH et sera enregistré/transcrit "
    "à des fins d'évaluation recrutement."
)


class InterviewAppointmentNotFoundError(Exception):
    pass


class InterviewAppointmentConflictError(Exception):
    pass


PRIVATE_RECORDING_FIELDS = {"path", "container_path", "log_path", "storage_key"}


class InterviewAppointmentService:
    ACTIVE_STATUSES = {
        InterviewAppointmentStatus.scheduled.value,
        InterviewAppointmentStatus.waiting_candidate.value,
        InterviewAppointmentStatus.in_progress.value,
        InterviewAppointmentStatus.paused.value,
        InterviewAppointmentStatus.wrapping_up.value,
    }

    @staticmethod
    def create_from_sheet(
        sheet_id: str,
        payload: InterviewAppointmentCreateRequest,
        *,
        owner_user_id: str,
        calcom_client: CalcomClient | None = None,
    ) -> dict[str, Any]:
        sheet, sheet_data = InterviewAppointmentService._load_sheet(sheet_id)
        existing = InterviewAppointmentService._get_active_for_sheet(sheet_id)
        if existing:
            raise InterviewAppointmentConflictError(
                f"Un appointment actif existe déjà pour la fiche {sheet_id}: {existing['id']}"
            )

        start_at = InterviewAppointmentService._as_utc(payload.start_at)
        end_at = InterviewAppointmentService._resolve_end_at(start_at, payload)

        registry_setup = InterviewAppointmentService._resolve_registry_setup_for_sheet(
            sheet,
            sheet_data,
            payload,
        )
        candidate_name = (
            payload.candidate_name.strip()
            if payload.candidate_name and payload.candidate_name.strip()
            else registry_setup.get("candidateName")
            or InterviewAppointmentService._resolve_candidate_name(sheet, sheet_data, payload)
        )
        registry_context = registry_setup.get("registryContext") or {}
        if registry_context.get("interviewSheetId") != sheet_id:
            raise ValueError(
                "Contexte registry invalide pour créer l'appointment Cal.com: "
                f"fiche liée attendue {sheet_id}"
            )
        candidate_email = (
            payload.candidate_email.strip()
            if payload.candidate_email and payload.candidate_email.strip()
            else registry_context.get("candidateEmail")
            or (registry_setup.get("candidate") or {}).get("email")
            or InterviewAppointmentService._resolve_candidate_email(sheet_data, payload)
        )
        if not candidate_email:
            raise ValueError("Email candidat requis pour créer le booking Cal.com")

        client = calcom_client or CalcomClient()
        event_reference = client.resolve_event_reference()
        recording_setup = InterviewAppointmentService._ensure_cal_video_recording(client, event_reference)
        recording_warning = recording_setup.get("error") if recording_setup.get("error") else None

        appointment_id = str(uuid.uuid4())
        realtime_request = RealtimeInterviewSetupRequest(
            mode=InterviewContextMode.registry,
            projectId=sheet.job_id,
            candidateId=sheet.candidate_id,
            matchingId=sheet.matching_id,
            interviewSheetId=sheet_id,
            aiPlanInstructions=registry_setup.get("aiPlanInstructions") or "",
            languageHint=payload.language_hint,
        )
        realtime = RealtimeInterviewService.create_interview_session(
            realtime_request,
            owner_user_id=owner_user_id,
        )
        realtime_interview_id = realtime["interviewId"]

        booking_payload = InterviewAppointmentService._build_calcom_booking_payload(
            appointment_id=appointment_id,
            sheet_id=sheet_id,
            realtime_interview_id=realtime_interview_id,
            start_at=start_at,
            payload=payload,
            candidate_name=candidate_name,
            candidate_email=candidate_email,
            event_reference=event_reference,
        )

        with get_session() as session:
            realtime_claim = session.exec(
                update(RealtimeInterviewDB)
                .where(
                    RealtimeInterviewDB.id == realtime_interview_id,
                    RealtimeInterviewDB.status != InterviewStatus.completed.value,
                    RealtimeInterviewDB.active_sheet_slot == sheet_id,
                )
                .values(updated_at=utc_now())
            )
            if realtime_claim.rowcount != 1:
                session.rollback()
                raise InterviewAppointmentConflictError(
                    "La session IA liée a changé pendant la planification. Relancez la planification."
                )
            record = InterviewAppointmentDB(
                id=appointment_id,
                interview_sheet_id=sheet_id,
                realtime_interview_id=realtime_interview_id,
                status=InterviewAppointmentStatus.scheduled.value,
                active_slot=InterviewAppointmentService._active_slot_for_status(
                    sheet_id,
                    InterviewAppointmentStatus.scheduled.value,
                ),
                start_at=start_at,
                end_at=end_at,
                candidate_name=candidate_name,
                candidate_email=candidate_email,
                candidate_timezone=payload.candidate_timezone,
                ai_interviewer_name=AI_INTERVIEWER_NAME,
                calcom_event_type_id=event_reference.get("eventTypeId"),
                calcom_event_type_slug=event_reference.get("eventTypeSlug"),
                worker_state={"events": []},
                artifact_data={
                    "disclosure": DISCLOSURE_TEXT,
                    "source": "calcom",
                    "calcom_recording": recording_setup,
                },
            )
            try:
                session.add(record)
                session.commit()
                session.refresh(record)
            except IntegrityError as exc:
                session.rollback()
                raise InterviewAppointmentConflictError(
                    f"Un appointment actif existe déjà pour la fiche {sheet_id}"
                ) from exc

        try:
            booking_response = client.create_booking(booking_payload)
            booking = booking_response.get("data") or {}
            if not isinstance(booking, dict):
                raise CalcomAPIError("Réponse Cal.com invalide: data booking manquant")
            booking_uid = booking.get("uid")
            if not booking_uid:
                raise CalcomAPIError("Réponse Cal.com invalide: uid booking manquant")

            references: list[dict[str, Any]] = []
            references_warning = None
            try:
                references = client.get_booking_references(booking_uid)
            except Exception as exc:
                references_warning = f"Cal.com artifact warning: {exc}"

            video_url = extract_calcom_video_url(booking)
            booking_start = booking.get("start") or booking.get("startTime")
            booking_end = booking.get("end") or booking.get("endTime")
            provider_start_at = (
                InterviewAppointmentService._parse_datetime(booking_start)
                if booking_start
                else None
            )
            provider_end_at = (
                InterviewAppointmentService._parse_datetime(booking_end)
                if booking_end
                else None
            )
        except Exception as exc:
            provider_error = f"Cal.com provider error: {exc}"
            record_dict = InterviewAppointmentService._mark_provider_error(
                appointment_id,
                error=provider_error,
            )
            InterviewAppointmentService._write_sheet_scheduling(
                sheet,
                sheet_data,
                appointment_id=appointment_id,
                start_at=start_at,
                end_at=end_at,
                video_url=None,
                notes=payload.scheduler_notes,
                booking_uid=None,
                booking_status=record_dict["status"],
            )
            worker_launch = CalVideoWorkerLauncher.mark_skipped(
                appointment_id,
                reason="No joinable Cal Video URL",
            )
            return {
                "appointment": record_dict,
                "booking": {},
                "realtime": realtime,
                "workerLaunch": worker_launch,
                "providerWarning": provider_error,
            }

        if not video_url:
            provider_warning = InterviewAppointmentService._combine_warnings(
                "Booking Cal.com créé sans URL Cal Video. Vérifier que l'event type utilise Cal Video.",
                references_warning,
                recording_warning,
            )
            with get_session() as session:
                record = session.get(InterviewAppointmentDB, appointment_id)
                if not record:
                    raise InterviewAppointmentNotFoundError(f"Appointment {appointment_id} introuvable")
                record.calcom_booking_uid = str(booking_uid)
                record.calcom_booking_id = str(booking.get("id") or booking.get("bookingId") or "")
                record.calcom_event_type_id = booking.get("eventTypeId") or event_reference.get("eventTypeId")
                record.calcom_event_type_slug = (
                    (booking.get("eventType") or {}).get("slug")
                    if isinstance(booking.get("eventType"), dict)
                    else event_reference.get("eventTypeSlug")
                )
                record.booking_data = booking
                record.booking_references = references
                record.last_error = provider_warning
                record.artifact_data = {
                    **(record.artifact_data or {}),
                    "calcom": InterviewAppointmentService._calcom_artifact_state(
                        status="accepted_without_video",
                        booking_uid=str(booking_uid),
                        video_url=None,
                        provider_start_at=provider_start_at,
                        provider_end_at=provider_end_at,
                        brainrh_start_at=start_at,
                        brainrh_end_at=end_at,
                        recording_setup=recording_setup,
                    ),
                }
                record.updated_at = utc_now()
                session.add(record)
                session.commit()
                session.refresh(record)
                record_dict = InterviewAppointmentService._to_dict(record)

            InterviewAppointmentService._write_sheet_scheduling(
                sheet,
                sheet_data,
                appointment_id=appointment_id,
                start_at=start_at,
                end_at=end_at,
                video_url=None,
                notes=payload.scheduler_notes,
                booking_uid=str(booking_uid),
                booking_status=record_dict["status"],
            )
            worker_launch = CalVideoWorkerLauncher.mark_skipped(
                appointment_id,
                reason="No joinable Cal Video URL",
            )
            return {
                "appointment": record_dict,
                "booking": booking,
                "realtime": realtime,
                "workerLaunch": worker_launch,
                "providerWarning": provider_warning,
            }

        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                raise InterviewAppointmentNotFoundError(f"Appointment {appointment_id} introuvable")
            record.calcom_booking_uid = str(booking_uid)
            record.calcom_booking_id = str(booking.get("id") or booking.get("bookingId") or "")
            record.calcom_event_type_id = booking.get("eventTypeId") or event_reference.get("eventTypeId")
            record.calcom_event_type_slug = (
                (booking.get("eventType") or {}).get("slug")
                if isinstance(booking.get("eventType"), dict)
                else event_reference.get("eventTypeSlug")
            )
            record.calcom_video_url = video_url
            record.booking_data = booking
            record.booking_references = references
            record.artifact_data = {
                **(record.artifact_data or {}),
                "calcom": InterviewAppointmentService._calcom_artifact_state(
                    status="accepted",
                    booking_uid=str(booking_uid),
                    video_url=video_url,
                    provider_start_at=provider_start_at,
                    provider_end_at=provider_end_at,
                    brainrh_start_at=start_at,
                    brainrh_end_at=end_at,
                    recording_setup=recording_setup,
                ),
            }
            record.updated_at = utc_now()
            session.add(record)
            session.commit()
            session.refresh(record)
            record_dict = InterviewAppointmentService._to_dict(record)
            provider_warning = InterviewAppointmentService._provider_time_warning(
                provider_start_at=provider_start_at,
                provider_end_at=provider_end_at,
                brainrh_start_at=start_at,
                brainrh_end_at=end_at,
            )
            provider_warning = InterviewAppointmentService._combine_warnings(
                provider_warning,
                references_warning,
                recording_warning,
            )

        InterviewAppointmentService._write_sheet_scheduling(
            sheet,
            sheet_data,
            appointment_id=appointment_id,
            start_at=start_at,
            end_at=end_at,
            video_url=video_url,
            notes=payload.scheduler_notes,
            booking_uid=str(booking_uid),
            booking_status=record_dict["status"],
        )
        worker_launch = CalVideoWorkerLauncher.schedule_or_launch(
            appointment_id,
            start_at=start_at,
            end_at=end_at,
        )
        response = {
            "appointment": record_dict,
            "booking": booking,
            "realtime": realtime,
            "workerLaunch": worker_launch,
        }
        if provider_warning:
            response["providerWarning"] = provider_warning
        return response

    @staticmethod
    def get(appointment_id: str) -> dict[str, Any]:
        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                raise InterviewAppointmentNotFoundError(f"Appointment {appointment_id} introuvable")
            return InterviewAppointmentService._to_dict(record)

    @staticmethod
    def create_human_from_sheet(
        sheet_id: str,
        payload: HumanInterviewAppointmentCreateRequest,
        *,
        owner_user_email: str | None,
        meeting_provider: HumanMeetingProvider | None = None,
        email_sender_factory: Callable[[], EmailSender] | None = None,
    ) -> dict[str, Any]:
        """Planifie un entretien mené par un recruteur : ni session IA, ni enregistrement.

        Plusieurs entretiens recruteur peuvent être planifiés pour un même candidat,
        en plus de l'entretien IA : ils n'occupent pas le créneau actif de la fiche.
        """
        sheet, sheet_data = InterviewAppointmentService._load_sheet(sheet_id)

        start_at = InterviewAppointmentService._as_utc(payload.start_at)
        end_at = InterviewAppointmentService._resolve_end_at(start_at, payload)
        if start_at <= utc_now():
            raise ValueError("L'entretien doit être planifié à une date future.")

        meeting = (meeting_provider or get_human_meeting_provider()).prepare(
            HumanMeetingRequest(
                meeting_format=payload.meeting_format,
                meeting_url=payload.meeting_url,
                meeting_location=payload.meeting_location,
            )
        )

        candidate_name = InterviewAppointmentService._resolve_candidate_name(sheet, sheet_data, payload)
        candidate_email = InterviewAppointmentService._resolve_candidate_email(sheet_data, payload)
        if candidate_email:
            candidate_email = InterviewAppointmentService._normalize_email(candidate_email, "Email candidat")
        if payload.send_invitation and not candidate_email:
            raise ValueError("Email candidat requis pour envoyer l'invitation.")

        interviewer_email = (payload.interviewer_email or owner_user_email or "").strip() or None
        if interviewer_email:
            interviewer_email = InterviewAppointmentService._normalize_email(interviewer_email, "Email du recruteur")
        interviewer_name = (
            " ".join((payload.interviewer_name or "").split())[:200]
            or interviewer_email
            or "Recruteur"
        )

        appointment_id = str(uuid.uuid4())
        with get_session() as session:
            record = InterviewAppointmentDB(
                id=appointment_id,
                interview_sheet_id=sheet_id,
                realtime_interview_id=None,
                interview_mode=InterviewMode.human.value,
                provider=meeting.provider,
                status=InterviewAppointmentStatus.scheduled.value,
                active_slot=None,
                start_at=start_at,
                end_at=end_at,
                candidate_name=candidate_name,
                candidate_email=candidate_email or "",
                candidate_timezone=payload.candidate_timezone,
                title=" ".join((payload.title or "").split())[:120] or None,
                interviewer_name=interviewer_name,
                interviewer_email=interviewer_email,
                meeting_format=meeting.meeting_format,
                meeting_url=meeting.meeting_url,
                meeting_location=meeting.meeting_location,
                worker_state={},
                artifact_data={
                    "source": meeting.provider,
                    "invitation": {"status": "pending" if payload.send_invitation else "not_requested"},
                },
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            record_dict = InterviewAppointmentService._to_dict(record)

        InterviewAppointmentService._sync_sheet_scheduling_from_appointment(
            record_dict,
            notes=payload.scheduler_notes,
            mark_in_progress=True,
        )

        invitation: dict[str, Any] = {"status": "not_requested"}
        invitation_warning = None
        if payload.send_invitation and not meeting.invitation_sent_by_provider:
            invitation, invitation_warning = InterviewAppointmentService._deliver_human_invitation(
                record_dict,
                role_title=InterviewAppointmentService._resolve_role_title(sheet),
                language=payload.invitation_language,
                cancelled=False,
                email_sender_factory=email_sender_factory,
            )
            record_dict = InterviewAppointmentService._store_invitation_state(appointment_id, invitation)

        response: dict[str, Any] = {"appointment": record_dict, "invitation": invitation}
        if invitation_warning:
            response["invitationWarning"] = invitation_warning
        return response

    @staticmethod
    def record_outcome(appointment_id: str, outcome: str) -> dict[str, Any]:
        """Clôture un entretien recruteur : réalisé ou candidat absent."""
        if outcome not in {InterviewAppointmentStatus.completed.value, InterviewAppointmentStatus.no_show.value}:
            raise ValueError("Résultat d'entretien inconnu.")
        now = utc_now()
        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                raise InterviewAppointmentNotFoundError(f"Appointment {appointment_id} introuvable")
            if record.interview_mode != InterviewMode.human.value:
                raise ValueError("Le déroulé d'un entretien IA est transmis par l'agent, pas saisi à la main.")
            if record.status == outcome:
                return {"appointment": InterviewAppointmentService._to_dict(record)}
            if record.status not in InterviewAppointmentService.ACTIVE_STATUSES:
                raise InterviewAppointmentConflictError(
                    f"L'entretien n'est plus planifié (statut : {record.status})."
                )
            if InterviewAppointmentService._as_utc(record.start_at) > now:
                raise ValueError("L'entretien n'a pas encore commencé.")

            record.status = outcome
            record.active_slot = None
            if outcome == InterviewAppointmentStatus.completed.value:
                record.completed_at = now
            record.worker_state = {
                **(record.worker_state or {}),
                "outcome": {"value": outcome, "recorded_at": InterviewAppointmentService._iso_z(now)},
            }
            record.updated_at = now
            session.add(record)
            session.commit()
            session.refresh(record)
            record_dict = InterviewAppointmentService._to_dict(record)

        InterviewAppointmentService._sync_sheet_scheduling_from_appointment(record_dict)
        return {"appointment": record_dict}

    @staticmethod
    def _normalize_email(value: str, label: str) -> str:
        try:
            return validate_mailbox(value, setting_name=label)
        except EmailConfigurationError as exc:
            raise ValueError(f"{label} invalide.") from exc

    @staticmethod
    def _resolve_role_title(sheet: InterviewSheetDB) -> str | None:
        """Intitulé de l'offre, seule information du projet montrée au candidat."""
        try:
            project = ProjectService.get_project(sheet.job_id) or {}
            offer = ProjectFileService.load_offer(sheet.job_id, enterprise_id=project.get("enterprise_id")) or {}
        except Exception:
            return None
        title = offer.get("intitule") or offer.get("title") or offer.get("poste") if isinstance(offer, dict) else None
        if not isinstance(title, str) or not title.strip():
            return None
        return " ".join(title.split())[:160]

    @staticmethod
    def _deliver_human_invitation(
        appointment: dict[str, Any],
        *,
        role_title: str | None,
        language: str,
        cancelled: bool,
        sequence: int = 0,
        email_sender_factory: Callable[[], EmailSender] | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        """Envoie l'invitation (ou son annulation) ; ne lève jamais, ne journalise aucun destinataire."""
        attempted_at = InterviewAppointmentService._iso_z(utc_now())
        base = {"language": language, "sequence": sequence, "role_title": role_title}
        details = InterviewInvitationDetails(
            appointment_id=appointment["id"],
            candidate_name=appointment["candidate_name"],
            candidate_email=appointment["candidate_email"],
            interviewer_name=appointment.get("interviewer_name") or "BRAIN HR",
            interviewer_email=appointment.get("interviewer_email"),
            start_at=InterviewAppointmentService._parse_datetime(appointment["start_at"]),
            end_at=InterviewAppointmentService._parse_datetime(appointment["end_at"]),
            candidate_timezone=appointment.get("candidate_timezone") or "UTC",
            meeting_format=appointment.get("meeting_format") or "video",
            meeting_url=appointment.get("meeting_url"),
            meeting_location=appointment.get("meeting_location"),
            role_title=role_title,
            language=language,
            sequence=sequence,
            cancelled=cancelled,
            interview_title=appointment.get("title"),
        )
        try:
            subject, text_body, html_body = render_interview_invitation(details)
            message = InterviewInvitationEmail(
                recipient=details.candidate_email,
                subject=subject,
                text_body=text_body,
                html_body=html_body,
                ics_content=build_interview_ics(details, stamp=utc_now()),
                ics_method="CANCEL" if cancelled else "PUBLISH",
                sender_display_name=details.interviewer_name,
                cc=(details.interviewer_email,) if details.interviewer_email else (),
                reply_to=details.interviewer_email,
            )
            sender = (email_sender_factory or get_email_sender)()
            message_id = sender.send_interview_invitation(message)
        except EmailConfigurationError:
            return (
                {**base, "status": "not_configured", "attempted_at": attempted_at},
                "L'envoi d'e-mails n'est pas configuré : transmettez vous-même les informations au candidat.",
            )
        except EmailDeliveryError:
            return (
                {**base, "status": "failed", "attempted_at": attempted_at},
                "L'e-mail n'a pas pu être envoyé : transmettez vous-même les informations au candidat.",
            )
        except Exception:
            return (
                {**base, "status": "failed", "attempted_at": attempted_at},
                "L'e-mail n'a pas pu être préparé : transmettez vous-même les informations au candidat.",
            )
        return (
            {
                **base,
                "status": "sent",
                "sent_at": attempted_at,
                "message_id": message_id,
                "interviewer_copied": bool(details.interviewer_email),
            },
            None,
        )

    @staticmethod
    def _store_invitation_state(
        appointment_id: str,
        invitation: dict[str, Any],
        *,
        key: str = "invitation",
    ) -> dict[str, Any]:
        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                raise InterviewAppointmentNotFoundError(f"Appointment {appointment_id} introuvable")
            artifact_data = dict(record.artifact_data or {})
            if key == "invitation":
                artifact_data["invitation"] = invitation
            else:
                artifact_data["invitation"] = {**(artifact_data.get("invitation") or {}), key: invitation}
            record.artifact_data = artifact_data
            record.updated_at = utc_now()
            session.add(record)
            session.commit()
            session.refresh(record)
            return InterviewAppointmentService._to_dict(record)

    @staticmethod
    def cancel(
        appointment_id: str,
        *,
        reason: str | None = None,
        calcom_client: CalcomClient | None = None,
        email_sender_factory: Callable[[], EmailSender] | None = None,
    ) -> dict[str, Any]:
        cancellation_reason = (reason or "Cancelled from BrainRH").strip() or "Cancelled from BrainRH"
        cancelled_at = utc_now()

        # Le mode ne change jamais : un entretien recruteur n'a ni booking Cal.com ni agent.
        if InterviewAppointmentService.get(appointment_id).get("interview_mode") == InterviewMode.human.value:
            return InterviewAppointmentService._cancel_human(
                appointment_id,
                reason=cancellation_reason,
                cancelled_at=cancelled_at,
                email_sender_factory=email_sender_factory,
            )

        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                raise InterviewAppointmentNotFoundError(f"Appointment {appointment_id} introuvable")

            if record.status == InterviewAppointmentStatus.cancelled.value:
                return {"appointment": InterviewAppointmentService._to_dict(record), "providerCancel": {}}

            if record.status in {
                InterviewAppointmentStatus.completed.value,
                InterviewAppointmentStatus.no_show.value,
            }:
                return {"appointment": InterviewAppointmentService._to_dict(record), "providerCancel": {}}

            booking_uid = record.calcom_booking_uid
            existing_calcom = InterviewAppointmentService._calcom_artifact_dict(record.artifact_data)
            record.status = InterviewAppointmentStatus.cancelled.value
            record.active_slot = None
            record.cancelled_at = cancelled_at
            record.worker_state = {
                **(record.worker_state or {}),
                "cancelled": {
                    "reason": cancellation_reason,
                    "cancelled_at": InterviewAppointmentService._iso_z(cancelled_at),
                },
            }
            record.artifact_data = {
                **(record.artifact_data or {}),
                "calcom": {
                    **existing_calcom,
                    "status": "cancel_requested_by_brainrh",
                    "cancel_reason": cancellation_reason,
                    "cancel_requested_at": InterviewAppointmentService._iso_z(cancelled_at),
                },
            }
            record.updated_at = utc_now()
            session.add(record)
            session.commit()
            session.refresh(record)
            record_dict = InterviewAppointmentService._to_dict(record)

        provider_cancel: dict[str, Any] = {}
        provider_warning = None
        if booking_uid:
            try:
                provider_cancel = (calcom_client or CalcomClient()).cancel_booking(
                    booking_uid,
                    cancellation_reason=cancellation_reason,
                )
            except Exception as exc:
                provider_warning = f"Cal.com cancellation warning: {exc}"

            with get_session() as session:
                record = session.get(InterviewAppointmentDB, appointment_id)
                if record:
                    existing_calcom = InterviewAppointmentService._calcom_artifact_dict(record.artifact_data)
                    record.artifact_data = {
                        **(record.artifact_data or {}),
                        "calcom": {
                            **existing_calcom,
                            "status": "cancel_failed" if provider_warning else "cancelled_by_brainrh",
                            "cancelled_at": InterviewAppointmentService._iso_z(utc_now())
                            if not provider_warning
                            else existing_calcom.get("cancelled_at"),
                            "cancel_error": provider_warning,
                        },
                    }
                    if provider_warning:
                        record.last_error = provider_warning
                    data = provider_cancel.get("data") if isinstance(provider_cancel, dict) else None
                    if isinstance(data, dict):
                        record.booking_data = {**(record.booking_data or {}), **data}
                    record.updated_at = utc_now()
                    session.add(record)
                    session.commit()
                    session.refresh(record)
                    record_dict = InterviewAppointmentService._to_dict(record)

        InterviewAppointmentService._sync_sheet_scheduling_from_appointment(record_dict)

        response = {"appointment": record_dict, "providerCancel": provider_cancel}
        if provider_warning:
            response["providerWarning"] = provider_warning
        return response

    @staticmethod
    def _cancel_human(
        appointment_id: str,
        *,
        reason: str,
        cancelled_at: datetime,
        email_sender_factory: Callable[[], EmailSender] | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                raise InterviewAppointmentNotFoundError(f"Appointment {appointment_id} introuvable")
            if record.status not in InterviewAppointmentService.ACTIVE_STATUSES:
                return {"appointment": InterviewAppointmentService._to_dict(record), "providerCancel": {}}

            record.status = InterviewAppointmentStatus.cancelled.value
            record.active_slot = None
            record.cancelled_at = cancelled_at
            record.worker_state = {
                **(record.worker_state or {}),
                "cancelled": {
                    "reason": reason,
                    "cancelled_at": InterviewAppointmentService._iso_z(cancelled_at),
                },
            }
            record.updated_at = utc_now()
            session.add(record)
            session.commit()
            session.refresh(record)
            record_dict = InterviewAppointmentService._to_dict(record)

        InterviewAppointmentService._sync_sheet_scheduling_from_appointment(record_dict)

        response: dict[str, Any] = {"appointment": record_dict, "providerCancel": {}}
        invitation = (record_dict.get("artifact_data") or {}).get("invitation") or {}
        if invitation.get("status") == "sent" and record_dict.get("candidate_email"):
            cancellation, warning = InterviewAppointmentService._deliver_human_invitation(
                record_dict,
                role_title=invitation.get("role_title"),
                language=invitation.get("language") or "fr",
                cancelled=True,
                sequence=int(invitation.get("sequence") or 0) + 1,
                email_sender_factory=email_sender_factory,
            )
            response["appointment"] = InterviewAppointmentService._store_invitation_state(
                appointment_id,
                cancellation,
                key="cancellation",
            )
            if warning:
                response["invitationWarning"] = warning
        return response

    @staticmethod
    def _get_active_for_sheet(sheet_id: str) -> dict[str, Any] | None:
        """Entretien IA actif de la fiche : un seul à la fois, la session IA étant liée à la fiche."""
        with get_session() as session:
            stmt = (
                select(InterviewAppointmentDB)
                .where(InterviewAppointmentDB.interview_sheet_id == sheet_id)
                .where(InterviewAppointmentDB.interview_mode == InterviewMode.ai.value)
                .where(InterviewAppointmentDB.status.in_(InterviewAppointmentService.ACTIVE_STATUSES))
                .order_by(InterviewAppointmentDB.created_at.desc())
            )
            record = session.exec(stmt).first()
            return InterviewAppointmentService._to_dict(record) if record else None

    @staticmethod
    def handle_worker_event(appointment_id: str, payload: WorkerEventRequest) -> dict[str, Any]:
        occurred_at = InterviewAppointmentService._as_utc(payload.occurred_at or utc_now())
        event_name = payload.event.strip()
        if not event_name:
            raise ValueError("event est requis")

        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                raise InterviewAppointmentNotFoundError(f"Appointment {appointment_id} introuvable")
            if record.interview_mode == InterviewMode.human.value:
                raise ValueError("Aucun agent IA n'intervient dans un entretien recruteur.")

            if InterviewAppointmentService._is_stale_worker_event(record, event_name):
                response = InterviewAppointmentService._record_ignored_worker_event(
                    session,
                    record,
                    event_name,
                    occurred_at,
                    payload,
                    reason="stale_or_terminal_appointment",
                )
                return response

            if (
                event_name in {"completed", "failed", "no_show"}
                and InterviewAppointmentService._has_other_active_slot(session, record)
            ):
                return InterviewAppointmentService._record_ignored_worker_event(
                    session,
                    record,
                    event_name,
                    occurred_at,
                    payload,
                    reason="another_active_appointment_for_sheet",
                )

            next_status = InterviewAppointmentService._status_for_worker_event(event_name, record.status)
            next_active_slot = InterviewAppointmentService._active_slot_for_status(
                record.interview_sheet_id,
                next_status,
            )
            if next_active_slot and InterviewAppointmentService._has_other_active_slot(session, record):
                response = InterviewAppointmentService._record_ignored_worker_event(
                    session,
                    record,
                    event_name,
                    occurred_at,
                    payload,
                    reason="another_active_appointment_for_sheet",
                )
                return response

            events = list((record.worker_state or {}).get("events", []))
            events.append(
                {
                    "event": event_name,
                    "occurred_at": InterviewAppointmentService._iso_z(occurred_at),
                    "details": payload.details,
                    "error": payload.error,
                }
            )
            record.worker_state = {**(record.worker_state or {}), "events": events, "last_event": event_name}
            record.status = next_status
            record.active_slot = next_active_slot
            record.updated_at = utc_now()
            if event_name in {"failed", "join_unavailable"}:
                record.last_error = payload.error or payload.details.get("reason") or record.last_error
            elif event_name in {"joined", "candidate_detected", "resumed", "wrapping_up", "completed"}:
                record.last_error = None

            if event_name == "joined":
                record.joined_at = occurred_at
            elif event_name in {"candidate_detected", "resumed"} and record.candidate_detected_at is None:
                record.candidate_detected_at = occurred_at
            elif event_name == "candidate_left":
                record.candidate_left_at = occurred_at
            elif event_name == "completed":
                record.completed_at = occurred_at
            elif event_name == "no_show":
                record.completed_at = occurred_at

            if event_name in {"completed", "failed"}:
                InterviewAppointmentService._attach_local_recording_artifact(record, payload.details)

            session.add(record)
            session.commit()
            session.refresh(record)
            has_execution_evidence = InterviewAppointmentService._has_candidate_execution_evidence(
                record
            )
            response = InterviewAppointmentService._to_dict(record)

        if event_name in {"completed", "failed"} and has_execution_evidence:
            InterviewAppointmentService._finalize_realtime_safely(
                response["realtime_interview_id"],
                appointment_id=response["id"],
            )
        if event_name in {
            "joined",
            "candidate_detected",
            "candidate_left",
            "resumed",
            "wrapping_up",
            "completed",
            "failed",
            "no_show",
            "join_unavailable",
        }:
            InterviewAppointmentService._sync_sheet_scheduling_from_appointment(response)
        return response

    @staticmethod
    def _attach_local_recording_artifact(record: InterviewAppointmentDB, details: dict[str, Any]) -> None:
        local_recording = details.get("local_recording")
        if not isinstance(local_recording, dict):
            return

        normalized_recording = InterviewAppointmentService._normalize_local_recording_artifact(record.id, local_recording)
        normalized_recording = InterviewAppointmentService._upload_recording_artifact_if_needed(record, normalized_recording)
        record.recordings = InterviewAppointmentService._merge_recordings(record.recordings or [], [normalized_recording])

        artifact_data = dict(record.artifact_data or {})
        artifact_data["local_recording"] = normalized_recording
        record.artifact_data = artifact_data

    @staticmethod
    def _normalize_local_recording_artifact(appointment_id: str, artifact: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(artifact)
        normalized.setdefault("provider", "brainrh_worker_local")
        normalized.setdefault("type", "call_recording")
        if not normalized.get("id"):
            raw_path = str(normalized.get("path") or normalized.get("container_path") or "").strip()
            if raw_path:
                normalized["id"] = Path(raw_path).stem
        return InterviewAppointmentService._with_recording_access_urls(
            appointment_id,
            [normalized],
            include_private=True,
        )[0]

    @staticmethod
    def _upload_recording_artifact_if_needed(
        record: InterviewAppointmentDB,
        artifact: dict[str, Any],
    ) -> dict[str, Any]:
        if artifact.get("storage_key"):
            return artifact

        source_path: Path | None = None
        for candidate_path in InterviewAppointmentService._local_recording_path_candidates(artifact):
            resolved = candidate_path.resolve()
            if resolved.is_file() and InterviewAppointmentService._is_allowed_local_recording_path(resolved):
                source_path = resolved
                break

        if source_path is None:
            return artifact

        if not use_s3_storage():
            return artifact

        with get_session() as session:
            sheet = session.get(InterviewSheetDB, record.interview_sheet_id)
            project_id = sheet.job_id if sheet else None
        if not project_id:
            return artifact

        from brainrh.services.project_service import ProjectService

        project = ProjectService.get_project(project_id)
        enterprise_id = project.get("enterprise_id") if project else None
        if not enterprise_id or not project_id:
            return artifact

        filename = source_path.name
        storage_key = (
            f"enterprises/{enterprise_id}/projects/{project_id}/recordings/{record.id}/{filename}"
        )
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        FileStorage.save_local_file(storage_key, source_path, content_type=content_type)

        uploaded = dict(artifact)
        uploaded["provider"] = "brainrh_worker_s3"
        uploaded["storage_key"] = storage_key
        uploaded["uploaded_at"] = utc_now().isoformat()
        return InterviewAppointmentService._with_recording_access_urls(
            record.id,
            [uploaded],
            include_private=True,
        )[0]

    @staticmethod
    def _merge_recordings(existing: list[Any], incoming: list[Any]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        positions: dict[str, int] = {}
        for item in [*(existing or []), *(incoming or [])]:
            if not isinstance(item, dict):
                continue
            candidate = dict(item)
            key = InterviewAppointmentService._recording_key(candidate)
            if key and key in positions:
                index = positions[key]
                merged[index] = {**merged[index], **candidate}
                continue
            if key:
                positions[key] = len(merged)
            merged.append(candidate)
        return merged

    @staticmethod
    def _recording_key(recording: dict[str, Any]) -> str:
        identifier = str(
            recording.get("id")
            or recording.get("uid")
            or recording.get("recordingId")
            or recording.get("download_url")
            or recording.get("downloadUrl")
            or recording.get("url")
            or recording.get("path")
            or ""
        ).strip()
        if not identifier:
            return ""
        provider = str(recording.get("provider") or recording.get("source") or "unknown").strip()
        return f"{provider}:{identifier}"

    @staticmethod
    def _is_stale_worker_event(record: InterviewAppointmentDB, event_name: str) -> bool:
        if event_name in {"failed", "completed", "no_show"}:
            return False
        if record.status in {
            InterviewAppointmentStatus.cancelled.value,
            InterviewAppointmentStatus.completed.value,
            InterviewAppointmentStatus.no_show.value,
        }:
            return True
        if record.status == InterviewAppointmentStatus.failed.value and utc_now() >= InterviewAppointmentService._as_utc(
            record.end_at
        ):
            return True
        return False

    @staticmethod
    def _has_other_active_slot(session, record: InterviewAppointmentDB) -> bool:
        stmt = (
            select(InterviewAppointmentDB)
            .where(InterviewAppointmentDB.interview_sheet_id == record.interview_sheet_id)
            .where(InterviewAppointmentDB.active_slot == record.interview_sheet_id)
            .where(InterviewAppointmentDB.id != record.id)
        )
        return session.exec(stmt).first() is not None

    @staticmethod
    def _has_candidate_execution_evidence(record: InterviewAppointmentDB) -> bool:
        if record.candidate_detected_at is not None:
            return True

        events = (record.worker_state or {}).get("events", [])
        if any(
            isinstance(event, dict) and event.get("event") in {"candidate_detected", "resumed"}
            for event in events
        ):
            return True

        return any(
            isinstance(item, dict)
            and str(item.get("speaker") or item.get("role") or "").lower() == "candidate"
            and bool(str(item.get("text") or item.get("content") or "").strip())
            for item in (record.transcripts or [])
        )

    @staticmethod
    def _record_ignored_worker_event(
        session,
        record: InterviewAppointmentDB,
        event_name: str,
        occurred_at: datetime,
        payload: WorkerEventRequest,
        *,
        reason: str,
    ) -> dict[str, Any]:
        events = list((record.worker_state or {}).get("events", []))
        events.append(
            {
                "event": event_name,
                "occurred_at": InterviewAppointmentService._iso_z(occurred_at),
                "details": {**payload.details, "ignored": True, "reason": reason},
                "error": payload.error,
            }
        )
        record.worker_state = {
            **(record.worker_state or {}),
            "events": events,
            "last_ignored_event": event_name,
            "last_ignored_reason": reason,
        }
        record.updated_at = utc_now()
        session.add(record)
        session.commit()
        session.refresh(record)
        return InterviewAppointmentService._to_dict(record)

    @staticmethod
    def handle_calcom_webhook(payload: dict[str, Any]) -> dict[str, Any]:
        trigger = str(payload.get("triggerEvent") or "").strip()
        if not trigger:
            raise ValueError("Webhook Cal.com sans triggerEvent")

        booking_payload = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
        appointment_id = InterviewAppointmentService._find_id_for_calcom_payload(booking_payload)
        if appointment_id is None:
            return {"handled": False, "reason": "appointment_not_found", "triggerEvent": trigger}
        if InterviewAppointmentService.get(appointment_id).get("interview_mode") == InterviewMode.human.value:
            return {"handled": False, "reason": "not_an_ai_appointment", "triggerEvent": trigger}

        updated = InterviewAppointmentService._apply_calcom_event(appointment_id, trigger, booking_payload)

        if trigger in {"RECORDING_READY", "TRANSCRIPTION_READY", "TRANSCRIPT_READY"}:
            updated = InterviewAppointmentService.sync_calcom_artifacts(appointment_id)

        return {"handled": True, "triggerEvent": trigger, "appointment": updated}

    @staticmethod
    def sync_calcom_artifacts(appointment_id: str, *, calcom_client: CalcomClient | None = None) -> dict[str, Any]:
        client = calcom_client or CalcomClient()
        errors: list[str] = []

        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                raise InterviewAppointmentNotFoundError(f"Appointment {appointment_id} introuvable")
            booking_uid = record.calcom_booking_uid

        if not booking_uid:
            raise ValueError("Appointment sans booking Cal.com")

        references = InterviewAppointmentService._try_calcom_artifact(
            lambda: client.get_booking_references(booking_uid), errors
        )
        sessions = InterviewAppointmentService._try_calcom_artifact(
            lambda: client.get_conferencing_sessions(booking_uid), errors
        )
        recordings = InterviewAppointmentService._try_calcom_artifact(
            lambda: client.get_recordings(booking_uid), errors
        )
        transcripts = InterviewAppointmentService._try_calcom_artifact(
            lambda: client.get_transcripts(booking_uid), errors
        )

        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                raise InterviewAppointmentNotFoundError(f"Appointment {appointment_id} introuvable")

            if references is not None:
                record.booking_references = references
            if sessions is not None:
                record.conferencing_sessions = sessions
            if recordings is not None:
                record.recordings = InterviewAppointmentService._merge_recordings(record.recordings or [], recordings)
            if transcripts is not None:
                record.transcripts = transcripts
            if record.status == InterviewAppointmentStatus.wrapping_up.value:
                record.status = InterviewAppointmentStatus.completed.value
                record.active_slot = None
                record.completed_at = record.completed_at or utc_now()
            record.last_error = "; ".join(errors) if errors else record.last_error
            record.updated_at = utc_now()
            session.add(record)
            session.commit()
            session.refresh(record)
            record_dict = InterviewAppointmentService._to_dict(record)

        InterviewAppointmentService._sync_sheet_scheduling_from_appointment(record_dict)
        return record_dict

    @staticmethod
    def _apply_calcom_event(
        appointment_id: str,
        trigger: str,
        booking_payload: dict[str, Any],
    ) -> dict[str, Any]:
        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                raise InterviewAppointmentNotFoundError(f"Appointment {appointment_id} introuvable")

            if booking_payload:
                record.booking_data = {**(record.booking_data or {}), **booking_payload}

            start = booking_payload.get("startTime") or booking_payload.get("start")
            end = booking_payload.get("endTime") or booking_payload.get("end")
            provider_start_at = InterviewAppointmentService._parse_datetime(start) if start else None
            provider_end_at = InterviewAppointmentService._parse_datetime(end) if end else None

            video_url = extract_calcom_video_url(booking_payload)
            if video_url:
                record.calcom_video_url = video_url

            existing_calcom = InterviewAppointmentService._calcom_artifact_dict(record.artifact_data)
            record.artifact_data = {
                **(record.artifact_data or {}),
                "last_calcom_event": trigger,
                "calcom": {
                    **existing_calcom,
                    "last_event": trigger,
                    "last_event_at": utc_now().isoformat(),
                    "provider_start_at": (
                        InterviewAppointmentService._iso_z(provider_start_at)
                        if provider_start_at
                        else existing_calcom.get("provider_start_at")
                    ),
                    "provider_end_at": (
                        InterviewAppointmentService._iso_z(provider_end_at)
                        if provider_end_at
                        else existing_calcom.get("provider_end_at")
                    ),
                    "video_url": video_url or record.calcom_video_url,
                    "provider_time_mismatch": (
                        InterviewAppointmentService._provider_time_warning(
                            provider_start_at=provider_start_at,
                            provider_end_at=provider_end_at,
                            brainrh_start_at=record.start_at,
                            brainrh_end_at=record.end_at,
                        )
                        is not None
                        if provider_start_at or provider_end_at
                        else existing_calcom.get("provider_time_mismatch")
                    ),
                },
            }

            if trigger == "BOOKING_CANCELLED":
                record.artifact_data = {
                    **(record.artifact_data or {}),
                    "calcom": {
                        **InterviewAppointmentService._calcom_artifact_dict(record.artifact_data),
                        "status": "cancelled_by_provider",
                    },
                }
            elif trigger in {"BOOKING_CREATED", "BOOKING_RESCHEDULED"}:
                record.artifact_data = {
                    **(record.artifact_data or {}),
                    "calcom": {
                        **InterviewAppointmentService._calcom_artifact_dict(record.artifact_data),
                        "status": "accepted",
                    },
                }
            elif trigger == "MEETING_STARTED":
                record.status = InterviewAppointmentStatus.waiting_candidate.value
                record.active_slot = InterviewAppointmentService._active_slot_for_status(
                    record.interview_sheet_id,
                    record.status,
                )
            elif trigger == "MEETING_ENDED":
                if record.candidate_detected_at is None and record.status in {
                    InterviewAppointmentStatus.scheduled.value,
                    InterviewAppointmentStatus.waiting_candidate.value,
                }:
                    record.status = InterviewAppointmentStatus.no_show.value
                    record.active_slot = None
                    record.completed_at = utc_now()
                elif record.status != InterviewAppointmentStatus.completed.value:
                    record.status = InterviewAppointmentStatus.wrapping_up.value
                    record.active_slot = InterviewAppointmentService._active_slot_for_status(
                        record.interview_sheet_id,
                        record.status,
                    )
            elif trigger in {"RECORDING_READY", "TRANSCRIPTION_READY", "TRANSCRIPT_READY"}:
                record.artifact_data = {
                    **(record.artifact_data or {}),
                    "last_calcom_artifact_event": trigger,
                    "last_calcom_artifact_payload": booking_payload,
                }

            record.updated_at = utc_now()
            session.add(record)
            session.commit()
            session.refresh(record)
            record_dict = InterviewAppointmentService._to_dict(record)

        if trigger in {"BOOKING_CREATED", "BOOKING_RESCHEDULED", "MEETING_STARTED", "MEETING_ENDED"}:
            InterviewAppointmentService._sync_sheet_scheduling_from_appointment(record_dict)

        return record_dict

    @staticmethod
    def worker_realtime_config(appointment_id: str) -> dict[str, Any]:
        appointment = InterviewAppointmentService.get(appointment_id)
        if not appointment.get("realtime_interview_id"):
            raise ValueError("Aucune session IA pour cet entretien recruteur.")
        session_config = RealtimeInterviewService.build_realtime_session_config(
            appointment["realtime_interview_id"]
        )
        return {
            "appointmentId": appointment_id,
            "realtimeInterviewId": appointment["realtime_interview_id"],
            "session": session_config,
        }

    @staticmethod
    def _find_id_for_calcom_payload(booking_payload: dict[str, Any]) -> str | None:
        booking_uid = booking_payload.get("uid") or booking_payload.get("bookingUid")
        metadata = booking_payload.get("metadata") if isinstance(booking_payload.get("metadata"), dict) else {}
        appointment_id = metadata.get("appointmentId") or metadata.get("brainrhAppointmentId")

        with get_session() as session:
            if appointment_id:
                by_id = session.get(InterviewAppointmentDB, str(appointment_id))
                if by_id:
                    return by_id.id
            if booking_uid:
                stmt = select(InterviewAppointmentDB).where(
                    InterviewAppointmentDB.calcom_booking_uid == str(booking_uid)
                )
                found = session.exec(stmt).first()
                return found.id if found else None
        return None

    @staticmethod
    def _build_calcom_booking_payload(
        *,
        appointment_id: str,
        sheet_id: str,
        realtime_interview_id: str,
        start_at: datetime,
        payload: InterviewAppointmentCreateRequest,
        candidate_name: str,
        candidate_email: str,
        event_reference: dict[str, Any],
    ) -> dict[str, Any]:
        notes = DISCLOSURE_TEXT
        if payload.scheduler_notes:
            notes = f"{DISCLOSURE_TEXT}\n\n{payload.scheduler_notes.strip()}"

        metadata = {
            **payload.extra_metadata,
            "source": "brainrh",
            "appointmentId": appointment_id,
            "sheetId": sheet_id,
            "realtimeId": realtime_interview_id,
            "aiInterviewer": AI_INTERVIEWER_NAME,
        }
        settings = get_calcom_settings()

        return {
            "start": InterviewAppointmentService._iso_z(start_at),
            "attendee": {
                "name": candidate_name,
                "email": candidate_email,
                "timeZone": payload.candidate_timezone,
                "language": payload.language_hint.value if payload.language_hint.value != "auto" else "fr",
            },
            "guests": [],
            "bookingFieldsResponses": {
                **payload.booking_fields_responses,
                "notes": notes,
                "brainrhDisclosure": DISCLOSURE_TEXT,
            },
            "metadata": {key: str(value)[:500] for key, value in metadata.items() if value is not None},
            "allowConflicts": settings.allow_conflicts,
            "allowBookingOutOfBounds": settings.allow_booking_out_of_bounds,
            **event_reference,
        }

    @staticmethod
    def _ensure_cal_video_recording(client: CalcomClient, event_reference: dict[str, Any]) -> dict[str, Any]:
        ensure_recording = getattr(client, "ensure_cal_video_recording", None)
        if not callable(ensure_recording):
            return {"requested": False, "reason": "client does not support Cal Video recording setup"}

        try:
            return ensure_recording(event_reference)
        except Exception as exc:
            return {
                "requested": True,
                "error": f"Cal.com recording setup warning: {exc}",
            }

    @staticmethod
    def _load_sheet(sheet_id: str) -> tuple[InterviewSheetDB, dict[str, Any]]:
        with get_session() as session:
            sheet = session.get(InterviewSheetDB, sheet_id)
            if not sheet:
                raise ValueError(f"Fiche d'entretien {sheet_id} introuvable")
            sheet_copy = InterviewSheetDB.model_validate(sheet)

        data = FileStorage.load_json(sheet_copy.json_path)
        return sheet_copy, data

    @staticmethod
    def _write_sheet_scheduling(
        sheet: InterviewSheetDB,
        sheet_data: dict[str, Any],
        *,
        appointment_id: str,
        start_at: datetime,
        end_at: datetime,
        video_url: str | None,
        notes: str | None,
        booking_uid: str | None = None,
        booking_status: str | None = None,
    ) -> None:
        scheduling = sheet_data.get("scheduling") if isinstance(sheet_data.get("scheduling"), dict) else {}
        scheduling = {
            **scheduling,
            "scheduled_at": InterviewAppointmentService._iso_z(start_at),
            "end_at": InterviewAppointmentService._iso_z(end_at),
            "location": video_url,
            "interviewer": AI_INTERVIEWER_NAME,
            "notes": notes,
            "appointment_id": appointment_id,
            "provider": "cal.com",
            "status": booking_status,
            "cancelled_at": None,
            "disclosure": DISCLOSURE_TEXT,
            "booking_uid": booking_uid,
            "booking_status": booking_status,
            "meeting_url": video_url,
            "provider_booking": {
                "appointment_id": appointment_id,
                "booking_uid": booking_uid,
                "booking_status": booking_status,
                "meeting_url": video_url,
            },
        }
        InterviewAppointmentService._persist_sheet_interview(
            sheet.id,
            {
                "appointment_id": appointment_id,
                "interview_mode": InterviewMode.ai.value,
                "title": None,
                "status": booking_status,
                "start_at": InterviewAppointmentService._iso_z(start_at),
                "end_at": InterviewAppointmentService._iso_z(end_at),
                "interviewer": AI_INTERVIEWER_NAME,
                "meeting_format": "video",
                "meeting_url": video_url,
                "location": None,
                "provider": "cal.com",
            },
            scheduling_updates=scheduling,
            status="in_progress",
        )

    @staticmethod
    def _sync_sheet_scheduling_from_appointment(
        appointment: dict[str, Any],
        *,
        notes: str | None = None,
        mark_in_progress: bool = False,
    ) -> None:
        if appointment.get("interview_mode") == InterviewMode.human.value:
            InterviewAppointmentService._sync_human_sheet_scheduling(
                appointment,
                notes=notes,
                mark_in_progress=mark_in_progress,
            )
            return

        sheet_id = appointment["interview_sheet_id"]
        with get_session() as session:
            sheet = session.get(InterviewSheetDB, sheet_id)
            if not sheet:
                return
            sheet_copy = InterviewSheetDB.model_validate(sheet)

        sheet_data = FileStorage.load_json(sheet_copy.json_path)
        scheduling = sheet_data.get("scheduling") if isinstance(sheet_data.get("scheduling"), dict) else {}
        existing_provider_artifacts = scheduling.get("provider_artifacts")
        scheduling = {
            **scheduling,
            "scheduled_at": appointment["start_at"],
            "end_at": appointment["end_at"],
            "location": appointment.get("calcom_video_url") or scheduling.get("location"),
            "interviewer": appointment.get("ai_interviewer_name") or AI_INTERVIEWER_NAME,
            "appointment_id": appointment["id"],
            "provider": appointment.get("provider") or "cal.com",
            "status": appointment["status"],
            "booking_uid": appointment.get("calcom_booking_uid"),
            "booking_status": appointment["status"],
            "meeting_url": appointment.get("calcom_video_url") or scheduling.get("meeting_url"),
            "provider_booking": {
                "appointment_id": appointment["id"],
                "booking_uid": appointment.get("calcom_booking_uid"),
                "booking_status": appointment["status"],
                "meeting_url": appointment.get("calcom_video_url") or scheduling.get("meeting_url"),
            },
            "provider_artifacts": InterviewAppointmentService.provider_artifacts_from_appointment(
                appointment,
                existing_provider_artifacts,
            ),
            "disclosure": scheduling.get("disclosure") or DISCLOSURE_TEXT,
        }
        if appointment["status"] == InterviewAppointmentStatus.cancelled.value:
            scheduling["cancelled_at"] = appointment.get("cancelled_at")

        InterviewAppointmentService._persist_sheet_interview(
            sheet_id,
            InterviewAppointmentService._sheet_interview_entry(appointment),
            scheduling_updates=scheduling,
        )

    @staticmethod
    def _sync_human_sheet_scheduling(
        appointment: dict[str, Any],
        *,
        notes: str | None,
        mark_in_progress: bool,
    ) -> None:
        """Un entretien recruteur n'apparaît que dans la liste des entretiens de la fiche."""
        entry = InterviewAppointmentService._sheet_interview_entry(appointment)
        if mark_in_progress:
            entry["notes"] = notes
        InterviewAppointmentService._persist_sheet_interview(
            appointment["interview_sheet_id"],
            entry,
            status="in_progress" if mark_in_progress else None,
        )

    @staticmethod
    def _sheet_interview_entry(appointment: dict[str, Any]) -> dict[str, Any]:
        human = appointment.get("interview_mode") == InterviewMode.human.value
        return {
            "appointment_id": appointment["id"],
            "interview_mode": appointment.get("interview_mode") or InterviewMode.ai.value,
            "title": appointment.get("title"),
            "status": appointment["status"],
            "start_at": appointment["start_at"],
            "end_at": appointment["end_at"],
            "interviewer": appointment.get("interviewer_name") if human else appointment.get("ai_interviewer_name"),
            "meeting_format": appointment.get("meeting_format") if human else "video",
            "meeting_url": appointment.get("meeting_url") if human else appointment.get("calcom_video_url"),
            "location": appointment.get("meeting_location") if human else None,
            "provider": appointment.get("provider"),
        }

    @staticmethod
    def _persist_sheet_interview(
        sheet_id: str,
        entry: dict[str, Any],
        *,
        scheduling_updates: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> None:
        """Met à jour l'entretien dans ``data.interviews`` (tous les entretiens du candidat)."""
        loaded = InterviewSheetService.load_sheet_payload(sheet_id)
        current_data = loaded[1] if loaded else {}
        interviews: list[dict[str, Any]] = []
        previous: dict[str, Any] = {}
        for item in current_data.get("interviews") or []:
            if not isinstance(item, dict):
                continue
            if item.get("appointment_id") == entry["appointment_id"]:
                previous = item
            else:
                interviews.append(item)
        interviews.append({**previous, **{key: value for key, value in entry.items() if key != "notes" or value}})
        interviews.sort(key=lambda item: str(item.get("start_at") or ""))
        InterviewSheetService.merge_and_persist(
            sheet_id,
            field_updates={"interviews": interviews},
            scheduling_updates=scheduling_updates,
            status=status,
        )

    @staticmethod
    def _mark_creation_failed(appointment_id: str, *, error: str) -> None:
        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                return
            record.status = InterviewAppointmentStatus.failed.value
            record.active_slot = None
            record.last_error = error
            record.updated_at = utc_now()
            session.add(record)
            session.commit()

    @staticmethod
    def _mark_provider_error(appointment_id: str, *, error: str) -> dict[str, Any]:
        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                raise InterviewAppointmentNotFoundError(f"Appointment {appointment_id} introuvable")
            record.last_error = error
            record.artifact_data = {
                **(record.artifact_data or {}),
                "calcom": {
                    "status": "failed",
                    "error": error,
                    "failed_at": utc_now().isoformat(),
                },
            }
            record.updated_at = utc_now()
            session.add(record)
            session.commit()
            session.refresh(record)
            return InterviewAppointmentService._to_dict(record)

    @staticmethod
    def _calcom_artifact_state(
        *,
        status: str,
        booking_uid: str,
        video_url: str | None,
        provider_start_at: datetime | None,
        provider_end_at: datetime | None,
        brainrh_start_at: datetime,
        brainrh_end_at: datetime,
        recording_setup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "status": status,
            "booking_uid": booking_uid,
            "video_url": video_url,
            "recording_setup": recording_setup or {},
            "provider_start_at": (
                InterviewAppointmentService._iso_z(provider_start_at)
                if provider_start_at
                else None
            ),
            "provider_end_at": (
                InterviewAppointmentService._iso_z(provider_end_at)
                if provider_end_at
                else None
            ),
            "brainrh_start_at": InterviewAppointmentService._iso_z(brainrh_start_at),
            "brainrh_end_at": InterviewAppointmentService._iso_z(brainrh_end_at),
            "provider_time_mismatch": InterviewAppointmentService._provider_time_warning(
                provider_start_at=provider_start_at,
                provider_end_at=provider_end_at,
                brainrh_start_at=brainrh_start_at,
                brainrh_end_at=brainrh_end_at,
            )
            is not None,
        }

    @staticmethod
    def _calcom_artifact_dict(artifact_data: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(artifact_data, dict):
            return {}
        calcom = artifact_data.get("calcom")
        return calcom if isinstance(calcom, dict) else {}

    @staticmethod
    def _provider_time_warning(
        *,
        provider_start_at: datetime | None,
        provider_end_at: datetime | None,
        brainrh_start_at: datetime,
        brainrh_end_at: datetime,
    ) -> str | None:
        provider_start = InterviewAppointmentService._as_utc(provider_start_at) if provider_start_at else None
        provider_end = InterviewAppointmentService._as_utc(provider_end_at) if provider_end_at else None
        brainrh_start = InterviewAppointmentService._as_utc(brainrh_start_at)
        brainrh_end = InterviewAppointmentService._as_utc(brainrh_end_at)
        if provider_start == brainrh_start and provider_end == brainrh_end:
            return None
        return (
            "Cal.com returned provider times that differ from BrainRH schedule; "
            "BrainRH schedule remains authoritative."
        )

    @staticmethod
    def _combine_warnings(*warnings: str | None) -> str | None:
        kept = [warning for warning in warnings if warning]
        return " | ".join(kept) if kept else None

    def _resolve_registry_setup_for_sheet(
        sheet: InterviewSheetDB,
        sheet_data: dict[str, Any],
        payload: InterviewAppointmentCreateRequest,
    ) -> dict[str, Any]:
        del payload
        interview_sheet = {
            "id": sheet.id,
            "candidate_id": sheet.candidate_id,
            "job_id": sheet.job_id,
            "matching_id": sheet.matching_id,
            "interviewer_id": sheet.interviewer_id,
            "status": sheet.status,
            "data": sheet_data,
            "json_path": sheet.json_path,
        }
        try:
            setup_context = RealtimeInterviewRegistryService.resolve_interview_sheet_context(interview_sheet)
        except RealtimeInterviewRegistryError as exc:
            raise ValueError(
                "Impossible de créer un appointment Cal.com sans contexte registry canonique: "
                f"{exc}"
            ) from exc

        registry_context = setup_context.get("registryContext")
        if hasattr(registry_context, "model_dump"):
            setup_context = {
                **setup_context,
                "registryContext": registry_context.model_dump(mode="json"),
            }
        return setup_context

    @staticmethod
    def _resolve_candidate_name(
        sheet: InterviewSheetDB,
        sheet_data: dict[str, Any],
        payload: InterviewAppointmentCreateRequest,
    ) -> str:
        if payload.candidate_name and payload.candidate_name.strip():
            return payload.candidate_name.strip()

        identity = sheet_data.get("identite") if isinstance(sheet_data.get("identite"), dict) else {}
        for key in ("nom_complet", "name"):
            value = identity.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        first_name = identity.get("prenom")
        last_name = identity.get("nom")
        full_name = " ".join(part.strip() for part in (first_name, last_name) if isinstance(part, str) and part.strip())
        return full_name or sheet.candidate_id

    @staticmethod
    def _resolve_candidate_email(
        sheet_data: dict[str, Any],
        payload: InterviewAppointmentCreateRequest,
    ) -> str | None:
        if payload.candidate_email and payload.candidate_email.strip():
            return payload.candidate_email.strip()
        identity = sheet_data.get("identite") if isinstance(sheet_data.get("identite"), dict) else {}
        value = identity.get("email")
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _build_candidate_context(sheet_data: dict[str, Any]) -> str:
        fields = {
            "identite": sheet_data.get("identite"),
            "resume": sheet_data.get("resume"),
            "strengths": sheet_data.get("strengths"),
            "concerns": sheet_data.get("concerns"),
            "questions": sheet_data.get("questions"),
            "evaluation_grid": sheet_data.get("evaluation_grid"),
        }
        return json.dumps(fields, ensure_ascii=False, default=str)[:12000]

    @staticmethod
    def _build_job_context(sheet: InterviewSheetDB, sheet_data: dict[str, Any]) -> str:
        fields = {
            "job_id": sheet.job_id,
            "matching_id": sheet.matching_id,
            "recommendation": sheet_data.get("recommendation"),
            "role": sheet_data.get("role") or sheet_data.get("poste") or sheet_data.get("job"),
        }
        return json.dumps(fields, ensure_ascii=False, default=str)[:8000]

    @staticmethod
    def _status_for_worker_event(event_name: str, current_status: str) -> str:
        mapping = {
            "joined": InterviewAppointmentStatus.waiting_candidate.value,
            "candidate_detected": InterviewAppointmentStatus.in_progress.value,
            "candidate_left": InterviewAppointmentStatus.paused.value,
            "resumed": InterviewAppointmentStatus.in_progress.value,
            "wrapping_up": InterviewAppointmentStatus.wrapping_up.value,
            "completed": InterviewAppointmentStatus.completed.value,
            "no_show": InterviewAppointmentStatus.no_show.value,
            "failed": InterviewAppointmentStatus.failed.value,
        }
        return mapping.get(event_name, current_status)

    @staticmethod
    def _active_slot_for_status(sheet_id: str, status: str) -> str | None:
        return sheet_id if status in InterviewAppointmentService.ACTIVE_STATUSES else None

    @staticmethod
    def _try_calcom_artifact(callback, errors: list[str]) -> list[Any] | None:
        try:
            return callback()
        except (CalcomAPIError, CalcomConfigurationError) as exc:
            errors.append(str(exc))
            return None

    @staticmethod
    def _with_recording_access_urls(
        appointment_id: str,
        recordings: list[Any],
        *,
        include_private: bool = False,
    ) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for item in recordings or []:
            if not isinstance(item, dict):
                continue
            recording = dict(item)
            if not include_private:
                for field in PRIVATE_RECORDING_FIELDS:
                    recording.pop(field, None)
            if recording.get("storage_key") and recording.get("id"):
                recording_id = quote(str(recording["id"]), safe="")
                base_url = f"/api/v1/interview-appointments/{appointment_id}/recordings/{recording_id}"
                recording.setdefault("view_url", base_url)
                recording.setdefault("download_url", f"{base_url}?download=1")
            elif recording.get("provider") == "brainrh_worker_local" and recording.get("id"):
                recording_id = quote(str(recording["id"]), safe="")
                base_url = f"/api/v1/interview-appointments/{appointment_id}/recordings/{recording_id}"
                recording.setdefault("view_url", base_url)
                recording.setdefault("download_url", f"{base_url}?download=1")
            enriched.append(recording)
        return enriched

    @staticmethod
    def provider_artifacts_from_appointment(
        appointment: dict[str, Any],
        existing_artifacts: Any = None,
    ) -> dict[str, Any]:
        artifacts = dict(existing_artifacts) if isinstance(existing_artifacts, dict) else {}
        artifacts.update(
            {
                "booking_references": appointment.get("booking_references") or [],
                "conferencing_sessions": appointment.get("conferencing_sessions") or [],
                "recordings": appointment.get("recordings") or [],
                "transcripts": appointment.get("transcripts") or [],
            }
        )
        return artifacts

    @staticmethod
    def _artifact_data_with_recording_urls(appointment_id: str, artifact_data: dict[str, Any] | None) -> dict[str, Any]:
        data = dict(artifact_data or {})
        local_recording = data.get("local_recording")
        if isinstance(local_recording, dict):
            data["local_recording"] = InterviewAppointmentService._with_recording_access_urls(
                appointment_id,
                [local_recording],
            )[0]
        return data

    @staticmethod
    def resolve_recording_download(
        appointment_id: str,
        recording_id: str,
        *,
        disposition: str = "attachment",
    ) -> dict[str, Any]:
        with get_session() as session:
            record = session.get(InterviewAppointmentDB, appointment_id)
            if not record:
                raise InterviewAppointmentNotFoundError(f"Appointment {appointment_id} introuvable")
            recordings = list(record.recordings or [])
            local_recording = (record.artifact_data or {}).get("local_recording")
            if isinstance(local_recording, dict):
                recordings.append(local_recording)

        artifact = InterviewAppointmentService._find_recording_artifact(recordings, recording_id)
        if not artifact:
            raise FileNotFoundError(f"Recording {recording_id} introuvable")

        if artifact.get("storage_key"):
            filename = InterviewAppointmentService._recording_filename(artifact)
            signed_url = FileStorage.generate_download_url(
                artifact["storage_key"],
                filename=filename,
                disposition=disposition,
            )
            if not signed_url:
                raise ValueError("Le backend storage actif ne supporte pas les URLs signees")
            return {
                "kind": "redirect",
                "url": signed_url,
                "artifact": InterviewAppointmentService._with_recording_access_urls(appointment_id, [artifact])[0],
            }

        if artifact.get("provider") != "brainrh_worker_local":
            raise ValueError("Ce recording n'est pas servi par le stockage local BrainRH")

        saw_allowed_path = False
        for candidate_path in InterviewAppointmentService._local_recording_path_candidates(artifact):
            resolved = candidate_path.resolve()
            if not InterviewAppointmentService._is_allowed_local_recording_path(resolved):
                continue
            saw_allowed_path = True
            if resolved.is_file():
                return {
                    "kind": "local",
                    "path": resolved,
                    "artifact": InterviewAppointmentService._with_recording_access_urls(appointment_id, [artifact])[0],
                }
        if saw_allowed_path:
            raise FileNotFoundError(f"Fichier recording introuvable: {recording_id}")
        raise ValueError("Chemin recording local hors scope")

    @staticmethod
    def _find_recording_artifact(recordings: list[Any], recording_id: str) -> dict[str, Any] | None:
        expected = str(recording_id).strip()
        for item in recordings:
            if not isinstance(item, dict):
                continue
            identifiers = {
                str(item.get("id") or "").strip(),
                str(item.get("uid") or "").strip(),
                Path(str(item.get("path") or "")).stem,
                Path(str(item.get("container_path") or "")).stem,
                Path(str(item.get("storage_key") or "")).stem,
            }
            if expected in identifiers:
                return dict(item)
        return None

    @staticmethod
    def _recording_filename(artifact: dict[str, Any]) -> str:
        for candidate in (
            artifact.get("name"),
            artifact.get("title"),
            artifact.get("path"),
            artifact.get("container_path"),
            artifact.get("storage_key"),
        ):
            if candidate:
                return Path(str(candidate)).name
        return f"{artifact.get('id') or 'recording'}.mp4"

    @staticmethod
    def _local_recording_path_candidates(artifact: dict[str, Any]) -> list[Path]:
        candidates: list[Path] = []
        for key in ("path", "container_path"):
            raw_path = str(artifact.get(key) or "").strip()
            if not raw_path:
                continue
            path = Path(raw_path)
            if path.is_absolute():
                candidates.append(path)
            else:
                candidates.append((PROJECT_ROOT / path).resolve())
            if key == "container_path":
                for root in InterviewAppointmentService._allowed_local_recording_roots():
                    candidates.append(root / path.name)
        return candidates

    @staticmethod
    def _allowed_local_recording_roots() -> list[Path]:
        raw_roots = [
            os.getenv("CAL_VIDEO_LOCAL_RECORDING_HOST_DIR", ""),
            os.getenv("CAL_VIDEO_WORKER_RECORDING_DIR", ""),
        ]
        roots = [
            PROJECT_ROOT / "logs" / "cal_video_recordings",
            STORAGE_ROOT / "logs" / "cal_video_recordings",
        ]
        for raw_root in raw_roots:
            cleaned = raw_root.strip()
            if not cleaned:
                continue
            path = Path(cleaned)
            roots.append(path if path.is_absolute() else PROJECT_ROOT / path)

        resolved_roots: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            resolved = root.resolve()
            key = str(resolved)
            if key not in seen:
                seen.add(key)
                resolved_roots.append(resolved)
        return resolved_roots

    @staticmethod
    def _is_allowed_local_recording_path(path: Path) -> bool:
        for root in InterviewAppointmentService._allowed_local_recording_roots():
            try:
                path.relative_to(root)
                return True
            except ValueError:
                continue
        return False

    @staticmethod
    def _finalize_realtime_safely(
        realtime_interview_id: str,
        *,
        appointment_id: str | None = None,
    ) -> None:
        try:
            RealtimeInterviewService.finalize_interview(
                realtime_interview_id,
                appointment_id=appointment_id,
            )
        except Exception:
            return

    @staticmethod
    def _resolve_end_at(start_at: datetime, payload: InterviewAppointmentCreateRequest) -> datetime:
        end_at = InterviewAppointmentService._as_utc(payload.end_at) if payload.end_at else start_at + timedelta(
            minutes=payload.duration_minutes
        )
        if end_at <= start_at:
            raise ValueError("end_at doit être après start_at")
        return end_at

    @staticmethod
    def _parse_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            return InterviewAppointmentService._as_utc(value)
        if not isinstance(value, str):
            raise ValueError("Datetime Cal.com invalide")
        normalized = value.replace("Z", "+00:00")
        return InterviewAppointmentService._as_utc(datetime.fromisoformat(normalized))

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _iso_z(value: datetime) -> str:
        return InterviewAppointmentService._as_utc(value).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _to_dict(record: InterviewAppointmentDB) -> dict[str, Any]:
        recordings = InterviewAppointmentService._with_recording_access_urls(record.id, record.recordings or [])
        artifact_data = InterviewAppointmentService._artifact_data_with_recording_urls(record.id, record.artifact_data)
        return {
            "id": record.id,
            "interview_sheet_id": record.interview_sheet_id,
            "realtime_interview_id": record.realtime_interview_id,
            "provider": record.provider,
            "status": record.status,
            "active_slot": record.active_slot,
            "start_at": InterviewAppointmentService._iso_z(record.start_at),
            "end_at": InterviewAppointmentService._iso_z(record.end_at),
            "joined_at": InterviewAppointmentService._iso_z(record.joined_at) if record.joined_at else None,
            "candidate_detected_at": InterviewAppointmentService._iso_z(record.candidate_detected_at)
            if record.candidate_detected_at
            else None,
            "candidate_left_at": InterviewAppointmentService._iso_z(record.candidate_left_at)
            if record.candidate_left_at
            else None,
            "completed_at": InterviewAppointmentService._iso_z(record.completed_at) if record.completed_at else None,
            "cancelled_at": InterviewAppointmentService._iso_z(record.cancelled_at) if record.cancelled_at else None,
            "candidate_name": record.candidate_name,
            "candidate_email": record.candidate_email,
            "candidate_timezone": record.candidate_timezone,
            "ai_interviewer_name": record.ai_interviewer_name,
            "interview_mode": record.interview_mode or InterviewMode.ai.value,
            "title": record.title,
            "interviewer_name": record.interviewer_name,
            "interviewer_email": record.interviewer_email,
            "meeting_format": record.meeting_format,
            "meeting_url": record.meeting_url,
            "meeting_location": record.meeting_location,
            "calcom_booking_uid": record.calcom_booking_uid,
            "calcom_booking_id": record.calcom_booking_id,
            "calcom_event_type_id": record.calcom_event_type_id,
            "calcom_event_type_slug": record.calcom_event_type_slug,
            "calcom_video_url": record.calcom_video_url,
            "booking": record.booking_data,
            "booking_references": record.booking_references,
            "conferencing_sessions": record.conferencing_sessions,
            "recordings": recordings,
            "transcripts": record.transcripts,
            "worker_state": record.worker_state,
            "artifact_data": artifact_data,
            "last_error": record.last_error,
            "created_at": InterviewAppointmentService._iso_z(record.created_at),
            "updated_at": InterviewAppointmentService._iso_z(record.updated_at),
        }


def calcom_webhook_secret() -> str:
    return get_calcom_settings().webhook_secret


def worker_event_secret() -> str:
    import os

    return os.getenv("BRAINRH_WORKER_EVENT_SECRET", "").strip()
