from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any
import uuid

import requests
from sqlalchemy import exists, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from brainrh.database import get_session
from brainrh.models.interview_appointment import InterviewAppointmentDB
from brainrh.models.realtime_interview import (
    InterviewPlan,
    InterviewRuntimeState,
    InterviewStatus,
    NotableSignal,
    NotableSignalType,
    RealtimeInterviewRegistryContext,
    RealtimeInterviewDB,
    RealtimeInterviewPreparationState,
    RealtimeInterviewSetupRequest,
    RealtimeToolCallRequest,
    TemporaryBranch,
    TranscriptSpeaker,
    TranscriptTurn,
    utc_now,
)
from brainrh.services.interview_sheet_service import InterviewSheetService
from brainrh.services.realtime_interview_planner import RealtimeInterviewPlanner
from brainrh.services.realtime_interview_registry_service import (
    RealtimeInterviewRegistryError,
    RealtimeInterviewRegistryService,
)
from brainrh.services.llm_settings_service import resolve_llm_selection


logger = logging.getLogger(__name__)


class RealtimeInterviewNotFoundError(Exception):
    pass


class RealtimeInterviewToolError(Exception):
    pass


class RealtimeInterviewPreparationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        interview_id: str | None = None,
        preparation_state: str = RealtimeInterviewPreparationState.pending.value,
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.interview_id = interview_id
        self.preparation_state = preparation_state


