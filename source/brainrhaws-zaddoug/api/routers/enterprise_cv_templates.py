from __future__ import annotations

from io import BytesIO
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from api.dependencies import get_current_user, get_tenant_context_for_user, require_tenant_roles
from brainrh.models.auth import UserDB, UserRole
from brainrh.services.enterprise_service import EnterpriseService
from brainrh.services.auth_service import TenantContext, tenant_has_any_role
from brainrh.services.company_cv_template_service import (
    DOCX_CONTENT_TYPE,
    CompanyCvTemplateService,
)
from brainrh.services.company_cv_html_renderer import CompanyCvHtmlRenderService
from brainrh.services.company_cv_render_service import CompanyCvRenderService

router = APIRouter(tags=["Enterprise CV Templates"])


class EnterpriseCvTemplateResponse(BaseModel):
    id: str
    tenant_id: Optional[str] = None
    scope_kind: Optional[str] = None
    name: str
    original_filename: str
    version: int
    detected_variables: list[str] = Field(default_factory=list)
    resolved_placeholders: list[str] = Field(default_factory=list)
    unknown_placeholders: list[str] = Field(default_factory=list)
    ambiguous_placeholders: list[str] = Field(default_factory=list)
    unsupported_variables: list[str] = Field(default_factory=list)
    supported_context_roots: list[str] = Field(default_factory=list)
    example_placeholders: list[str] = Field(default_factory=list)
    mapping_version: Optional[str] = None
    mapper_version: Optional[str] = None
    template_text_outline: str = ""
    slot_families: dict[str, str] = Field(default_factory=dict)
    section_slot_map: dict[str, list[str]] = Field(default_factory=dict)
    render_mode: Optional[str] = None
    layout_spec_version: Optional[str] = None
    layout_spec_status: Optional[str] = None
    layout_spec: Optional[dict[str, Any]] = None
    layout_spec_errors: list[str] = Field(default_factory=list)
    layout_spec_warnings: list[str] = Field(default_factory=list)
    is_valid: bool
    is_active: bool
    created_at: str
    activated_at: Optional[str] = None


class TemplateMappingUpdateRequest(BaseModel):
    confirmed_mappings: dict[str, Any] = Field(default_factory=dict)


class TemplateSampleRenderRequest(BaseModel):
    sheet_id: str


def _enterprise_reader(enterprise_id: str, current_user: UserDB) -> TenantContext:
    return get_tenant_context_for_user(current_user, enterprise_id)


def _enterprise_admin(enterprise_id: str, current_user: UserDB) -> TenantContext:
    tenant = get_tenant_context_for_user(current_user, enterprise_id)
    require_tenant_roles(tenant, {UserRole.enterprise_admin})
    return tenant


def _require_safe_template_mutation_scope(tenant: TenantContext) -> None:
    if not tenant.tenant_id or not tenant.enterprise_id:
        return
    enterprises = EnterpriseService.list_enterprises_by_tenant(tenant.tenant_id)
    if len(enterprises) > 1 and not tenant_has_any_role(tenant, {UserRole.client_admin}):
        raise HTTPException(
            status_code=403,
            detail=(
                "This CV template is shared across multiple enterprises of the same client. "
                "A client_admin or platform_admin is required for tenant-scoped template mutations."
            ),
        )


