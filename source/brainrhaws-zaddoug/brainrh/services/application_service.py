from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional, Set
from sqlmodel import Session, select
from brainrh.models.application import ApplicationDB
from brainrh.models.talent_profile import TalentProfileDB
from brainrh.models.resume_version import ResumeVersionDB
from brainrh.models.project import ProjectDB
from brainrh.models.cv import CVMetaDB
from brainrh.services.cv_service import CVService
from brainrh.services.file_storage import FileStorage
from lib.models import CV
import json


_CANDIDATE_STORAGE_WORKERS = 8


def _load_candidate_payloads(paths: Set[str]) -> dict[str, object]:
    """Load independent candidate JSON objects concurrently and at most once."""
    normalized_paths = sorted(path for path in paths if path)
    if not normalized_paths:
        return {}
    if len(normalized_paths) == 1:
        path = normalized_paths[0]
        return {path: FileStorage.load_json_if_exists(path)}

    with ThreadPoolExecutor(
        max_workers=min(_CANDIDATE_STORAGE_WORKERS, len(normalized_paths))
    ) as executor:
        payloads = executor.map(FileStorage.load_json_if_exists, normalized_paths)
        return dict(zip(normalized_paths, payloads))


def _candidate_tokens(candidate: dict) -> Set[str]:
    tokens: Set[str] = set()

    for raw_value in [
        candidate.get("filename"),
        candidate.get("application_id"),
        candidate.get("talent_profile_id"),
        candidate.get("resume_version_id"),
        candidate.get("email"),
        candidate.get("storage_path"),
        candidate.get("json_path"),
    ]:
        if raw_value is None:
            continue
        normalized = str(raw_value).strip().lower()
        if not normalized:
            continue
        tokens.add(normalized)
        tokens.add(Path(normalized).name)
        tokens.add(Path(normalized).stem)

    cv_data = candidate.get("cv_data")
    if isinstance(cv_data, dict):
        for raw_value in [
            cv_data.get("cv"),
            cv_data.get("filename"),
        ]:
            if raw_value is None:
                continue
            normalized = str(raw_value).strip().lower()
            if not normalized:
                continue
            tokens.add(normalized)
            tokens.add(Path(normalized).name)
            tokens.add(Path(normalized).stem)

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
        tokens.add(full_name.lower())

    return tokens


def _candidate_identity_tokens(candidate: dict) -> Set[str]:
    """Tokens stricts pour dédupliquer sans confondre deux profils homonymes."""
    tokens: Set[str] = set()

    for raw_value in [
        candidate.get("application_id"),
        candidate.get("resume_version_id"),
        candidate.get("storage_path"),
        candidate.get("json_path"),
    ]:
        if raw_value is None:
            continue
        normalized = str(raw_value).strip().lower()
        if normalized:
            tokens.add(normalized)

    filename = candidate.get("filename")
    email = candidate.get("email")
    if filename:
        normalized_filename = Path(str(filename)).name.strip().lower()
        if normalized_filename:
            tokens.add(normalized_filename)
            tokens.add(Path(normalized_filename).stem)
            if email:
                normalized_email = str(email).strip().lower()
                if normalized_email:
                    tokens.add(f"{normalized_filename}::{normalized_email}")

    return tokens


