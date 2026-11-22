from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy.exc import OperationalError
from sqlmodel import select

from brainrh.database import get_session_direct
from brainrh.models import TenantCvTemplateDB
from brainrh.services.enterprise_service import EnterpriseService
from brainrh.services.file_storage import FileStorage


def _collect_template_conflicts(enterprises: list[dict]) -> list[dict]:
    per_tenant: dict[str, list[dict]] = {}
    for enterprise in enterprises:
        tenant_id = enterprise.get("tenant_id")
        templates = enterprise.get("cv_templates") or []
        if not tenant_id or not isinstance(templates, list) or not templates:
            continue
        per_tenant.setdefault(str(tenant_id), []).extend(
            template
            for template in templates
            if isinstance(template, dict)
        )

    conflicts: list[dict] = []
    for tenant_id, templates in per_tenant.items():
        active_templates = [template for template in templates if template.get("is_active")]
        content_hashes = {
            str(template.get("content_hash") or "")
            for template in templates
            if template.get("content_hash")
        }
        if len(active_templates) > 1 or len(content_hashes) > 1:
            conflicts.append(
                {
                    "tenant_id": tenant_id,
                    "template_count": len(templates),
                    "active_template_ids": [str(template["id"]) for template in active_templates],
                    "content_hashes": sorted(content_hashes),
                }
            )
    return conflicts


def _copy_legacy_template_to_tenant(
    *,
    enterprise_id: str,
    tenant_id: str,
    template: dict,
    dry_run: bool,
) -> bool:
    template_id = str(template["id"])
    target_path = str(template.get("storage_path") or "").replace(
        f"enterprises/{enterprise_id}/cv_templates/",
        f"tenants/{tenant_id}/cv_templates/",
        1,
    )
    if not target_path.startswith(f"tenants/{tenant_id}/cv_templates/"):
        target_path = f"tenants/{tenant_id}/cv_templates/{template_id}/{template.get('original_filename', 'template.docx')}"

    if dry_run:
        print(
            json.dumps(
                {
                    "action": "would_copy_template",
                    "enterprise_id": enterprise_id,
                    "tenant_id": tenant_id,
                    "template_id": template_id,
                    "target_path": target_path,
                },
                ensure_ascii=False,
            )
        )
        return False

    payload = FileStorage.load_bytes(template["storage_path"])
    FileStorage.save_bytes(target_path, payload)

    metadata = {
        key: value
        for key, value in template.items()
        if key
        not in {
            "id",
            "tenant_id",
            "scope_kind",
            "name",
            "original_filename",
            "version",
            "storage_path",
            "content_hash",
            "is_valid",
            "is_active",
            "uploaded_by",
            "created_at",
            "activated_at",
        }
    }

    with get_session_direct() as session:
        existing = session.get(TenantCvTemplateDB, template_id)
        if existing:
            return False

        row = TenantCvTemplateDB(
            id=template_id,
            tenant_id=tenant_id,
            name=str(template.get("name") or "template"),
            original_filename=str(template.get("original_filename") or "template.docx"),
            version=int(template.get("version", 1)),
            storage_path=target_path,
            content_hash=str(template.get("content_hash") or ""),
            metadata_json=json.dumps(metadata, ensure_ascii=False),
            is_valid=bool(template.get("is_valid")),
            is_active=bool(template.get("is_active")),
            uploaded_by=str(template.get("uploaded_by") or ""),
            created_at=datetime.fromisoformat(str(template.get("created_at")).replace("Z", "+00:00")),
            activated_at=(
                datetime.fromisoformat(str(template.get("activated_at")).replace("Z", "+00:00"))
                if template.get("activated_at")
                else None
            ),
        )
        session.add(row)
        session.commit()

    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill enterprise CV templates into tenant-scoped templates.")
    parser.add_argument("--apply", action="store_true", help="Apply the migration. Default is dry-run.")
    args = parser.parse_args()

    dry_run = not args.apply
    created = 0

    try:
        enterprises = EnterpriseService.list_enterprises()
    except OperationalError as exc:
        raise SystemExit(
            "Database is not initialized for this environment. Run migrations and point the script at a valid BrainRH database before backfill."
        ) from exc

    conflicts = _collect_template_conflicts(enterprises)
    if conflicts:
        print(json.dumps({"conflicts": conflicts}, ensure_ascii=False))
        if not dry_run:
            raise SystemExit(
                "Template conflicts detected across enterprises of the same tenant. Resolve them before running --apply."
            )

    for enterprise in enterprises:
        enterprise_id = str(enterprise["id"])
        tenant_id = enterprise.get("tenant_id")
        templates = enterprise.get("cv_templates") or []
        if not tenant_id or not isinstance(templates, list) or not templates:
            continue

        for template in templates:
            if not isinstance(template, dict):
                continue
            created += int(
                _copy_legacy_template_to_tenant(
                    enterprise_id=enterprise_id,
                    tenant_id=str(tenant_id),
                    template=template,
                    dry_run=dry_run,
                )
            )

    with get_session_direct() as session:
        total = len(session.exec(select(TenantCvTemplateDB)).all())

    print(
        json.dumps(
            {
                "mode": "dry-run" if dry_run else "apply",
                "created": created,
                "tenant_template_count": total,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