class RealtimeInterviewService:
    DEFAULT_REALTIME_MODEL = "gpt-realtime-2.1-mini"
    DEFAULT_REALTIME_VOICE = "marin"
    TRANSCRIPTION_MODEL = "gpt-4o-mini-transcribe"
    CLIENT_SECRET_URL = "https://api.openai.com/v1/realtime/client_secrets"
    PREPARATION_LEASE_SECONDS = 30
    PREPARATION_WAIT_SECONDS = 0.25

    @staticmethod
    def create_interview_session(
        payload: RealtimeInterviewSetupRequest,
        *,
        owner_user_id: str,
    ) -> dict[str, Any]:
        setup_context = RealtimeInterviewService._resolve_setup_context(payload)
        registry_context = setup_context["registryContext"]
        sheet_id = registry_context.interviewSheetId if registry_context else None
        if payload.mode and payload.mode.value == "registry" and sheet_id:
            return RealtimeInterviewService._get_or_create_sheet_interview(
                payload,
                setup_context=setup_context,
                sheet_id=sheet_id,
                owner_user_id=owner_user_id,
            )

        interview_id = str(uuid.uuid4())
        plan = RealtimeInterviewPlanner.build_plan(
            candidate_name=setup_context["candidateName"],
            cv_text=setup_context["cvText"],
            job_description_text=setup_context["jobDescriptionText"],
            language_hint=payload.languageHint.value,
            ai_plan_instructions=setup_context.get("aiPlanInstructions", ""),
        )
        plan.registryContext = setup_context["registryContext"]
        runtime_state = RealtimeInterviewPlanner.build_initial_runtime_state(interview_id, plan)

        with get_session() as session:
            record = RealtimeInterviewDB(
                id=interview_id,
                owner_user_id=owner_user_id,
                interview_sheet_id=sheet_id,
                project_id=registry_context.projectId if registry_context else None,
                active_sheet_slot=sheet_id,
                preparation_state=RealtimeInterviewPreparationState.ready.value,
                candidate_name=setup_context["candidateName"],
                language_hint=plan.languageHint.value,
                status=InterviewStatus.ready.value,
                cv_text=setup_context["cvText"],
                job_description_text=setup_context["jobDescriptionText"],
                plan_data=plan.model_dump(mode="json"),
                runtime_state=runtime_state.model_dump(mode="json"),
            )
            session.add(record)
            session.commit()
            session.refresh(record)

        logger.info("Realtime interview created: %s", interview_id)
        return {
            "interviewId": interview_id,
            "plan": plan.model_dump(mode="json"),
            "runtimeState": runtime_state.model_dump(mode="json"),
            "registryContext": RealtimeInterviewService._registry_context_payload(plan),
            "preparationState": RealtimeInterviewPreparationState.ready.value,
        }

    @staticmethod
    def get_interview_context(interview_id: str) -> dict[str, Any]:
        with get_session() as session:
            record = RealtimeInterviewService._get_record(session, interview_id, require_prepared=False)
            if record.preparation_state != RealtimeInterviewPreparationState.ready.value:
                return RealtimeInterviewService._preparation_response(record)
            plan = InterviewPlan.model_validate(record.plan_data)
            return {
                "interviewId": record.id,
                "candidateName": record.candidate_name,
                "languageHint": record.language_hint,
                "cvText": record.cv_text,
                "jobDescriptionText": record.job_description_text,
                "plan": plan.model_dump(mode="json"),
                "status": record.status,
                "registryContext": RealtimeInterviewService._registry_context_payload(plan),
                "preparationState": record.preparation_state,
            }

    @staticmethod
    def get_interview_runtime_state(interview_id: str) -> dict[str, Any]:
        with get_session() as session:
            record = RealtimeInterviewService._get_record(session, interview_id)
            state = InterviewRuntimeState.model_validate(record.runtime_state)
            return state.model_dump(mode="json")

    @staticmethod
    def update_interview_plan(interview_id: str, plan_payload: dict[str, Any]) -> dict[str, Any]:
        with get_session() as session:
            record = RealtimeInterviewService._get_record(session, interview_id)
            if record.status != InterviewStatus.ready.value:
                raise ValueError("Le plan ne peut être modifié qu'avant le lancement de l'entretien.")

            current_plan = InterviewPlan.model_validate(record.plan_data)
            next_plan = InterviewPlan.model_validate(plan_payload)
            if not next_plan.stages:
                raise ValueError("Le plan doit contenir au moins une étape.")
            seen_stage_ids: set[str] = set()
            for index, stage in enumerate(next_plan.stages):
                stage_id = stage.id.strip()
                if not stage_id:
                    raise ValueError(f"L'identifiant de l'étape {index + 1} est requis.")
                if stage_id in seen_stage_ids:
                    raise ValueError(f"L'identifiant d'étape '{stage_id}' est dupliqué.")
                seen_stage_ids.add(stage_id)
                stage.id = stage_id

            # The registry linkage stays canonical on the server side.
            next_plan.registryContext = current_plan.registryContext

            state = InterviewRuntimeState.model_validate(record.runtime_state)
            valid_stage_ids = {stage.id for stage in next_plan.stages}
            if state.currentStageId not in valid_stage_ids:
                state.currentStageId = next_plan.stages[0].id
            state.coveredItems = [stage_id for stage_id in state.coveredItems if stage_id in valid_stage_ids]
            now = utc_now()
            update_statement = (
                update(RealtimeInterviewDB)
                .where(
                    RealtimeInterviewDB.id == interview_id,
                    RealtimeInterviewDB.status == InterviewStatus.ready.value,
                )
                .values(
                    plan_data=next_plan.model_dump(mode="json"),
                    runtime_state=state.model_dump(mode="json"),
                    candidate_name=next_plan.candidateName,
                    language_hint=next_plan.languageHint.value,
                    updated_at=now,
                )
            )
            result = session.exec(update_statement)
            if result.rowcount != 1:
                session.rollback()
                refreshed_record = RealtimeInterviewService._get_record(session, interview_id)
                if refreshed_record.status != InterviewStatus.ready.value:
                    raise ValueError("Le plan ne peut être modifié qu'avant le lancement de l'entretien.")
                raise ValueError("Le plan a changé pendant l'édition. Réessayez.")

            session.commit()

            return {
                "interviewId": interview_id,
                "plan": next_plan.model_dump(mode="json"),
                "runtimeState": state.model_dump(mode="json"),
                "registryContext": RealtimeInterviewService._registry_context_payload(next_plan),
            }

    @staticmethod
    def append_transcript_turn(
        interview_id: str,
        *,
        speaker: str,
        text: str,
        ts: str | None = None,
    ) -> dict[str, Any]:
        normalized_speaker = TranscriptSpeaker(speaker)
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Le transcript ne peut pas être vide")
        turn = TranscriptTurn(
            speaker=normalized_speaker,
            text=clean_text,
            ts=ts or utc_now().isoformat(),
        )

        with get_session() as session:
            record = RealtimeInterviewService._get_record(session, interview_id)
            plan = InterviewPlan.model_validate(record.plan_data)
            state = InterviewRuntimeState.model_validate(record.runtime_state)
            duplicate_turn = next(
                (
                    previous
                    for previous in reversed(state.transcriptTurns[-5:])
                    if previous.speaker == normalized_speaker and previous.text.strip() == clean_text
                ),
                None,
            )
            if duplicate_turn:
                turn = duplicate_turn
            else:
                state.transcriptTurns = [*state.transcriptTurns, turn]
            next_status = record.status
            if record.status == InterviewStatus.ready.value:
                next_status = InterviewStatus.in_progress.value
            if not duplicate_turn or next_status != record.status:
                RealtimeInterviewService._persist_runtime_state(
                    session,
                    record,
                    state,
                    status=next_status,
                )
            summary_data = record.summary_data if isinstance(record.summary_data, dict) else {}
            completed_at = record.completed_at.isoformat() if record.completed_at else None

        RealtimeInterviewService._sync_runtime_to_interview_sheet(
            interview_id=interview_id,
            plan=plan,
            state=state,
            summary_data=summary_data,
            realtime_status=next_status,
            completed_at=completed_at,
        )

        return {
            "turn": turn.model_dump(mode="json"),
            "runtimeState": state.model_dump(mode="json"),
        }

    @staticmethod
    def add_notable_signal(
        interview_id: str,
        *,
        signal_type: str,
        text: str,
    ) -> dict[str, Any]:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("Le signal ne peut pas être vide")
        signal = NotableSignal(
            type=NotableSignalType(signal_type),
            text=clean_text,
            createdAt=utc_now().isoformat(),
        )

        with get_session() as session:
            record = RealtimeInterviewService._get_record(session, interview_id)
            state = InterviewRuntimeState.model_validate(record.runtime_state)
            state.notableSignals = [*state.notableSignals, signal]
            RealtimeInterviewService._persist_runtime_state(session, record, state)

        return {
            "signal": signal.model_dump(mode="json"),
            "runtimeState": state.model_dump(mode="json"),
        }

    @staticmethod
    def open_temporary_branch(
        interview_id: str,
        *,
        topic: str,
        reason: str,
        remaining_questions: int = 2,
    ) -> dict[str, Any]:
        clean_topic = topic.strip()
        clean_reason = reason.strip()
        if not clean_topic or not clean_reason:
            raise ValueError("Le topic et la reason de la branche sont requis")
        branch = TemporaryBranch(
            topic=clean_topic,
            reason=clean_reason,
            remainingQuestions=max(1, min(int(remaining_questions), 2)),
        )

        with get_session() as session:
            record = RealtimeInterviewService._get_record(session, interview_id)
            state = InterviewRuntimeState.model_validate(record.runtime_state)
            state.temporaryBranch = branch
            RealtimeInterviewService._persist_runtime_state(session, record, state)

        return {
            "temporaryBranch": branch.model_dump(mode="json"),
            "runtimeState": state.model_dump(mode="json"),
        }

    @staticmethod
    def close_temporary_branch(interview_id: str) -> dict[str, Any]:
        with get_session() as session:
            record = RealtimeInterviewService._get_record(session, interview_id)
            state = InterviewRuntimeState.model_validate(record.runtime_state)
            state.temporaryBranch = None
            RealtimeInterviewService._persist_runtime_state(session, record, state)

        return {"runtimeState": state.model_dump(mode="json")}

    @staticmethod
    def advance_stage(interview_id: str) -> dict[str, Any]:
        with get_session() as session:
            record = RealtimeInterviewService._get_record(session, interview_id)
            plan = InterviewPlan.model_validate(record.plan_data)
            state = InterviewRuntimeState.model_validate(record.runtime_state)

            current_index = RealtimeInterviewService._resolve_stage_index(plan, state.currentStageId)
            current_stage = plan.stages[current_index]

            covered_items = list(state.coveredItems)
            if current_stage.id not in covered_items:
                covered_items.append(current_stage.id)
            state.coveredItems = covered_items
            state.temporaryBranch = None

            if current_index < len(plan.stages) - 1:
                state.currentStageId = plan.stages[current_index + 1].id

            RealtimeInterviewService._persist_runtime_state(
                session,
                record,
                state,
                status=InterviewStatus.in_progress.value,
            )

            return {
                "currentStageId": state.currentStageId,
                "coveredItems": state.coveredItems,
                "runtimeState": state.model_dump(mode="json"),
            }

    @staticmethod
    def finalize_interview(
        interview_id: str,
        *,
        appointment_id: str | None = None,
    ) -> dict[str, Any]:
        with get_session() as session:
            record = RealtimeInterviewService._get_record(session, interview_id)
            plan = InterviewPlan.model_validate(record.plan_data)
            state = InterviewRuntimeState.model_validate(record.runtime_state)
            finalization_conditions = [
                RealtimeInterviewDB.id == interview_id,
                RealtimeInterviewDB.status != InterviewStatus.completed.value,
                RealtimeInterviewDB.updated_at == record.updated_at,
            ]
            if appointment_id:
                appointment = session.get(InterviewAppointmentDB, appointment_id)
                if not appointment or appointment.realtime_interview_id != interview_id:
                    raise ValueError("Appointment incompatible avec la session IA à finaliser")
                finalization_conditions.append(
                    ~exists().where(
                        InterviewAppointmentDB.interview_sheet_id == appointment.interview_sheet_id,
                        InterviewAppointmentDB.active_slot == appointment.interview_sheet_id,
                        InterviewAppointmentDB.id != appointment_id,
                    )
                )
            if record.status == InterviewStatus.completed.value and isinstance(record.summary_data, dict):
                summary = record.summary_data
            else:
                if state.currentStageId and state.currentStageId not in state.coveredItems:
                    state.coveredItems = [*state.coveredItems, state.currentStageId]
                state.temporaryBranch = None
                summary = RealtimeInterviewService._build_summary(plan, state)
                registry_context = RealtimeInterviewService._registry_context_payload(plan)
                if registry_context:
                    summary["registryContext"] = registry_context
                finalized_at = utc_now()
                finalized = session.exec(
                    update(RealtimeInterviewDB)
                    .where(*finalization_conditions)
                    .values(
                        runtime_state=state.model_dump(mode="json"),
                        summary_data=summary,
                        status=InterviewStatus.completed.value,
                        completed_at=finalized_at,
                        active_sheet_slot=None,
                        preparation_state=RealtimeInterviewPreparationState.ready.value,
                        preparation_lease_token=None,
                        preparation_lease_expires_at=None,
                        updated_at=finalized_at,
                    )
                )
                session.commit()
                if finalized.rowcount != 1:
                    record = RealtimeInterviewService._get_record(session, interview_id)
                    if appointment_id and record.status != InterviewStatus.completed.value:
                        return {
                            "interviewId": record.id,
                            "status": record.status,
                            "transcriptTurns": state.model_dump(mode="json")["transcriptTurns"],
                            "notableSignals": state.model_dump(mode="json")["notableSignals"],
                            "summary": record.summary_data or {},
                            "registryContext": RealtimeInterviewService._registry_context_payload(plan),
                            "interviewSheetSync": None,
                            "finalized": False,
                        }
                    summary = record.summary_data if isinstance(record.summary_data, dict) else summary
                    state = InterviewRuntimeState.model_validate(record.runtime_state)
                else:
                    record = RealtimeInterviewService._get_record(session, interview_id)

            registry_context = RealtimeInterviewService._registry_context_payload(plan)
            result = {
                "interviewId": record.id,
                "status": record.status,
                "transcriptTurns": state.model_dump(mode="json")["transcriptTurns"],
                "notableSignals": state.model_dump(mode="json")["notableSignals"],
                "summary": summary,
                "registryContext": registry_context,
            }
            interview_sheet_id = record.interview_sheet_id
            completed_at = record.completed_at

        result["interviewSheetSync"] = RealtimeInterviewService._sync_summary_to_interview_sheet(
            plan,
            summary,
            state,
            interview_id=interview_id,
            interview_sheet_id=interview_sheet_id,
            completed_at=completed_at,
        )
        return result

    @staticmethod
    def execute_tool_calls(
        interview_id: str,
        tool_calls: list[RealtimeToolCallRequest],
        *,
        appointment_id: str | None = None,
    ) -> dict[str, Any]:
        outputs = []
        for tool_call in tool_calls:
            outputs.append(
                {
                    "callId": tool_call.callId,
                    "name": tool_call.name,
                    "output": RealtimeInterviewService.execute_tool_call(
                        interview_id,
                        tool_call.name,
                        tool_call.arguments,
                        appointment_id=appointment_id,
                    ),
                }
            )
        return {"outputs": outputs}

    @staticmethod
    def execute_tool_call(
        interview_id: str,
        name: str,
        arguments: Any,
        *,
        appointment_id: str | None = None,
    ) -> dict[str, Any]:
        args = RealtimeInterviewService._normalize_arguments(arguments)

        if name == "getInterviewContext":
            return RealtimeInterviewService.get_interview_context(interview_id)
        if name == "getInterviewRuntimeState":
            return RealtimeInterviewService.get_interview_runtime_state(interview_id)
        if name == "appendTranscriptTurn":
            return RealtimeInterviewService.append_transcript_turn(
                interview_id,
                speaker=args["speaker"],
                text=args["text"],
                ts=args.get("ts"),
            )
        if name == "addNotableSignal":
            return RealtimeInterviewService.add_notable_signal(
                interview_id,
                signal_type=args["type"],
                text=args["text"],
            )
        if name == "openTemporaryBranch":
            return RealtimeInterviewService.open_temporary_branch(
                interview_id,
                topic=args["topic"],
                reason=args["reason"],
                remaining_questions=args.get("remainingQuestions", 2),
            )
        if name == "closeTemporaryBranch":
            return RealtimeInterviewService.close_temporary_branch(interview_id)
        if name == "advanceStage":
            return RealtimeInterviewService.advance_stage(interview_id)
        if name == "finalizeInterview":
            return RealtimeInterviewService.finalize_interview(
                interview_id,
                appointment_id=appointment_id,
            )
        raise RealtimeInterviewToolError(f"Unsupported tool call: {name}")

    @staticmethod
    def build_realtime_session_config(interview_id: str) -> dict[str, Any]:
        with get_session() as session:
            record = RealtimeInterviewService._get_record(session, interview_id)
            plan = InterviewPlan.model_validate(record.plan_data)
            state = InterviewRuntimeState.model_validate(record.runtime_state)

        return RealtimeInterviewService._build_session_config_from_plan_and_state(plan, state)

    @staticmethod
    def _build_session_config_from_plan_and_state(
        plan: InterviewPlan,
        state: InterviewRuntimeState,
    ) -> dict[str, Any]:

        transcription: dict[str, Any] = {
            "model": RealtimeInterviewService.TRANSCRIPTION_MODEL,
        }
        if plan.languageHint.value != "auto":
            transcription["language"] = plan.languageHint.value

        return {
            "type": "realtime",
            "model": RealtimeInterviewService._realtime_model(),
            "instructions": RealtimeInterviewService._build_system_instructions(plan, state),
            "output_modalities": ["audio"],
            "audio": {
                "input": {
                    "noise_reduction": {"type": "near_field"},
                    "transcription": transcription,
                    "turn_detection": RealtimeInterviewService._turn_detection_config(),
                },
                "output": {
                    "voice": RealtimeInterviewService._realtime_voice(),
                },
            },
            "include": ["item.input_audio_transcription.logprobs"],
            "tools": RealtimeInterviewService.build_tool_definitions(),
            "tool_choice": "auto",
        }

    @staticmethod
    def preview_realtime_prompt(interview_id: str) -> dict[str, Any]:
        session_config = RealtimeInterviewService.build_realtime_session_config(interview_id)
        audio_config = session_config.get("audio") if isinstance(session_config.get("audio"), dict) else {}
        input_config = audio_config.get("input") if isinstance(audio_config.get("input"), dict) else {}
        output_config = audio_config.get("output") if isinstance(audio_config.get("output"), dict) else {}
        return {
            "interviewId": interview_id,
            "model": session_config["model"],
            "voice": output_config.get("voice"),
            "turnDetection": input_config.get("turn_detection"),
            "transcription": input_config.get("transcription"),
        }

    @staticmethod
    def mint_realtime_client_secret(interview_id: str) -> dict[str, Any]:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY non trouvée dans l'environnement")

        claimed_ready = False
        with get_session() as session:
            record = RealtimeInterviewService._get_record(session, interview_id)
            if record.status == InterviewStatus.completed.value:
                raise RuntimeError("Impossible de relancer un entretien realtime déjà finalisé")

            if record.status == InterviewStatus.ready.value:
                claim_statement = (
                    update(RealtimeInterviewDB)
                    .where(
                        RealtimeInterviewDB.id == interview_id,
                        RealtimeInterviewDB.status == InterviewStatus.ready.value,
                    )
                    .values(
                        status=InterviewStatus.in_progress.value,
                        updated_at=utc_now(),
                    )
                )
                claim_result = session.exec(claim_statement)
                if claim_result.rowcount != 1:
                    session.rollback()
                    record = RealtimeInterviewService._get_record(session, interview_id)
                    if record.status == InterviewStatus.completed.value:
                        raise RuntimeError("Impossible de relancer un entretien realtime déjà finalisé")
                else:
                    claimed_ready = True
                    session.commit()
                    record = RealtimeInterviewService._get_record(session, interview_id)
            else:
                session.commit()

            plan = InterviewPlan.model_validate(record.plan_data)
            state = InterviewRuntimeState.model_validate(record.runtime_state)

        session_config = RealtimeInterviewService._build_session_config_from_plan_and_state(plan, state)
        payload = {
            "expires_after": {
                "anchor": "created_at",
                "seconds": 600,
            },
            "session": session_config,
        }

        try:
            response = requests.post(
                RealtimeInterviewService.CLIENT_SECRET_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=20,
            )
        except requests.RequestException as exc:
            if claimed_ready:
                RealtimeInterviewService._reset_status_to_ready(interview_id)
            raise RuntimeError(f"Erreur réseau OpenAI realtime: {exc}") from exc

        if response.status_code >= 400:
            if claimed_ready:
                RealtimeInterviewService._reset_status_to_ready(interview_id)
            raise RuntimeError(
                f"OpenAI realtime client_secrets a échoué ({response.status_code}): {response.text[:400]}"
            )

        data = response.json()
        client_secret = data.get("client_secret") or {
            "value": data.get("value"),
            "expires_at": data.get("expires_at"),
        }
        if not client_secret.get("value"):
            if claimed_ready:
                RealtimeInterviewService._reset_status_to_ready(interview_id)
            raise RuntimeError("Réponse OpenAI invalide: client_secret manquant")

        return {
            "interviewId": interview_id,
            "client_secret": client_secret,
            "session": data.get("session", session_config),
        }

    @staticmethod
    def _realtime_model() -> str:
        try:
            selection = resolve_llm_selection("realtime_interview_live")
            if selection.provider == "openai" and selection.model:
                return selection.model
        except Exception:
            logger.exception("Impossible de résoudre le modèle realtime depuis llm_process_settings")
        return os.getenv("OPENAI_REALTIME_MODEL", RealtimeInterviewService.DEFAULT_REALTIME_MODEL).strip() or (
            RealtimeInterviewService.DEFAULT_REALTIME_MODEL
        )

    @staticmethod
    def _realtime_voice() -> str:
        return os.getenv("OPENAI_REALTIME_VOICE", RealtimeInterviewService.DEFAULT_REALTIME_VOICE).strip() or (
            RealtimeInterviewService.DEFAULT_REALTIME_VOICE
        )

    @staticmethod
    def _turn_detection_config() -> dict[str, Any]:
        turn_detection_type = os.getenv("OPENAI_REALTIME_TURN_DETECTION", "semantic_vad").strip() or "semantic_vad"
        # Barge-in is a product invariant: candidate speech must stop the active response.
        if turn_detection_type == "server_vad":
            return {
                "type": "server_vad",
                "threshold": float(os.getenv("OPENAI_REALTIME_VAD_THRESHOLD", "0.5")),
                "prefix_padding_ms": int(os.getenv("OPENAI_REALTIME_VAD_PREFIX_PADDING_MS", "300")),
                "silence_duration_ms": int(os.getenv("OPENAI_REALTIME_VAD_SILENCE_DURATION_MS", "450")),
                "create_response": True,
                "interrupt_response": True,
            }

        return {
            "type": "semantic_vad",
            "eagerness": os.getenv("OPENAI_REALTIME_SEMANTIC_VAD_EAGERNESS", "high").strip() or "high",
            "create_response": True,
            "interrupt_response": True,
        }

    @staticmethod
    def build_tool_definitions() -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "name": "getInterviewContext",
                "description": "Récupère le contexte complet de l'entretien si un détail du CV, du poste ou du plan manque.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "getInterviewRuntimeState",
                "description": "Récupère l'état courant de l'entretien, y compris l'étape active, les signaux et le transcript.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "appendTranscriptTurn",
                "description": (
                    "Ajoute un tour de transcript uniquement si la transcription automatique a manqué "
                    "un élément important ou si une correction explicite est nécessaire."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "speaker": {
                            "type": "string",
                            "enum": ["candidate", "assistant"],
                        },
                        "text": {"type": "string"},
                        "ts": {"type": "string"},
                    },
                    "required": ["speaker", "text"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "addNotableSignal",
                "description": "Enregistre un signal important observé pendant l'entretien.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": ["strength", "risk", "clarification", "followup"],
                        },
                        "text": {"type": "string"},
                    },
                    "required": ["type", "text"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "openTemporaryBranch",
                "description": "Ouvre une courte parenthèse pour approfondir un sujet chaud avant de revenir au plan.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string"},
                        "reason": {"type": "string"},
                        "remainingQuestions": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 2,
                        },
                    },
                    "required": ["topic", "reason"],
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "closeTemporaryBranch",
                "description": "Ferme la parenthèse temporaire et revient au plan principal.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "advanceStage",
                "description": "Passe à l'étape suivante du plan lorsque l'étape courante est suffisamment couverte.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
            {
                "type": "function",
                "name": "finalizeInterview",
                "description": "Finalise l'entretien à la toute fin et produit un résumé, les signaux et le transcript consolidé.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        ]

    @staticmethod
    def _persist_runtime_state(
        session,
        record: RealtimeInterviewDB,
        state: InterviewRuntimeState,
        *,
        status: str | None = None,
    ) -> None:
        record.runtime_state = state.model_dump(mode="json")
        record.updated_at = utc_now()
        if status:
            record.status = status
        session.add(record)
        session.commit()
        session.refresh(record)

    @staticmethod
    def _reset_status_to_ready(interview_id: str) -> None:
        with get_session() as session:
            record = RealtimeInterviewService._get_record(session, interview_id)
            if record.status == InterviewStatus.in_progress.value and record.completed_at is None:
                record.status = InterviewStatus.ready.value
                record.updated_at = utc_now()
                session.add(record)
                session.commit()

    @staticmethod
    def _get_record(
        session,
        interview_id: str,
        *,
        require_prepared: bool = True,
    ) -> RealtimeInterviewDB:
        record = session.get(RealtimeInterviewDB, interview_id)
        if not record:
            raise RealtimeInterviewNotFoundError(f"Entretien {interview_id} introuvable")
        if require_prepared and record.preparation_state != RealtimeInterviewPreparationState.ready.value:
            if record.preparation_state == RealtimeInterviewPreparationState.pending.value:
                raise RealtimeInterviewPreparationError(
                    "La préparation de l'entretien est en cours. Réessayez dans quelques instants.",
                    retryable=True,
                    interview_id=record.id,
                    preparation_state=record.preparation_state,
                )
            raise RealtimeInterviewPreparationError(
                "La préparation de l'entretien a échoué. Relancez la préparation depuis la fiche.",
                retryable=True,
                interview_id=record.id,
                preparation_state=record.preparation_state,
            )
        return record

    @staticmethod
    def _get_or_create_sheet_interview(
        payload: RealtimeInterviewSetupRequest,
        *,
        setup_context: dict[str, Any],
        sheet_id: str,
        owner_user_id: str,
    ) -> dict[str, Any]:
        lease_token = str(uuid.uuid4())
        lease_expires_at = utc_now() + timedelta(seconds=RealtimeInterviewService.PREPARATION_LEASE_SECONDS)
        interview_id = str(uuid.uuid4())
        registry_context = setup_context["registryContext"]
        owns_lease = False

        with get_session() as session:
            record = RealtimeInterviewDB(
                id=interview_id,
                owner_user_id=owner_user_id,
                interview_sheet_id=sheet_id,
                project_id=registry_context.projectId,
                active_sheet_slot=sheet_id,
                preparation_state=RealtimeInterviewPreparationState.pending.value,
                preparation_lease_token=lease_token,
                preparation_lease_expires_at=lease_expires_at,
                candidate_name=setup_context["candidateName"],
                language_hint="auto",
                status=InterviewStatus.ready.value,
                cv_text=setup_context["cvText"],
                job_description_text=setup_context["jobDescriptionText"],
                plan_data={},
                runtime_state={},
            )
            session.add(record)
            try:
                session.commit()
                owns_lease = True
            except IntegrityError:
                session.rollback()
                existing = session.exec(
                    select(RealtimeInterviewDB).where(
                        RealtimeInterviewDB.active_sheet_slot == sheet_id
                    )
                ).first()
                if not existing:
                    raise
                interview_id = existing.id
                if existing.preparation_state == RealtimeInterviewPreparationState.ready.value:
                    return RealtimeInterviewService.get_interview_context(existing.id)
                if RealtimeInterviewService._lease_is_active(existing.preparation_lease_expires_at):
                    owns_lease = False
                else:
                    previous_token = existing.preparation_lease_token
                    claim = session.exec(
                        update(RealtimeInterviewDB)
                        .where(
                            RealtimeInterviewDB.id == existing.id,
                            RealtimeInterviewDB.preparation_state.in_((
                                RealtimeInterviewPreparationState.pending.value,
                                RealtimeInterviewPreparationState.failed.value,
                            )),
                            RealtimeInterviewDB.preparation_lease_token == previous_token,
                        )
                        .values(
                            preparation_state=RealtimeInterviewPreparationState.pending.value,
                            preparation_lease_token=lease_token,
                            preparation_lease_expires_at=lease_expires_at,
                            owner_user_id=owner_user_id,
                            candidate_name=setup_context["candidateName"],
                            cv_text=setup_context["cvText"],
                            job_description_text=setup_context["jobDescriptionText"],
                            project_id=registry_context.projectId,
                            interview_sheet_id=sheet_id,
                            updated_at=utc_now(),
                        )
                    )
                    session.commit()
                    owns_lease = claim.rowcount == 1

        if not owns_lease:
            deadline = time.monotonic() + RealtimeInterviewService.PREPARATION_WAIT_SECONDS
            while time.monotonic() < deadline:
                time.sleep(0.025)
                with get_session() as session:
                    current = RealtimeInterviewService._get_record(
                        session,
                        interview_id,
                        require_prepared=False,
                    )
                    if current.preparation_state == RealtimeInterviewPreparationState.ready.value:
                        return RealtimeInterviewService.get_interview_context(interview_id)
                    if current.preparation_state == RealtimeInterviewPreparationState.failed.value:
                        break
            raise RealtimeInterviewPreparationError(
                "La préparation de l'entretien est en cours. Réessayez dans quelques instants.",
                retryable=True,
                interview_id=interview_id,
            )

        RealtimeInterviewService._sync_preparation_to_interview_sheet(
            sheet_id,
            interview_id=interview_id,
            status=RealtimeInterviewPreparationState.pending.value,
        )
        try:
            plan = RealtimeInterviewPlanner.build_plan(
                candidate_name=setup_context["candidateName"],
                cv_text=setup_context["cvText"],
                job_description_text=setup_context["jobDescriptionText"],
                language_hint=payload.languageHint.value,
                ai_plan_instructions=setup_context.get("aiPlanInstructions", ""),
            )
            plan.registryContext = registry_context
            runtime_state = RealtimeInterviewPlanner.build_initial_runtime_state(interview_id, plan)
        except Exception as exc:
            error_message = str(exc)[:500]
            with get_session() as session:
                failed = session.exec(
                    update(RealtimeInterviewDB)
                    .where(
                        RealtimeInterviewDB.id == interview_id,
                        RealtimeInterviewDB.preparation_state
                        == RealtimeInterviewPreparationState.pending.value,
                        RealtimeInterviewDB.preparation_lease_token == lease_token,
                    )
                    .values(
                        preparation_state=RealtimeInterviewPreparationState.failed.value,
                        preparation_lease_token=None,
                        preparation_lease_expires_at=None,
                        runtime_state={"preparationError": error_message},
                        updated_at=utc_now(),
                    )
                )
                session.commit()
            if failed.rowcount == 1:
                RealtimeInterviewService._sync_preparation_to_interview_sheet(
                    sheet_id,
                    interview_id=interview_id,
                    status=RealtimeInterviewPreparationState.failed.value,
                )
            raise

        with get_session() as session:
            published = session.exec(
                update(RealtimeInterviewDB)
                .where(
                    RealtimeInterviewDB.id == interview_id,
                    RealtimeInterviewDB.preparation_state
                    == RealtimeInterviewPreparationState.pending.value,
                    RealtimeInterviewDB.preparation_lease_token == lease_token,
                )
                .values(
                    candidate_name=plan.candidateName,
                    language_hint=plan.languageHint.value,
                    plan_data=plan.model_dump(mode="json"),
                    runtime_state=runtime_state.model_dump(mode="json"),
                    preparation_state=RealtimeInterviewPreparationState.ready.value,
                    preparation_lease_token=None,
                    preparation_lease_expires_at=None,
                    updated_at=utc_now(),
                )
            )
            session.commit()
            if published.rowcount != 1:
                current = RealtimeInterviewService._get_record(
                    session,
                    interview_id,
                    require_prepared=False,
                )
                if current.preparation_state == RealtimeInterviewPreparationState.ready.value:
                    return RealtimeInterviewService.get_interview_context(interview_id)
                raise RealtimeInterviewPreparationError(
                    "Le bail de préparation a expiré; le résultat obsolète a été ignoré.",
                    retryable=True,
                    interview_id=interview_id,
                )

        RealtimeInterviewService._sync_preparation_to_interview_sheet(
            sheet_id,
            interview_id=interview_id,
            status=RealtimeInterviewPreparationState.ready.value,
        )
        logger.info("Canonical realtime interview prepared: %s", interview_id)
        return {
            "interviewId": interview_id,
            "plan": plan.model_dump(mode="json"),
            "runtimeState": runtime_state.model_dump(mode="json"),
            "registryContext": RealtimeInterviewService._registry_context_payload(plan),
            "preparationState": RealtimeInterviewPreparationState.ready.value,
        }

    @staticmethod
    def _lease_is_active(expires_at: datetime | None) -> bool:
        if expires_at is None:
            return False
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at > utc_now()

    @staticmethod
    def _preparation_response(record: RealtimeInterviewDB) -> dict[str, Any]:
        return {
            "interviewId": record.id,
            "status": record.status,
            "preparationState": record.preparation_state,
            "retryable": True,
        }

    @staticmethod
    def _sync_preparation_to_interview_sheet(
        sheet_id: str,
        *,
        interview_id: str,
        status: str,
    ) -> None:
        try:
            InterviewSheetService.attach_realtime_preparation(
                sheet_id,
                interview_id=interview_id,
                status=status,
                updated_at=utc_now().isoformat(),
            )
        except (FileNotFoundError, OSError, ValueError):
            logger.warning(
                "Unable to sync realtime preparation %s to sheet %s",
                interview_id,
                sheet_id,
                exc_info=True,
            )

    @staticmethod
    def _resolve_stage_index(plan: InterviewPlan, stage_id: str) -> int:
        if not plan.stages:
            return 0
        for index, stage in enumerate(plan.stages):
            if stage.id == stage_id:
                return index
        return 0

    @staticmethod
    def _normalize_arguments(arguments: Any) -> dict[str, Any]:
        if arguments is None:
            return {}
        if isinstance(arguments, dict):
            return arguments
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
            except json.JSONDecodeError as exc:
                raise RealtimeInterviewToolError(f"Arguments JSON invalides: {exc}") from exc
            if not isinstance(parsed, dict):
                raise RealtimeInterviewToolError("Les arguments doivent être un objet JSON")
            return parsed
        raise RealtimeInterviewToolError("Format d'arguments non supporté")

    @staticmethod
    def _registry_context_payload(plan: InterviewPlan) -> dict[str, Any] | None:
        if not plan.registryContext:
            return None
        return plan.registryContext.model_dump(mode="json")

    @staticmethod
    def _resolve_setup_context(payload: RealtimeInterviewSetupRequest) -> dict[str, Any]:
        try:
            return RealtimeInterviewRegistryService.resolve_setup_payload(payload)
        except RealtimeInterviewRegistryError as exc:
            raise ValueError(str(exc)) from exc

    @staticmethod
    def _ensure_linked_interview_sheet(plan: InterviewPlan) -> str | None:
        registry_context = plan.registryContext
        if not registry_context:
            return None
        return registry_context.interviewSheetId or RealtimeInterviewRegistryService.find_linked_interview_sheet_id(
            registry_context.projectId,
            registry_context.candidateId,
            registry_context.matchingId,
        )

    @staticmethod
    def _build_system_instructions(plan: InterviewPlan, state: InterviewRuntimeState) -> str:
        stage_lines = []
        for idx, stage in enumerate(plan.stages, start=1):
            must_cover = ", ".join(stage.mustCover[:4]) or "aucun point"
            stage_lines.append(
                f"{idx}. {stage.label} ({stage.id}) - {stage.objective} | Must cover: {must_cover}"
            )

        covered = ", ".join(state.coveredItems) if state.coveredItems else "aucune étape validée"
        active_branch = (
            f"Sujet temporaire: {state.temporaryBranch.topic} ({state.temporaryBranch.remainingQuestions} questions restantes)"
            if state.temporaryBranch
            else "Aucune branche temporaire ouverte"
        )

        return (
            "Tu es un intervieweur professionnel, naturel, humain et réactif.\n\n"
            "Objectif:\n"
            "- conduire un entretien vocal en temps réel\n"
            "- utiliser le CV, l'offre d'emploi et le plan d'entretien fournis\n"
            "- suivre le plan comme une trame, sans être robotique\n"
            "- obtenir des réponses concrètes, vérifiables et utiles au recruteur\n\n"
            "Ouverture obligatoire:\n"
            "- Au tout début de l'entretien, ne commence jamais directement par une question métier, technique ou d'évaluation.\n"
            "- Commence comme un recruteur humain: salue le candidat, demande-lui comment il va, et rassure-le brièvement sur le cadre de l'échange.\n"
            "- Présente-toi en une phrase comme l'intervieweur IA qui va conduire l'échange pour ce recrutement.\n"
            "- Dis explicitement au candidat qu'il peut à tout moment demander de répéter, reformuler ou clarifier une question, ou prendre quelques secondes pour réfléchir.\n"
            "- Garde cette introduction chaleureuse mais courte: 20 à 35 secondes maximum.\n"
            "- Exemple en français à adapter naturellement: "
            "\"Bonjour {candidate}, j'espère que vous allez bien. Pas trop stressé j'espère ? "
            "Je vais conduire cet échange avec vous aujourd'hui. Il n'y a pas de piège: "
            "si une question n'est pas claire, n'hésitez pas à me demander de la répéter, de la reformuler ou de préciser ce que j'attends. "
            "Prenez aussi le temps de réfléchir si besoin. Est-ce que vous êtes prêt à commencer ?\"\n"
            "- Après cette ouverture, attends une confirmation ou une réponse courte du candidat avant de lancer la première question du plan.\n\n"
            "Règles:\n"
            "1. Pose une seule question à la fois.\n"
            "2. Parle brièvement et clairement.\n"
            "3. Si le candidat mentionne un élément très pertinent ou surprenant, creuse-le avec 1 à 2 relances maximum.\n"
            "4. Tu peux légèrement sortir du plan pour clarifier un point important, challenger une réponse vague ou vérifier un exemple concret.\n"
            "5. N'invente jamais un fait du CV ou du poste.\n"
            "6. Si une information est ambiguë, demande une clarification.\n"
            "7. Adapte-toi automatiquement à la langue du candidat. Priorité: français, anglais, arabe.\n"
            "8. Si l'utilisateur interrompt, arrête immédiatement ta réponse et écoute.\n"
            "9. Garde un ton humain, chaleureux, professionnel, crédible.\n"
            "10. Sois parfois exigeant: si une réponse est générale, demande un exemple précis, un résultat mesurable, une contrainte rencontrée ou une décision prise.\n"
            "11. Challenge sans agressivité les incohérences, les affirmations trop faciles ou les zones floues, comme le ferait un recruteur senior.\n"
            "12. Après une courte digression utile, reviens naturellement au plan d'entretien.\n"
            "13. Priorité absolue à la latence: réponds oralement dès que tu as assez d'information.\n"
            "14. N'enchaîne jamais plusieurs tools avant une réponse audio. Si un tool n'est pas indispensable, réponds d'abord.\n"
            "15. La transcription candidat/assistant est déjà persistée automatiquement par le système; n'utilise pas `appendTranscriptTurn` à chaque tour.\n"
            "16. Utilise les tools en arrière-plan seulement quand ils changent réellement l'état de l'entretien.\n\n"
            "17. Si le candidat dit clairement qu'il veut arrêter, finir ou clôturer l'entretien maintenant, "
            "n'attends pas la fin du créneau: dis brièvement que tu vas valider et clore l'entretien, "
            "remercie-le, puis appelle immédiatement `finalizeInterview`.\n\n"
            f"Contexte:\n"
            f"- Candidat: {plan.candidateName}\n"
            f"- Poste: {plan.roleTitle}\n"
            f"- Langue cible: {plan.languageHint.value}\n"
            f"- Résumé candidat: {plan.candidateSummary}\n"
            f"- Résumé poste: {plan.jobSummary}\n\n"
            "Plan:\n"
            f"{chr(10).join(stage_lines)}\n\n"
            "État courant:\n"
            f"- Étape active: {state.currentStageId}\n"
            f"- Couverture: {covered}\n"
            f"- Branche temporaire: {active_branch}\n\n"
            "Usage des tools:\n"
            "- `appendTranscriptTurn` seulement en correction/fallback si la transcription automatique manque un passage important.\n"
            "- `addNotableSignal` seulement pour un signal fort qui mérite vraiment d'être conservé, pas pour chaque réponse.\n"
            "- `openTemporaryBranch` pour une parenthèse courte, puis `closeTemporaryBranch` dès que le sujet est couvert; évite cette paire si une simple relance suffit.\n"
            "- `advanceStage` uniquement au moment d'un vrai changement d'étape, idéalement après avoir posé la transition oralement.\n"
            "- `finalizeInterview` à la fin normale, ou immédiatement après une demande explicite du candidat de finir/clore l'entretien.\n"
        )

    @staticmethod
    def _build_summary(plan: InterviewPlan, state: InterviewRuntimeState) -> dict[str, Any]:
        transcript_dump = state.model_dump(mode="json")["transcriptTurns"]
        signals_dump = state.model_dump(mode="json")["notableSignals"]

        candidate_turns = [turn["text"] for turn in transcript_dump if turn["speaker"] == "candidate"]
        strengths = [signal["text"] for signal in signals_dump if signal["type"] == "strength"]
        risks = [signal["text"] for signal in signals_dump if signal["type"] == "risk"]
        clarifications = [signal["text"] for signal in signals_dump if signal["type"] == "clarification"]
        completed_stage_labels = [
            stage.label for stage in plan.stages if stage.id in state.coveredItems
        ]

        highlights = strengths[:3] or candidate_turns[:2]
        overall_appreciation = RealtimeInterviewService._build_overall_appreciation(
            plan=plan,
            candidate_turns=candidate_turns,
            strengths=strengths,
            risks=risks,
            clarifications=clarifications,
            completed_stage_labels=completed_stage_labels,
        )
        summary_text = (
            f"Entretien de {plan.candidateName} pour {plan.roleTitle}. "
            f"{len(candidate_turns)} prises de parole candidat relevées. "
            f"Étapes couvertes: {', '.join(completed_stage_labels) or 'aucune'}. "
            f"Points saillants: {', '.join(highlights) or 'aucun point fort explicite relevé'}. "
            f"Risques/clarifications: {', '.join((risks + clarifications)[:3]) or 'aucun signal critique relevé'}."
        )

        return {
            "summaryText": summary_text,
            "overallAppreciation": overall_appreciation,
            "overall_appreciation": overall_appreciation,
            "roleTitle": plan.roleTitle,
            "candidateName": plan.candidateName,
            "completedStages": completed_stage_labels,
            "highlights": highlights,
            "risks": risks[:5],
            "clarifications": clarifications[:5],
            "transcriptTurnCount": len(transcript_dump),
        }

    @staticmethod
    def _build_overall_appreciation(
        *,
        plan: InterviewPlan,
        candidate_turns: list[str],
        strengths: list[str],
        risks: list[str],
        clarifications: list[str],
        completed_stage_labels: list[str],
    ) -> str:
        if not candidate_turns:
            return (
                f"Appréciation globale: l'entretien de {plan.candidateName} pour {plan.roleTitle} "
                "ne contient pas encore assez de réponses candidat pour émettre un avis fiable. "
                "Recommandation: compléter l'entretien avant décision."
            )

        signal_count = len(strengths)
        risk_count = len(risks) + len(clarifications)
        coverage_count = len(completed_stage_labels)

        if signal_count >= 2 and risk_count == 0 and coverage_count >= 2:
            orientation = "favorable"
            recommendation = "poursuivre le process avec un échange métier ou décisionnel."
        elif signal_count >= 1 and risk_count <= 2:
            orientation = "plutôt favorable, avec quelques points à confirmer"
            recommendation = "poursuivre en ciblant les points de vigilance identifiés."
        elif risk_count >= 3 and signal_count == 0:
            orientation = "réservée"
            recommendation = "ne pas avancer sans clarification complémentaire."
        else:
            orientation = "à approfondir"
            recommendation = "compléter l'évaluation avant décision finale."

        positive_part = (
            f"Points positifs observés: {', '.join(strengths[:2])}."
            if strengths
            else f"Le candidat a fourni {len(candidate_turns)} réponse(s), mais aucun point fort explicite n'a encore été isolé."
        )
        risk_items = (risks + clarifications)[:2]
        risk_part = (
            f"Points à vérifier: {', '.join(risk_items)}."
            if risk_items
            else "Aucun risque critique explicite n'a été relevé pendant l'entretien."
        )

        return (
            f"Appréciation globale: avis {orientation} pour {plan.candidateName} sur le poste {plan.roleTitle}. "
            f"{positive_part} {risk_part} Recommandation: {recommendation}"
        )

    @staticmethod
    def _sync_summary_to_interview_sheet(
        plan: InterviewPlan,
        summary: dict[str, Any],
        state: InterviewRuntimeState,
        *,
        interview_id: str,
        interview_sheet_id: str | None,
        completed_at: datetime | None,
    ) -> dict[str, Any] | None:
        registry_context = RealtimeInterviewService._registry_context_payload(plan)
        interview_sheet_id = interview_sheet_id or (registry_context or {}).get("interviewSheetId")
        if not interview_sheet_id:
            return None

        interview_sheet = InterviewSheetService.get(interview_sheet_id)
        if not interview_sheet:
            logger.warning(
                "Unable to sync realtime summary, interview sheet missing: %s",
                interview_sheet_id,
            )
            return None

        try:
            next_status = "in_progress" if interview_sheet.get("status") == "draft" else None
            updated_sheet = InterviewSheetService.attach_realtime_summary(
                interview_sheet_id,
                interview_id=interview_id,
                summary_text=summary.get("summaryText", ""),
                summary_data=summary,
                transcript_turns=state.model_dump(mode="json")["transcriptTurns"],
                notable_signals=state.model_dump(mode="json")["notableSignals"],
                registry_context=registry_context,
                completed_at=completed_at.isoformat() if completed_at else utc_now().isoformat(),
                realtime_status=InterviewStatus.completed.value,
                status=next_status,
            )
            return {
                "interviewSheetId": interview_sheet_id,
                "updatedAt": updated_sheet.get("updated_at") if updated_sheet else None,
            }
        except Exception:
            logger.exception(
                "Unable to sync realtime interview %s to interview sheet %s",
                interview_id,
                interview_sheet_id,
            )
            return {
                "interviewSheetId": interview_sheet_id,
                "error": "sync_failed",
            }

    @staticmethod
    def _sync_runtime_to_interview_sheet(
        *,
        interview_id: str,
        plan: InterviewPlan,
        state: InterviewRuntimeState,
        summary_data: dict[str, Any],
        realtime_status: str,
        completed_at: str | None = None,
    ) -> dict[str, Any] | None:
        if realtime_status != InterviewStatus.completed.value:
            return None
        registry_context = RealtimeInterviewService._registry_context_payload(plan)
        interview_sheet_id = (registry_context or {}).get("interviewSheetId")
        if not interview_sheet_id:
            return None

        interview_sheet = InterviewSheetService.get(interview_sheet_id)
        if not interview_sheet:
            logger.warning(
                "Unable to sync realtime runtime, interview sheet missing: %s",
                interview_sheet_id,
            )
            return None

        summary_text = ""
        if isinstance(summary_data, dict):
            summary_text = str(summary_data.get("summaryText") or summary_data.get("summary") or "")

        try:
            next_status = "in_progress" if interview_sheet.get("status") == "draft" else None
            updated_sheet = InterviewSheetService.attach_realtime_summary(
                interview_sheet_id,
                interview_id=interview_id,
                summary_text=summary_text,
                summary_data=summary_data,
                transcript_turns=state.model_dump(mode="json")["transcriptTurns"],
                notable_signals=state.model_dump(mode="json")["notableSignals"],
                registry_context=registry_context,
                completed_at=completed_at,
                realtime_status=realtime_status,
                status=next_status,
            )
            return {
                "interviewSheetId": interview_sheet_id,
                "updatedAt": updated_sheet.get("updated_at") if updated_sheet else None,
            }
        except Exception:
            logger.exception(
                "Unable to sync realtime runtime %s to interview sheet %s",
                interview_id,
                interview_sheet_id,
            )
            return {
                "interviewSheetId": interview_sheet_id,
                "error": "sync_failed",
            }
