from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from brainrh.database import get_session
from brainrh.models.realtime_interview import (
    InterviewContextMode,
    RealtimeInterviewRegistryContext,
    RealtimeInterviewSetupRequest,
)
from brainrh.services.application_service import ApplicationService
from brainrh.services.interview_sheet_service import InterviewSheetService
from brainrh.services.matching_file_service import MatchingFileService
from brainrh.services.project_file_service import ProjectFileService
from brainrh.services.project_service import ProjectService


class RealtimeInterviewRegistryError(ValueError):
    pass


def _string_variants(values: Iterable[Any]) -> set[str]:
    variants: set[str] = set()
    for raw_value in values:
        if raw_value is None:
            continue
        normalized = str(raw_value).strip().lower()
        if not normalized:
            continue
        variants.add(normalized)
        variants.add(Path(normalized).name)
        variants.add(Path(normalized).stem)
    return variants


class RealtimeInterviewRegistryService:
    @staticmethod
    def resolve_setup_payload(payload: RealtimeInterviewSetupRequest) -> dict[str, Any]:
        mode = RealtimeInterviewRegistryService._normalize_mode(payload)
        if mode == InterviewContextMode.manual.value:
            candidate_name = (payload.candidateName or "").strip()
            cv_text = (payload.cvText or "").strip()
            job_text = (payload.jobDescriptionText or "").strip()
            if not candidate_name or not cv_text or not job_text:
                raise RealtimeInterviewRegistryError(
                    "Le mode manuel requiert candidateName, cvText et jobDescriptionText."
                )
            return {
                "mode": mode,
                "candidateName": candidate_name,
                "cvText": cv_text,
                "jobDescriptionText": job_text,
                "aiPlanInstructions": (payload.aiPlanInstructions or "").strip(),
                "registryContext": None,
            }

        resolved = RealtimeInterviewRegistryService._resolve_registry_context(
            project_id=payload.projectId or payload.jobId,
            candidate_id=payload.candidateId,
            matching_id=payload.matchingId,
            interview_sheet_id=payload.interviewSheetId,
        )
        resolved["aiPlanInstructions"] = (payload.aiPlanInstructions or "").strip()
        return resolved

    @staticmethod
    def resolve_interview_sheet_context(interview_sheet: dict[str, Any]) -> dict[str, Any]:
        if not interview_sheet:
            raise RealtimeInterviewRegistryError("Fiche d'entretien introuvable")

        resolved = RealtimeInterviewRegistryService._resolve_registry_context(
            project_id=interview_sheet.get("job_id"),
            candidate_id=interview_sheet.get("candidate_id"),
            matching_id=interview_sheet.get("matching_id"),
            interview_sheet_id=interview_sheet.get("id"),
        )
        sheet_data = interview_sheet.get("data")
        if not isinstance(sheet_data, dict):
            sheet_data = {}
        resolved["aiPlanInstructions"] = str(sheet_data.get("ai_plan_instructions") or "").strip()[:4000]
        return resolved

    @staticmethod
    def find_linked_interview_sheet_id(
        project_id: str | None,
        candidate_id: str | None,
        matching_id: str | None,
    ) -> str | None:
        if not project_id or not candidate_id or not matching_id:
            return None
        existing_sheet = InterviewSheetService.find_existing(candidate_id, project_id, matching_id)
        return existing_sheet["id"] if existing_sheet else None

    @staticmethod
    def _resolve_registry_context(
        *,
        project_id: str | None,
        candidate_id: str | None,
        matching_id: str | None,
        interview_sheet_id: str | None,
    ) -> dict[str, Any]:
        linked_sheet = InterviewSheetService.get(interview_sheet_id) if interview_sheet_id else None
        if interview_sheet_id and not linked_sheet:
            raise RealtimeInterviewRegistryError(
                f"Fiche d'entretien {interview_sheet_id} introuvable pour le mode registry."
            )

        resolved_project_id = project_id or (linked_sheet or {}).get("job_id")
        resolved_candidate_id = candidate_id or (linked_sheet or {}).get("candidate_id")
        resolved_matching_id = matching_id or (linked_sheet or {}).get("matching_id")
        resolved_interview_sheet_id = interview_sheet_id or (linked_sheet or {}).get("id")

        if not resolved_project_id:
            raise RealtimeInterviewRegistryError("Le mode registry requiert projectId/jobId ou interviewSheetId.")
        if not resolved_candidate_id:
            raise RealtimeInterviewRegistryError("Le mode registry requiert candidateId ou interviewSheetId.")

        project_data = ProjectService.get_project(resolved_project_id)
        offer_data = ProjectFileService.load_offer(
            resolved_project_id,
            enterprise_id=(project_data or {}).get("enterprise_id"),
        )
        job_description_text = (
            RealtimeInterviewRegistryService._render_offer_text(offer_data)
            or RealtimeInterviewRegistryService._render_project_text(project_data)
        )
        if not job_description_text:
            raise RealtimeInterviewRegistryError(
                f"Impossible de résoudre l'offre canonique du projet {resolved_project_id}."
            )

        with get_session() as session:
            candidate = ApplicationService.find_project_candidate(
                session,
                resolved_project_id,
                str(resolved_candidate_id),
            )

        if not candidate:
            raise RealtimeInterviewRegistryError(
                f"Candidat {resolved_candidate_id} introuvable pour le projet {resolved_project_id}."
            )

        candidate_name = RealtimeInterviewRegistryService._candidate_display_name(candidate)
        cv_text = RealtimeInterviewRegistryService._render_candidate_text(candidate)
        if not cv_text:
            raise RealtimeInterviewRegistryError(
                f"Impossible de reconstruire le CV canonique du candidat {resolved_candidate_id}."
            )

        matching_payload = None
        if resolved_matching_id:
            matching_payload = MatchingFileService.load_matching_json(
                resolved_project_id,
                resolved_matching_id,
                enterprise_id=(project_data or {}).get("enterprise_id"),
            )
        matching_result = RealtimeInterviewRegistryService._find_matching_result(
            matching_payload,
            str(resolved_candidate_id),
            candidate,
        )
        matching_text = RealtimeInterviewRegistryService._render_matching_text(matching_result)
        if matching_text:
            cv_text = f"{cv_text}\n\n### Contexte de matching BrainRH\n{matching_text}"

        if not resolved_interview_sheet_id:
            resolved_interview_sheet_id = RealtimeInterviewRegistryService.find_linked_interview_sheet_id(
                resolved_project_id,
                str(resolved_candidate_id),
                resolved_matching_id,
            )

        registry_context = RealtimeInterviewRegistryContext(
            projectId=resolved_project_id,
            candidateId=str(resolved_candidate_id),
            matchingId=resolved_matching_id,
            interviewSheetId=resolved_interview_sheet_id,
            applicationId=candidate.get("application_id"),
            talentProfileId=candidate.get("talent_profile_id"),
            resumeVersionId=candidate.get("resume_version_id"),
            source=candidate.get("source"),
            candidateEmail=candidate.get("email"),
            candidatePhone=candidate.get("phone"),
        )

        return {
            "mode": InterviewContextMode.registry.value,
            "candidateName": candidate_name,
            "cvText": cv_text,
            "jobDescriptionText": job_description_text,
            "registryContext": registry_context,
            "candidate": candidate,
            "project": project_data,
        }

    @staticmethod
    def _normalize_mode(payload: RealtimeInterviewSetupRequest) -> str:
        explicit_mode = payload.mode.value if payload.mode else None
        if explicit_mode == InterviewContextMode.manual.value:
            return InterviewContextMode.manual.value
        if explicit_mode in {InterviewContextMode.registry.value, InterviewContextMode.canonical.value}:
            return InterviewContextMode.registry.value
        if payload.projectId or payload.jobId or payload.candidateId or payload.interviewSheetId:
            return InterviewContextMode.registry.value
        return InterviewContextMode.manual.value

    @staticmethod
    def _candidate_display_name(candidate: dict[str, Any]) -> str:
        full_name = " ".join(
            part.strip()
            for part in [
                str(candidate.get("first_name") or ""),
                str(candidate.get("last_name") or ""),
                str(candidate.get("nom_complet") or ""),
            ]
            if part and str(part).strip()
        ).strip()
        if full_name:
            return full_name

        cv_data = candidate.get("cv_data")
        if isinstance(cv_data, dict):
            personal_info = cv_data.get("informations_personnelles") or {}
            for key in ("nom_complet", "name", "full_name"):
                value = personal_info.get(key) or cv_data.get(key)
                if value:
                    return str(value).strip()

        return str(candidate.get("filename") or candidate.get("email") or candidate.get("application_id") or "Candidat")

    @staticmethod
    def _render_candidate_text(candidate: dict[str, Any]) -> str:
        cv_data = candidate.get("cv_data")
        if not isinstance(cv_data, dict):
            return RealtimeInterviewRegistryService._candidate_display_name(candidate)

        parts: list[str] = []
        identity_line = RealtimeInterviewRegistryService._candidate_display_name(candidate)
        personal = cv_data.get("informations_personnelles") or {}
        email = candidate.get("email") or personal.get("email")
        phone = candidate.get("phone") or personal.get("telephone") or personal.get("phone")
        if identity_line:
            contact_bits = [bit for bit in [email, phone] if bit]
            if contact_bits:
                parts.append(f"Candidat: {identity_line} | {' | '.join(contact_bits)}")
            else:
                parts.append(f"Candidat: {identity_line}")

        summary = cv_data.get("resume") or cv_data.get("summary") or cv_data.get("profil")
        if summary:
            parts.append(f"Résumé: {summary}")

        technical_skills = []
        competences = cv_data.get("competences")
        if isinstance(competences, dict):
            technical_skills.extend(competences.get("techniques") or [])
            technical_skills.extend(competences.get("outils") or [])
        if technical_skills:
            parts.append(f"Compétences clés: {', '.join(str(skill) for skill in technical_skills[:12])}")

        experiences = cv_data.get("experiences_professionnelles") or cv_data.get("experiences") or []
        experience_lines: list[str] = []
        if isinstance(experiences, list):
            for experience in experiences[:5]:
                if not isinstance(experience, dict):
                    continue
                title = (
                    experience.get("poste")
                    or experience.get("titre")
                    or experience.get("intitule")
                    or experience.get("role")
                )
                company = experience.get("entreprise") or experience.get("company")
                period = (
                    experience.get("periode")
                    or experience.get("duration")
                    or " - ".join(
                        part
                        for part in [
                            str(experience.get("date_debut") or "").strip(),
                            str(experience.get("date_fin") or "").strip(),
                        ]
                        if part
                    )
                )
                description = experience.get("description")
                if not description:
                    missions = experience.get("missions")
                    if isinstance(missions, list):
                        description = "; ".join(str(item) for item in missions[:3])
                line = " | ".join(
                    str(bit).strip()
                    for bit in [title, company, period, description]
                    if bit and str(bit).strip()
                )
                if line:
                    experience_lines.append(f"- {line}")
        if experience_lines:
            parts.append("Expériences:\n" + "\n".join(experience_lines))

        formations = cv_data.get("formations") or cv_data.get("education") or []
        formation_lines: list[str] = []
        if isinstance(formations, list):
            for formation in formations[:3]:
                if not isinstance(formation, dict):
                    continue
                degree = formation.get("diplome") or formation.get("titre") or formation.get("degree")
                school = formation.get("ecole") or formation.get("etablissement") or formation.get("school")
                year = formation.get("annee") or formation.get("year")
                line = " | ".join(
                    str(bit).strip()
                    for bit in [degree, school, year]
                    if bit and str(bit).strip()
                )
                if line:
                    formation_lines.append(f"- {line}")
        if formation_lines:
            parts.append("Formations:\n" + "\n".join(formation_lines))

        if not parts:
            return json.dumps(cv_data, ensure_ascii=False, indent=2)
        return "\n\n".join(parts)

    @staticmethod
    def _render_offer_text(offer_data: dict[str, Any] | None) -> str:
        if not isinstance(offer_data, dict) or not offer_data:
            return ""

        parts: list[str] = []
        title = offer_data.get("intitule") or offer_data.get("title") or offer_data.get("poste")
        if title:
            parts.append(f"Poste: {title}")

        for label, key in [
            ("Résumé", "resume"),
            ("Description", "description"),
            ("Missions", "missions"),
            ("Contexte", "contexte"),
        ]:
            value = offer_data.get(key)
            if value:
                if isinstance(value, list):
                    value = "; ".join(str(item) for item in value[:6])
                parts.append(f"{label}: {value}")

        must_have = offer_data.get("must_have") or offer_data.get("mustHave") or []
        if isinstance(must_have, list) and must_have:
            parts.append(f"Must-have: {', '.join(str(item) for item in must_have[:10])}")

        nice_have = offer_data.get("nice_have") or offer_data.get("niceHave") or []
        if isinstance(nice_have, list) and nice_have:
            parts.append(f"Nice-to-have: {', '.join(str(item) for item in nice_have[:8])}")

        return "\n\n".join(parts)

    @staticmethod
    def _render_project_text(project_data: dict[str, Any] | None) -> str:
        if not isinstance(project_data, dict) or not project_data:
            return ""

        parts = []
        if project_data.get("nom"):
            parts.append(f"Projet: {project_data['nom']}")
        if project_data.get("description"):
            parts.append(f"Description: {project_data['description']}")
        if project_data.get("notes"):
            parts.append(f"Notes: {project_data['notes']}")
        return "\n\n".join(parts)

    @staticmethod
    def _find_matching_result(
        matching_payload: dict[str, Any] | None,
        candidate_id: str,
        candidate: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not isinstance(matching_payload, dict):
            return None

        candidate_tokens = _string_variants(
            [
                candidate_id,
                candidate.get("filename"),
                candidate.get("application_id"),
                candidate.get("resume_version_id"),
            ]
        )
        cv_data = candidate.get("cv_data")
        if isinstance(cv_data, dict):
            candidate_tokens |= _string_variants([cv_data.get("cv"), cv_data.get("filename")])

        candidate_lists = []
        results = matching_payload.get("results")
        if isinstance(results, list):
            candidate_lists.append(results)
        qualified_results = matching_payload.get("qualified_results")
        if isinstance(qualified_results, list):
            candidate_lists.append(qualified_results)

        for result_list in candidate_lists:
            for result in result_list:
                if not isinstance(result, dict):
                    continue
                result_tokens = _string_variants([result.get("cv"), result.get("filename")])
                if candidate_tokens & result_tokens:
                    return result
        return None

    @staticmethod
    def _render_matching_text(matching_result: dict[str, Any] | None) -> str:
        if not isinstance(matching_result, dict):
            return ""

        parts: list[str] = []
        if matching_result.get("score_final") is not None:
            parts.append(f"Score final: {matching_result['score_final']}")
        if matching_result.get("appreciation_globale"):
            parts.append(f"Appréciation: {matching_result['appreciation_globale']}")
        missing_nice_have = matching_result.get("nice_have_manquants")
        if isinstance(missing_nice_have, list) and missing_nice_have:
            parts.append(f"Nice-have manquants: {', '.join(str(item) for item in missing_nice_have[:6])}")
        comment = matching_result.get("commentaire_scoring")
        if comment:
            parts.append(f"Commentaire de scoring: {comment}")
        return "\n".join(parts)
