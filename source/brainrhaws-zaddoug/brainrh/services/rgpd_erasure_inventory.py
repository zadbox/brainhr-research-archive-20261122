"""Read-only candidate erasure inventory with a deliberately narrow scope."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

from sqlalchemy import inspect, text
from sqlmodel import Session, select

from brainrh.models.application import ApplicationDB
from brainrh.models.project import ProjectDB
from brainrh.models.resume_version import ResumeVersionDB
from brainrh.models.talent_profile import TalentProfileDB
from brainrh.models.crustdata import CrustdataIdentityDB, CrustdataIdentityEnterpriseDB, CrustdataSearchResultDB


SCOPE_VERSION = "candidate-erasure-inventory-v1"


class SubjectNotFoundError(LookupError):
    """Raised without echoing identifiers when the tenant-scoped subject is absent."""


class StorageReader(Protocol):
    def exists(self, key: str) -> bool:
        """Return whether a storage key exists without mutating it."""


@dataclass(frozen=True)
class ResolvedStore:
    store: str
    status: str
    records: int


@dataclass(frozen=True)
class StorageStore:
    store: str
    status: str
    referenced_objects: int
    present_objects: int
    not_confirmed_objects: int
    probe_error_objects: int
    resume_versions_without_storage_path: int


@dataclass(frozen=True)
class UnresolvedStore:
    store: str
    status: str
    reason: str
    related_project_count: int


@dataclass(frozen=True)
class ErasureInventoryReport:
    schema_version: int
    scope_version: str
    mode: str
    report_id: str
    generated_at: str
    subject_present: bool
    complete: bool
    resolved_stores: tuple[ResolvedStore, ...]
    storage_stores: tuple[StorageStore, ...]
    unresolved_stores: tuple[UnresolvedStore, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def begin_read_only_snapshot(session: Session) -> None:
    """Start the consistent PostgreSQL snapshot required by the operational CLI."""

    session.exec(
        text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
    )


def _storage_status(*, not_confirmed: int, probe_errors: int, unlinked: int) -> str:
    if probe_errors:
        return "PARTIAL_PROBE_ERROR"
    if not_confirmed or unlinked:
        return "PARTIAL_NOT_CONFIRMED"
    return "RESOLVED"


def build_erasure_inventory(
    session: Session,
    storage: StorageReader,
    *,
    enterprise_id: str,
    talent_profile_id: int,
) -> ErasureInventoryReport:
    """Inventory only deterministic links; never inspect unstructured PII content."""

    normalized_enterprise_id = str(enterprise_id or "").strip()
    if not normalized_enterprise_id or talent_profile_id <= 0:
        raise ValueError("Tenant scope and positive talent profile id are required")

    profile = session.exec(
        select(TalentProfileDB.id).where(
            TalentProfileDB.id == talent_profile_id,
            TalentProfileDB.enterprise_id == normalized_enterprise_id,
        )
    ).first()
    if profile is None:
        raise SubjectNotFoundError("Tenant-scoped subject not found")

    resume_rows = session.exec(
        select(ResumeVersionDB.id, ResumeVersionDB.storage_path).where(
            ResumeVersionDB.enterprise_id == normalized_enterprise_id,
            ResumeVersionDB.talent_profile_id == talent_profile_id,
        )
    ).all()
    application_rows = session.exec(
        select(ApplicationDB.id, ApplicationDB.project_id).where(
            ApplicationDB.enterprise_id == normalized_enterprise_id,
            ApplicationDB.talent_profile_id == talent_profile_id,
        )
    ).all()
    crustdata_tables_present = all(
        inspect(session.get_bind()).has_table(table)
        for table in ("crustdata_identities", "crustdata_identity_enterprises", "crustdata_search_results")
    )
    crustdata_identities = session.exec(
        select(CrustdataIdentityDB).join(
            CrustdataIdentityEnterpriseDB,
            CrustdataIdentityEnterpriseDB.identity_id == CrustdataIdentityDB.id,
        ).where(
            CrustdataIdentityEnterpriseDB.enterprise_id == normalized_enterprise_id,
            CrustdataIdentityEnterpriseDB.talent_profile_id == talent_profile_id,
        )
    ).all() if crustdata_tables_present else []
    identity_person_ids = [row.provider_person_id for row in crustdata_identities]
    crustdata_results = session.exec(
        select(CrustdataSearchResultDB.id).where(
            CrustdataSearchResultDB.enterprise_id == normalized_enterprise_id,
            CrustdataSearchResultDB.provider_person_id.in_(identity_person_ids),
        )
    ).all() if crustdata_tables_present and identity_person_ids else []
    validated_project_ids = session.exec(
        select(ProjectDB.id)
        .join(ApplicationDB, ApplicationDB.project_id == ProjectDB.id)
        .where(
            ApplicationDB.enterprise_id == normalized_enterprise_id,
            ApplicationDB.talent_profile_id == talent_profile_id,
            ProjectDB.enterprise_id == normalized_enterprise_id,
        )
        .distinct()
    ).all()

    storage_paths = sorted(
        {
            str(row.storage_path).strip()
            for row in resume_rows
            if row.storage_path and str(row.storage_path).strip()
        }
    )
    crustdata_snapshot_paths = sorted({
        str(row.raw_snapshot_path).strip()
        for row in crustdata_identities
        if row.raw_snapshot_path and str(row.raw_snapshot_path).strip()
    })
    present_objects = 0
    not_confirmed_objects = 0
    probe_error_objects = 0
    for storage_path in storage_paths:
        try:
            if storage.exists(storage_path):
                present_objects += 1
            else:
                # The current storage abstraction intentionally hides provider
                # errors, so False cannot be asserted as a confirmed absence.
                not_confirmed_objects += 1
        except Exception:
            # Do not leak bucket names, keys, credentials or provider errors.
            probe_error_objects += 1

    unlinked_resume_versions = sum(
        1
        for row in resume_rows
        if not row.storage_path or not str(row.storage_path).strip()
    )
    crustdata_present = 0
    crustdata_not_confirmed = 0
    crustdata_probe_errors = 0
    for storage_path in crustdata_snapshot_paths:
        try:
            if storage.exists(storage_path): crustdata_present += 1
            else: crustdata_not_confirmed += 1
        except Exception:
            crustdata_probe_errors += 1

    application_project_count = len({str(row.project_id) for row in application_rows})
    project_count = len(validated_project_ids)
    project_link_status = (
        "RESOLVED"
        if project_count == application_project_count
        else "INTEGRITY_GAP"
    )
    unresolved = (
        ("legacy_cv_and_project_files", "NO_STABLE_TALENT_PROFILE_LINK"),
        ("matching_results_and_exports", "UNSTRUCTURED_PROJECT_ARTIFACTS"),
        ("interview_sheets_and_company_cv", "CANDIDATE_REFERENCE_NOT_CANONICAL"),
        ("realtime_interviews_and_appointments", "TENANT_SUBJECT_LINK_NOT_PERSISTED"),
        ("webhooks_and_delivery_attempts", "SUBJECT_LINK_EMBEDDED_IN_PAYLOAD"),
        ("provider_copies", "PROVIDER_RECONCILIATION_REQUIRED"),
        ("logs_and_backups", "CONTENT_NOT_CANDIDATE_INDEXED"),
    )

    return ErasureInventoryReport(
        schema_version=1,
        scope_version=SCOPE_VERSION,
        mode="DRY_RUN_READ_ONLY",
        report_id=str(uuid4()),
        generated_at=datetime.now(timezone.utc).isoformat(),
        subject_present=True,
        complete=False,
        resolved_stores=(
            ResolvedStore("talent_profiles", "RESOLVED", 1),
            ResolvedStore("resume_versions", "RESOLVED", len(resume_rows)),
            ResolvedStore("applications", "RESOLVED", len(application_rows)),
            ResolvedStore("application_project_links", project_link_status, project_count),
            ResolvedStore("crustdata_identities", "RESOLVED", len(crustdata_identities)),
            ResolvedStore("crustdata_search_results", "RESOLVED", len(crustdata_results)),
        ),
        storage_stores=(
            StorageStore(
                store="resume_storage_objects",
                status=_storage_status(
                    not_confirmed=not_confirmed_objects,
                    probe_errors=probe_error_objects,
                    unlinked=unlinked_resume_versions,
                ),
                referenced_objects=len(storage_paths),
                present_objects=present_objects,
                not_confirmed_objects=not_confirmed_objects,
                probe_error_objects=probe_error_objects,
                resume_versions_without_storage_path=unlinked_resume_versions,
            ),
            StorageStore(
                store="crustdata_raw_snapshots",
                status=_storage_status(
                    not_confirmed=crustdata_not_confirmed,
                    probe_errors=crustdata_probe_errors,
                    unlinked=sum(1 for row in crustdata_identities if not row.raw_snapshot_path),
                ),
                referenced_objects=len(crustdata_snapshot_paths),
                present_objects=crustdata_present,
                not_confirmed_objects=crustdata_not_confirmed,
                probe_error_objects=crustdata_probe_errors,
                resume_versions_without_storage_path=sum(1 for row in crustdata_identities if not row.raw_snapshot_path),
            ),
        ),
        unresolved_stores=tuple(
            UnresolvedStore(
                store=store,
                status="MAPPING_REQUIRED",
                reason=reason,
                related_project_count=project_count,
            )
            for store, reason in unresolved
        ),
    )