@router.get("/{enterprise_id}/cv-templates", response_model=list[EnterpriseCvTemplateResponse])
async def list_enterprise_cv_templates(
    enterprise_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    _enterprise_reader(enterprise_id, current_user)
    templates = CompanyCvTemplateService.list_templates(enterprise_id)
    return [EnterpriseCvTemplateResponse(**_public_template(template)) for template in templates]


@router.post("/{enterprise_id}/cv-templates", response_model=EnterpriseCvTemplateResponse)
async def upload_enterprise_cv_template(
    enterprise_id: str,
    file: UploadFile = File(...),
    current_user: UserDB = Depends(get_current_user),
):
    tenant = _enterprise_admin(enterprise_id, current_user)
    _require_safe_template_mutation_scope(tenant)
    payload = await file.read()
    template = CompanyCvTemplateService.upload_template(
        enterprise_id=enterprise_id,
        original_filename=file.filename or "template.docx",
        template_bytes=payload,
        uploaded_by=str(current_user.id),
    )
    return EnterpriseCvTemplateResponse(**_public_template(template))


@router.post("/{enterprise_id}/cv-templates/{template_id}/activate", response_model=EnterpriseCvTemplateResponse)
async def activate_enterprise_cv_template(
    enterprise_id: str,
    template_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    tenant = _enterprise_admin(enterprise_id, current_user)
    _require_safe_template_mutation_scope(tenant)
    template = CompanyCvTemplateService.activate_template(enterprise_id, template_id)
    return EnterpriseCvTemplateResponse(**_public_template(template))


@router.get("/{enterprise_id}/cv-templates/{template_id}/download")
async def download_enterprise_cv_template(
    enterprise_id: str,
    template_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    _enterprise_reader(enterprise_id, current_user)
    template, payload = CompanyCvTemplateService.load_template_bytes(enterprise_id, template_id)
    filename = template.get("original_filename") or f"{template.get('name', 'template')}.docx"

    return StreamingResponse(
        BytesIO(payload),
        media_type=DOCX_CONTENT_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{enterprise_id}/cv-templates/{template_id}/mapping", response_model=EnterpriseCvTemplateResponse)
async def get_enterprise_cv_template_mapping(
    enterprise_id: str,
    template_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    _enterprise_reader(enterprise_id, current_user)
    template = CompanyCvTemplateService.get_template(enterprise_id, template_id)
    return EnterpriseCvTemplateResponse(**_public_template(template))


@router.put("/{enterprise_id}/cv-templates/{template_id}/mapping", response_model=EnterpriseCvTemplateResponse)
async def update_enterprise_cv_template_mapping(
    enterprise_id: str,
    template_id: str,
    payload: TemplateMappingUpdateRequest,
    current_user: UserDB = Depends(get_current_user),
):
    tenant = _enterprise_admin(enterprise_id, current_user)
    _require_safe_template_mutation_scope(tenant)
    template = CompanyCvTemplateService.update_template_mapping(
        enterprise_id=enterprise_id,
        template_id=template_id,
        confirmed_mappings=payload.confirmed_mappings,
    )
    return EnterpriseCvTemplateResponse(**_public_template(template))


@router.post("/{enterprise_id}/cv-templates/{template_id}/sample-render")
async def sample_render_enterprise_cv_template(
    enterprise_id: str,
    template_id: str,
    payload: TemplateSampleRenderRequest,
    current_user: UserDB = Depends(get_current_user),
):
    _enterprise_reader(enterprise_id, current_user)
    rendered = await run_in_threadpool(
        CompanyCvRenderService.render_company_cv,
        payload.sheet_id,
        template_id,
    )
    return StreamingResponse(
        BytesIO(rendered["bytes"]),
        media_type=rendered["content_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{rendered["filename"]}"',
            "X-Company-CV-Template-Id": str(rendered["template"].get("id") or ""),
            "X-Company-CV-Render-Fingerprint": str(rendered["render_fingerprint"]),
        },
    )


@router.post("/{enterprise_id}/cv-templates/{template_id}/sample-render/html-docx")
async def sample_render_enterprise_cv_template_html_docx(
    enterprise_id: str,
    template_id: str,
    payload: TemplateSampleRenderRequest,
    current_user: UserDB = Depends(get_current_user),
):
    _enterprise_reader(enterprise_id, current_user)
    rendered = await run_in_threadpool(
        CompanyCvHtmlRenderService.render_company_cv_html_docx,
        payload.sheet_id,
        template_id,
    )
    renderer = rendered.get("renderer") or {}
    return StreamingResponse(
        BytesIO(rendered["bytes"]),
        media_type=rendered["content_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{rendered["filename"]}"',
            "X-Company-Cv-Renderer": str(renderer.get("mode") or "html_docx"),
            "X-Company-Cv-Renderer-Version": str(renderer.get("version") or ""),
            "X-Company-CV-Template-Id": str(rendered["template"].get("id") or ""),
            "X-Company-CV-Render-Fingerprint": str(rendered["render_fingerprint"]),
        },
    )


@router.delete("/{enterprise_id}/cv-templates/{template_id}", status_code=204)
async def delete_enterprise_cv_template(
    enterprise_id: str,
    template_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    tenant = _enterprise_admin(enterprise_id, current_user)
    _require_safe_template_mutation_scope(tenant)
    CompanyCvTemplateService.delete_template(enterprise_id, template_id)
    return Response(status_code=204)


def _public_template(template: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": template["id"],
        "tenant_id": template.get("tenant_id"),
        "scope_kind": template.get("scope_kind"),
        "name": template["name"],
        "original_filename": template["original_filename"],
        "version": template["version"],
        "detected_variables": template.get("detected_variables", []),
        "resolved_placeholders": template.get("resolved_placeholders", []),
        "unknown_placeholders": template.get("unknown_placeholders", []),
        "ambiguous_placeholders": template.get("ambiguous_placeholders", []),
        "unsupported_variables": template.get("unsupported_variables", []),
        "supported_context_roots": template.get("supported_context_roots", []),
        "example_placeholders": template.get("example_placeholders", []),
        "mapping_version": template.get("mapping_version"),
        "mapper_version": template.get("mapper_version"),
        "template_text_outline": template.get("template_text_outline", ""),
        "slot_families": template.get("slot_families", {}),
        "section_slot_map": template.get("section_slot_map", {}),
        "render_mode": template.get("render_mode"),
        "layout_spec_version": template.get("layout_spec_version"),
        "layout_spec_status": template.get("layout_spec_status"),
        "layout_spec": template.get("layout_spec"),
        "layout_spec_errors": template.get("layout_spec_errors", []),
        "layout_spec_warnings": template.get("layout_spec_warnings", []),
        "is_valid": bool(template.get("is_valid")),
        "is_active": bool(template.get("is_active")),
        "created_at": template.get("created_at", ""),
        "activated_at": template.get("activated_at"),
    }
