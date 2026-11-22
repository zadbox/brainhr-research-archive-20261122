from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlmodel import select

from brainrh.database import get_session
from brainrh.models import TenantCvTemplateDB
from brainrh.services.company_cv_mapping_service import (
    DOCX_CONTENT_TYPE,
    analyze_template_variables,
    build_template_contract,
    ensure_template_mapping_metadata,
    extract_template_variables,
)
from brainrh.services.company_cv_layout_spec_service import (
    LAYOUT_SPEC_VERSION,
    compile_layout_spec,
    update_layout_spec_confirmed_mappings,
)
from brainrh.services.enterprise_service import EnterpriseService
from brainrh.services.file_storage import FileStorage


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slugify_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip()).strip("-")
    return cleaned or "template.docx"


def _extract_variable_root(variable_name: str) -> str:
    root = re.split(r"[.\[\]\s|()]+", variable_name.strip())[0]
    return root


def _validate_docx_template(template_bytes: bytes) -> dict[str, Any]:
    detected_variables = extract_template_variables(template_bytes)
    analysis = analyze_template_variables(detected_variables)
    analysis.update(build_template_contract(analysis, template_bytes=template_bytes))
    return analysis


class CompanyCvTemplateService:
    @staticmethod
    def _tenant_template_metadata_payload(template: dict[str, Any]) -> dict[str, Any]:
        return {
            "detected_variables": template.get("detected_variables", []),
            "unsupported_variables": template.get("unsupported_variables", []),
            "supported_context_roots": template.get("supported_context_roots", []),
            "example_placeholders": template.get("example_placeholders", []),
            "resolved_placeholders": template.get("resolved_placeholders", []),
            "unknown_placeholders": template.get("unknown_placeholders", []),
            "ambiguous_placeholders": template.get("ambiguous_placeholders", []),
            "placeholder_mappings": template.get("placeholder_mappings", []),
            "mapping_version": template.get("mapping_version"),
            "mapper_version": template.get("mapper_version"),
            "contract_version": template.get("contract_version"),
            "template_contract": template.get("template_contract"),
            "slot_definitions": template.get("slot_definitions", []),
            "group_definitions": template.get("group_definitions", {}),
            "adapter_plan": template.get("adapter_plan", []),
            "template_text_outline": template.get("template_text_outline", ""),
            "slot_families": template.get("slot_families", {}),
            "section_slot_map": template.get("section_slot_map", {}),
            "render_mode": template.get("render_mode"),
            "layout_spec_version": template.get("layout_spec_version"),
            "layout_spec_status": template.get("layout_spec_status"),
            "layout_spec": template.get("layout_spec"),
            "layout_spec_errors": template.get("layout_spec_errors", []),
            "layout_spec_warnings": template.get("layout_spec_warnings", []),
        }

    @staticmethod
    def _ensure_layout_spec_metadata(
        template_record: dict[str, Any],
        *,
        template_bytes: bytes | None = None,
    ) -> dict[str, Any]:
        if (
            template_record.get("layout_spec_version") == LAYOUT_SPEC_VERSION
            and template_record.get("layout_spec_status")
            and "layout_spec" in template_record
        ):
            return dict(template_record)

        if template_bytes is None:
            storage_path = str(template_record.get("storage_path") or "")
            if not storage_path:
                return {
                    **template_record,
                    "render_mode": "legacy_docxtpl",
                    "layout_spec_version": LAYOUT_SPEC_VERSION,
                    "layout_spec_status": "unsupported",
                    "layout_spec": {},
                    "layout_spec_errors": ["Missing template storage path for layout compilation."],
                    "layout_spec_warnings": [],
                }
            try:
                template_bytes = FileStorage.load_bytes(storage_path)
            except Exception as exc:  # pragma: no cover - defensive fallback
                return {
                    **template_record,
                    "render_mode": "legacy_docxtpl",
                    "layout_spec_version": LAYOUT_SPEC_VERSION,
                    "layout_spec_status": "unsupported",
                    "layout_spec": {},
                    "layout_spec_errors": [f"Unable to load template bytes for layout compilation: {exc}"],
                    "layout_spec_warnings": [],
                }

        compiled = compile_layout_spec(
            template_bytes=template_bytes,
            detected_variables=template_record.get("detected_variables", []),
        )
        updated = dict(template_record)
        updated.update(compiled)
        return updated

    @staticmethod
    def _promote_first_valid_tenant_template_if_needed(tenant_id: str) -> None:
        with get_session() as session:
            rows = session.exec(
                select(TenantCvTemplateDB).where(TenantCvTemplateDB.tenant_id == tenant_id)
            ).all()
            if not rows:
                return
            if any(row.is_active for row in rows):
                return

            valid_rows = [row for row in rows if row.is_valid]
            if not valid_rows:
                return

            selected = max(
                valid_rows,
                key=lambda row: (int(row.version or 0), row.created_at),
            )
            selected.is_active = True
            selected.activated_at = datetime.now(timezone.utc)
            session.add(selected)
            session.commit()

    @staticmethod
    def _promote_first_valid_enterprise_template_if_needed(
        enterprise_id: str,
        templates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if any(bool(template.get("is_active")) for template in templates):
            return templates

        valid_templates = [template for template in templates if template.get("is_valid")]
        if not valid_templates:
            return templates

        selected = max(
            valid_templates,
            key=lambda template: (
                int(template.get("version", 0)),
                template.get("created_at", ""),
            ),
        )
        now = _now_iso()
        next_templates: list[dict[str, Any]] = []
        for template in templates:
            updated = dict(template)
            if template.get("id") == selected.get("id"):
                updated["is_active"] = True
                updated["activated_at"] = now
            next_templates.append(updated)
        return next_templates

    @staticmethod
    def _serialize_tenant_template(row: TenantCvTemplateDB) -> dict[str, Any]:
        metadata = json.loads(row.metadata_json or "{}")
        return {
            "id": row.id,
            "tenant_id": row.tenant_id,
            "scope_kind": "tenant",
            "name": row.name,
            "original_filename": row.original_filename,
            "version": row.version,
            "storage_path": row.storage_path,
            "content_hash": row.content_hash,
            "is_valid": row.is_valid,
            "is_active": row.is_active,
            "uploaded_by": row.uploaded_by,
            "created_at": row.created_at.isoformat(),
            "activated_at": row.activated_at.isoformat() if row.activated_at else None,
            **metadata,
        }

    @staticmethod
    def _tenant_id_for_enterprise(enterprise: dict[str, Any], enterprise_id: str) -> str | None:
        tenant_id = enterprise.get("tenant_id") or EnterpriseService.get_enterprise_tenant_id(enterprise_id)
        if not tenant_id:
            return None
        return str(tenant_id)

    @staticmethod
    def _list_tenant_templates(tenant_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            rows = session.exec(
                select(TenantCvTemplateDB).where(TenantCvTemplateDB.tenant_id == tenant_id)
            ).all()
            templates = [CompanyCvTemplateService._serialize_tenant_template(row) for row in rows]
        return CompanyCvTemplateService._sorted_templates(templates)

    @staticmethod
    def _upgrade_tenant_template_records(tenant_id: str, templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        upgraded_templates = []
        changed = False
        for template in templates:
            upgraded = ensure_template_mapping_metadata(template)
            upgraded = CompanyCvTemplateService._ensure_layout_spec_metadata(upgraded)
            if upgraded != template:
                changed = True
            upgraded_templates.append(upgraded)

        if not changed:
            return upgraded_templates

        with get_session() as session:
            rows = session.exec(
                select(TenantCvTemplateDB).where(TenantCvTemplateDB.tenant_id == tenant_id)
            ).all()
            row_by_id = {row.id: row for row in rows}
            for template in upgraded_templates:
                row = row_by_id.get(template.get("id"))
                if row is None:
                    continue
                row.metadata_json = json.dumps(
                    CompanyCvTemplateService._tenant_template_metadata_payload(template),
                    ensure_ascii=False,
                )
                row.is_valid = bool(template.get("is_valid"))
                session.add(row)
            session.commit()

        CompanyCvTemplateService._sync_tenant_templates_to_enterprises(tenant_id)
        return CompanyCvTemplateService._sorted_templates(upgraded_templates)

    @staticmethod
    def _replace_active_tenant_template_flags(tenant_id: str, template_id: str, now: datetime) -> dict[str, Any]:
        with get_session() as session:
            rows = session.exec(
                select(TenantCvTemplateDB).where(TenantCvTemplateDB.tenant_id == tenant_id)
            ).all()
            selected: TenantCvTemplateDB | None = None
            for row in rows:
                is_selected = row.id == template_id
                row.is_active = is_selected
                if is_selected:
                    row.activated_at = now
                    selected = row
                session.add(row)
            session.commit()
            if selected is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"CV template {template_id} not found for tenant {tenant_id}.",
                )
            session.refresh(selected)
            selected_record = CompanyCvTemplateService._serialize_tenant_template(selected)
        CompanyCvTemplateService._sync_tenant_templates_to_enterprises(tenant_id)
        return selected_record

    @staticmethod
    def _sync_tenant_templates_to_enterprises(tenant_id: str) -> None:
        tenant_templates = CompanyCvTemplateService._list_tenant_templates(tenant_id)
        for enterprise in EnterpriseService.list_enterprises_by_tenant(tenant_id):
            EnterpriseService.update_enterprise(
                enterprise["id"],
                {"cv_templates": tenant_templates},
            )

    @staticmethod
    def _upgrade_template_records(
        enterprise_id: str,
        templates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        upgraded_templates = []
        changed = False
        for template in templates:
            upgraded = ensure_template_mapping_metadata(template)
            upgraded = CompanyCvTemplateService._ensure_layout_spec_metadata(upgraded)
            if upgraded != template:
                changed = True
            upgraded_templates.append(upgraded)

        if changed:
            EnterpriseService.update_enterprise(enterprise_id, {"cv_templates": upgraded_templates})
        return upgraded_templates

    @staticmethod
    def _load_enterprise_or_404(enterprise_id: str) -> dict[str, Any]:
        enterprise = EnterpriseService.get_enterprise(enterprise_id)
        if not enterprise:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Enterprise {enterprise_id} not found.",
            )
        return enterprise

    @staticmethod
    def _sorted_templates(templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            templates,
            key=lambda item: (
                not bool(item.get("is_active")),
                -int(item.get("version", 0)),
                item.get("created_at", ""),
            ),
        )

    @staticmethod
    def list_templates(enterprise_id: str) -> list[dict[str, Any]]:
        enterprise = CompanyCvTemplateService._load_enterprise_or_404(enterprise_id)
        tenant_id = CompanyCvTemplateService._tenant_id_for_enterprise(enterprise, enterprise_id)
        if tenant_id:
            tenant_templates = CompanyCvTemplateService._list_tenant_templates(tenant_id)
            if tenant_templates:
                return CompanyCvTemplateService._upgrade_tenant_template_records(tenant_id, tenant_templates)
        templates = enterprise.get("cv_templates") or []
        if not isinstance(templates, list):
            templates = []
        templates = CompanyCvTemplateService._upgrade_template_records(enterprise_id, templates)
        return CompanyCvTemplateService._sorted_templates(templates)

    @staticmethod
    def get_template(enterprise_id: str, template_id: str) -> dict[str, Any]:
        templates = CompanyCvTemplateService.list_templates(enterprise_id)
        for template in templates:
            if template.get("id") == template_id:
                return template
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CV template {template_id} not found for enterprise {enterprise_id}.",
        )

    @staticmethod
    def get_active_template(enterprise_id: str) -> dict[str, Any]:
        templates = CompanyCvTemplateService.list_templates(enterprise_id)
        for template in templates:
            if template.get("is_active"):
                return template
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active CV template configured for enterprise {enterprise_id}.",
        )

    @staticmethod
    def upload_template(
        *,
        enterprise_id: str,
        original_filename: str,
        template_bytes: bytes,
        uploaded_by: str,
    ) -> dict[str, Any]:
        enterprise = CompanyCvTemplateService._load_enterprise_or_404(enterprise_id)
        tenant_id = CompanyCvTemplateService._tenant_id_for_enterprise(enterprise, enterprise_id)
        templates = CompanyCvTemplateService._list_tenant_templates(tenant_id) if tenant_id else (
            enterprise.get("cv_templates") or []
        )
        if not isinstance(templates, list):
            templates = []

        if not original_filename.lower().endswith(".docx"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only .docx templates are supported.",
            )

        validation_report = _validate_docx_template(template_bytes)
        template_id = str(uuid.uuid4())
        version = max((int(item.get("version", 0)) for item in templates), default=0) + 1
        content_hash = hashlib.sha256(template_bytes).hexdigest()
        safe_filename = _slugify_filename(original_filename)
        storage_path = (
            f"tenants/{tenant_id}/cv_templates/{template_id}/{safe_filename}"
            if tenant_id
            else f"enterprises/{enterprise_id}/cv_templates/{template_id}/{safe_filename}"
        )
        FileStorage.save_bytes(storage_path, template_bytes, content_type=DOCX_CONTENT_TYPE)

        should_activate = validation_report["is_valid"] and not any(
            item.get("is_active") for item in templates
        )
        now = _now_iso()
        template_record = {
            "id": template_id,
            "name": Path(original_filename).stem,
            "original_filename": original_filename,
            "version": version,
            "storage_path": storage_path,
            "content_hash": content_hash,
            "detected_variables": validation_report["detected_variables"],
            "unsupported_variables": validation_report["unsupported_variables"],
            "supported_context_roots": validation_report["supported_context_roots"],
            "example_placeholders": validation_report["example_placeholders"],
            "resolved_placeholders": validation_report["resolved_placeholders"],
            "unknown_placeholders": validation_report["unknown_placeholders"],
            "ambiguous_placeholders": validation_report["ambiguous_placeholders"],
            "placeholder_mappings": validation_report["placeholder_mappings"],
            "mapping_version": validation_report["mapping_version"],
            "mapper_version": validation_report["mapper_version"],
            "contract_version": validation_report["contract_version"],
            "template_contract": validation_report["template_contract"],
            "slot_definitions": validation_report["slot_definitions"],
            "group_definitions": validation_report["group_definitions"],
            "adapter_plan": validation_report["adapter_plan"],
            "template_text_outline": validation_report["template_text_outline"],
            "slot_families": validation_report["slot_families"],
            "section_slot_map": validation_report["section_slot_map"],
            "is_valid": validation_report["is_valid"],
            "is_active": should_activate,
            "uploaded_by": uploaded_by,
            "created_at": now,
            "activated_at": now if should_activate else None,
        }
        template_record.update(
            compile_layout_spec(
                template_bytes=template_bytes,
                detected_variables=validation_report["detected_variables"],
            )
        )

        if tenant_id:
            metadata_json = json.dumps(
                CompanyCvTemplateService._tenant_template_metadata_payload(template_record),
                ensure_ascii=False,
            )
            with get_session() as session:
                row = TenantCvTemplateDB(
                    id=template_id,
                    tenant_id=tenant_id,
                    name=template_record["name"],
                    original_filename=original_filename,
                    version=version,
                    storage_path=storage_path,
                    content_hash=content_hash,
                    metadata_json=metadata_json,
                    is_valid=validation_report["is_valid"],
                    is_active=should_activate,
                    uploaded_by=uploaded_by,
                    created_at=datetime.fromisoformat(now),
                    activated_at=datetime.fromisoformat(now) if should_activate else None,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                record = CompanyCvTemplateService._serialize_tenant_template(row)
            CompanyCvTemplateService._sync_tenant_templates_to_enterprises(tenant_id)
            return record

        templates.append(template_record)
        EnterpriseService.update_enterprise(enterprise_id, {"cv_templates": templates})
        return template_record

    @staticmethod
    def activate_template(enterprise_id: str, template_id: str) -> dict[str, Any]:
        enterprise = CompanyCvTemplateService._load_enterprise_or_404(enterprise_id)
        tenant_id = CompanyCvTemplateService._tenant_id_for_enterprise(enterprise, enterprise_id)
        if tenant_id:
            templates = CompanyCvTemplateService._list_tenant_templates(tenant_id)
            if templates:
                selected = next((template for template in templates if template.get("id") == template_id), None)
                if selected is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"CV template {template_id} not found for tenant {tenant_id}.",
                    )
                if not selected.get("is_valid", False):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Only templates with a complete deterministic placeholder mapping can be activated.",
                    )
                return CompanyCvTemplateService._replace_active_tenant_template_flags(
                    tenant_id,
                    template_id,
                    datetime.now(timezone.utc),
                )

        templates = enterprise.get("cv_templates") or []
        if not isinstance(templates, list):
            templates = []

        selected = None
        now = _now_iso()
        for template in templates:
            if template.get("id") == template_id:
                selected = template
                break

        if selected is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"CV template {template_id} not found for enterprise {enterprise_id}.",
            )

        if not selected.get("is_valid", False):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only templates with a complete deterministic placeholder mapping can be activated.",
            )

        for template in templates:
            is_selected = template.get("id") == template_id
            template["is_active"] = is_selected
            template["activated_at"] = now if is_selected else template.get("activated_at")

        EnterpriseService.update_enterprise(enterprise_id, {"cv_templates": templates})
        return next(template for template in templates if template.get("id") == template_id)

    @staticmethod
    def load_template_bytes(enterprise_id: str, template_id: str | None = None) -> tuple[dict[str, Any], bytes]:
        template = (
            CompanyCvTemplateService.get_template(enterprise_id, template_id)
            if template_id
            else CompanyCvTemplateService.get_active_template(enterprise_id)
        )
        return template, FileStorage.load_bytes(template["storage_path"])

    @staticmethod
    def delete_template(enterprise_id: str, template_id: str) -> None:
        enterprise = CompanyCvTemplateService._load_enterprise_or_404(enterprise_id)
        tenant_id = CompanyCvTemplateService._tenant_id_for_enterprise(enterprise, enterprise_id)
        if tenant_id:
            with get_session() as session:
                row = session.exec(
                    select(TenantCvTemplateDB).where(
                        TenantCvTemplateDB.tenant_id == tenant_id,
                        TenantCvTemplateDB.id == template_id,
                    )
                ).first()
                if row is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"CV template {template_id} not found for tenant {tenant_id}.",
                    )
                storage_path = row.storage_path
                session.delete(row)
                session.commit()
            if storage_path:
                try:
                    FileStorage.delete_file(storage_path)
                except FileNotFoundError:
                    pass
            CompanyCvTemplateService._promote_first_valid_tenant_template_if_needed(tenant_id)
            CompanyCvTemplateService._sync_tenant_templates_to_enterprises(tenant_id)
            return

        templates = enterprise.get("cv_templates") or []
        if not isinstance(templates, list):
            templates = []

        selected = next((template for template in templates if template.get("id") == template_id), None)
        if selected is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"CV template {template_id} not found for enterprise {enterprise_id}.",
            )

        remaining_templates = [template for template in templates if template.get("id") != template_id]
        remaining_templates = CompanyCvTemplateService._promote_first_valid_enterprise_template_if_needed(
            enterprise_id,
            remaining_templates,
        )
        EnterpriseService.update_enterprise(enterprise_id, {"cv_templates": remaining_templates})
        storage_path = selected.get("storage_path")
        if storage_path:
            try:
                FileStorage.delete_file(storage_path)
            except FileNotFoundError:
                pass

    @staticmethod
    def update_template_mapping(
        *,
        enterprise_id: str,
        template_id: str,
        confirmed_mappings: dict[str, Any],
    ) -> dict[str, Any]:
        enterprise = CompanyCvTemplateService._load_enterprise_or_404(enterprise_id)
        tenant_id = CompanyCvTemplateService._tenant_id_for_enterprise(enterprise, enterprise_id)

        if tenant_id:
            with get_session() as session:
                row = session.exec(
                    select(TenantCvTemplateDB).where(
                        TenantCvTemplateDB.tenant_id == tenant_id,
                        TenantCvTemplateDB.id == template_id,
                    )
                ).first()
                if row is None:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"CV template {template_id} not found for tenant {tenant_id}.",
                    )
                template_record = CompanyCvTemplateService._serialize_tenant_template(row)
                template_record = CompanyCvTemplateService._ensure_layout_spec_metadata(template_record)
                layout_payload = update_layout_spec_confirmed_mappings(
                    layout_spec=template_record.get("layout_spec") or {},
                    confirmed_mappings=confirmed_mappings,
                )
                template_record.update(layout_payload)
                row.metadata_json = json.dumps(
                    CompanyCvTemplateService._tenant_template_metadata_payload(template_record),
                    ensure_ascii=False,
                )
                session.add(row)
                session.commit()
                session.refresh(row)
                updated = CompanyCvTemplateService._serialize_tenant_template(row)
            CompanyCvTemplateService._sync_tenant_templates_to_enterprises(tenant_id)
            return updated

        templates = enterprise.get("cv_templates") or []
        if not isinstance(templates, list):
            templates = []
        updated_record = None
        next_templates: list[dict[str, Any]] = []
        for template in templates:
            current = dict(template)
            if template.get("id") == template_id:
                current = CompanyCvTemplateService._ensure_layout_spec_metadata(current)
                current.update(
                    update_layout_spec_confirmed_mappings(
                        layout_spec=current.get("layout_spec") or {},
                        confirmed_mappings=confirmed_mappings,
                    )
                )
                updated_record = current
            next_templates.append(current)
        if updated_record is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"CV template {template_id} not found for enterprise {enterprise_id}.",
            )
        EnterpriseService.update_enterprise(enterprise_id, {"cv_templates": next_templates})
        return updated_record