class ApplicationService:
    @staticmethod
    def get_project_candidate_summary(session: Session, project_id: str) -> dict:
        """Return a storage-free candidate count for project overview screens."""
        applications = list(
            session.exec(
                select(ApplicationDB).where(ApplicationDB.project_id == project_id)
            ).all()
        )
        legacy_rows = list(
            session.exec(
                select(CVMetaDB).where(CVMetaDB.project_id == project_id)
            ).all()
        )

        resume_ids = {
            app.resume_version_id
            for app in applications
            if app.resume_version_id is not None
        }
        resumes = (
            session.exec(
                select(ResumeVersionDB).where(ResumeVersionDB.id.in_(resume_ids))
            ).all()
            if resume_ids
            else []
        )
        resume_by_id = {resume.id: resume for resume in resumes}

        valid_legacy_rows = [
            row for row in legacy_rows
            if str(row.filename or "").strip() and str(row.json_path or "").strip()
        ]
        legacy_tokens: Set[str] = set()
        for row in valid_legacy_rows:
            for raw_value in (row.filename, row.file_path, row.json_path):
                if not raw_value:
                    continue
                normalized = str(raw_value).strip().lower()
                if not normalized:
                    continue
                legacy_tokens.add(normalized)
                legacy_tokens.add(Path(normalized).name)

        candidate_count = len(valid_legacy_rows)
        for app in applications:
            resume = resume_by_id.get(app.resume_version_id)
            if resume is None or not resume.parsed_json_str:
                continue
            try:
                CV.model_validate(json.loads(resume.parsed_json_str))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            storage_path = resume.storage_path if resume else None
            if storage_path:
                normalized = str(storage_path).strip().lower()
                application_tokens = {normalized, Path(normalized).name}
                if application_tokens & legacy_tokens:
                    continue
            candidate_count += 1

        return {"count": candidate_count, "ready": candidate_count > 0}

    @staticmethod
    def create_application(
        session: Session,
        talent_profile_id: int,
        project_id: str,
        enterprise_id: str,
        resume_version_id: Optional[int] = None,
        status: str = "new"
    ) -> ApplicationDB:
        profile = session.get(TalentProfileDB, talent_profile_id)
        if not profile or profile.enterprise_id != enterprise_id:
            raise ValueError("Talent profile invalid or cross-enterprise link forbidden")

        project = session.get(ProjectDB, project_id)
        if not project or project.enterprise_id != enterprise_id:
            raise ValueError("Project invalid or cross-enterprise link forbidden")

        if resume_version_id:
            resume = session.get(ResumeVersionDB, resume_version_id)
            if not resume or resume.enterprise_id != enterprise_id or resume.talent_profile_id != talent_profile_id:
                raise ValueError("Resume invalid or cross-enterprise link forbidden")

        app = ApplicationDB(
            talent_profile_id=talent_profile_id,
            project_id=project_id,
            enterprise_id=enterprise_id,
            resume_version_id=resume_version_id,
            status=status
        )
        session.add(app)
        session.commit()
        session.refresh(app)
        return app

    @staticmethod
    def list_applications_for_project(session: Session, project_id: str) -> List[ApplicationDB]:
        statement = select(ApplicationDB).where(ApplicationDB.project_id == project_id)
        results = session.exec(statement).all()
        return list(results)

    @staticmethod
    def find_project_candidate(session: Session, project_id: str, candidate_id: str) -> Optional[dict]:
        normalized_id = str(candidate_id or "").strip().lower()
        if not normalized_id:
            return None

        requested_tokens = {
            normalized_id,
            Path(normalized_id).name,
            Path(normalized_id).stem,
        }

        for candidate in ApplicationService.get_project_candidates(session, project_id):
            if requested_tokens & _candidate_tokens(candidate):
                return candidate

        return None

    @staticmethod
    def get_project_candidates(session: Session, project_id: str) -> List[dict]:
        """
        Récupère les candidatures d'un projet en exposant à la fois :
        - les candidatures modernes (Application / ResumeVersion),
        - les CV legacy encore présents dans cv_meta.

        Important:
        - si des données existent dans les deux mondes, on les fusionne;
        - les métadonnées utiles au frontend / matching (filename, storage_path,
          json_path) sont conservées pour éviter les divergences d'affichage.
        """
        legacy_cvs = CVService.list_by_project(project_id)
        legacy_by_file_path = {
            cv["file_path"]: cv for cv in legacy_cvs if cv.get("file_path")
        }
        legacy_by_json_path = {
            cv["json_path"]: cv for cv in legacy_cvs if cv.get("json_path")
        }
        legacy_by_basename = {
            Path(cv["file_path"]).name.lower(): cv
            for cv in legacy_cvs
            if cv.get("file_path")
        }

        statement = select(ApplicationDB).where(ApplicationDB.project_id == project_id)
        apps = list(session.exec(statement).all())

        profile_ids = {app.talent_profile_id for app in apps}
        profiles = (
            session.exec(
                select(TalentProfileDB).where(TalentProfileDB.id.in_(profile_ids))
            ).all()
            if profile_ids
            else []
        )
        profiles_by_id = {profile.id: profile for profile in profiles}

        resume_ids = {
            app.resume_version_id
            for app in apps
            if app.resume_version_id is not None
        }
        resumes = (
            session.exec(
                select(ResumeVersionDB).where(ResumeVersionDB.id.in_(resume_ids))
            ).all()
            if resume_ids
            else []
        )
        resumes_by_id = {resume.id: resume for resume in resumes}

        parsed_payloads_by_resume_id = {}
        for resume in resumes:
            if not resume.parsed_json_str:
                continue
            try:
                parsed_payload = json.loads(resume.parsed_json_str)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(parsed_payload, dict) and parsed_payload:
                parsed_payloads_by_resume_id[resume.id] = parsed_payload

        authoritative_storage_paths = {
            resume.storage_path
            for resume in resumes
            if resume.id in parsed_payloads_by_resume_id and resume.storage_path
        }
        payload_paths = {
            cv["json_path"]
            for cv in legacy_cvs
            if cv.get("json_path") and cv["json_path"] not in authoritative_storage_paths
        }
        payload_paths.update(
            resume.storage_path
            for resume in resumes
            if resume.id not in parsed_payloads_by_resume_id
            and resume.storage_path
            and resume.storage_path.endswith(".json")
        )
        payloads_by_path = _load_candidate_payloads(payload_paths)

        candidates = []
        seen_tokens: Set[str] = set()

        for app in apps:
            profile = profiles_by_id.get(app.talent_profile_id)
            resume = resumes_by_id.get(app.resume_version_id) if app.resume_version_id else None
            legacy_cv = None

            candidate_data = {
                "source": "application_db",
                "application_id": app.id,
                "talent_profile_id": app.talent_profile_id,
                "resume_version_id": app.resume_version_id,
                "status": app.status,
                "email": profile.email if profile else None,
                "first_name": profile.first_name if profile else None,
                "last_name": profile.last_name if profile else None,
                "phone": profile.phone if profile else None,
                "storage_path": resume.storage_path if resume else None,
                "json_path": None,
                "filename": None,
                "cv_data": None,
            }

            if resume and resume.id in parsed_payloads_by_resume_id:
                candidate_data["cv_data"] = parsed_payloads_by_resume_id[resume.id]
                if resume.storage_path and resume.storage_path.endswith(".json"):
                    candidate_data["json_path"] = resume.storage_path

            if resume and not candidate_data.get("cv_data") and resume.storage_path and resume.storage_path.endswith(".json"):
                candidate_data["cv_data"] = payloads_by_path.get(resume.storage_path)
                if candidate_data["cv_data"] is not None:
                    candidate_data["json_path"] = resume.storage_path

            if resume and resume.storage_path:
                legacy_cv = (
                    legacy_by_file_path.get(resume.storage_path)
                    or legacy_by_json_path.get(resume.storage_path)
                    or legacy_by_basename.get(Path(resume.storage_path).name.lower())
                )

            if legacy_cv:
                if not candidate_data.get("json_path"):
                    candidate_data["json_path"] = legacy_cv.get("json_path")
                if legacy_cv.get("json_path") and legacy_cv.get("json_path") != (resume.storage_path if resume else None):
                    legacy_payload = payloads_by_path.get(legacy_cv["json_path"])
                    if legacy_payload is not None:
                        if candidate_data.get("cv_data"):
                            merged_payload = dict(legacy_payload)
                            merged_payload.update(candidate_data["cv_data"])
                            candidate_data["cv_data"] = merged_payload
                        else:
                            candidate_data["cv_data"] = legacy_payload
                if not candidate_data.get("storage_path"):
                    candidate_data["storage_path"] = legacy_cv.get("file_path")

            if candidate_data.get("cv_data"):
                candidate_data["filename"] = (
                    candidate_data["cv_data"].get("cv")
                    or candidate_data["cv_data"].get("filename")
                )

            if legacy_cv and legacy_cv.get("filename"):
                candidate_data["filename"] = legacy_cv.get("filename")

            if not candidate_data.get("filename") and candidate_data.get("storage_path"):
                candidate_data["filename"] = Path(candidate_data["storage_path"]).name

            if not candidate_data.get("filename") and legacy_cv:
                candidate_data["filename"] = legacy_cv.get("filename")

            tokens = _candidate_identity_tokens(candidate_data)
            seen_tokens.update(tokens)
            candidates.append(candidate_data)

        for cv in legacy_cvs:
            filename = (
                cv.get("filename")
                or (Path(cv["file_path"]).name if cv.get("file_path") else None)
            )

            candidate_data = {
                "source": "legacy",
                "filename": filename,
                "nom_complet": cv.get("candidat_nom"),
                "storage_path": cv.get("file_path"),
                "json_path": cv.get("json_path"),
                "cv_data": None,
            }

            tokens = _candidate_identity_tokens(candidate_data)
            if seen_tokens & tokens:
                continue

            cv_data = payloads_by_path.get(cv["json_path"]) if cv.get("json_path") else None
            candidate_data["cv_data"] = cv_data
            if not candidate_data.get("filename") and cv_data:
                candidate_data["filename"] = cv_data.get("cv")

            seen_tokens.update(tokens)
            candidates.append(candidate_data)

        return candidates
