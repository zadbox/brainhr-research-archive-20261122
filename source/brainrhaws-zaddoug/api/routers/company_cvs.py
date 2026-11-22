from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from io import BytesIO
from typing import Any, Callable, Optional
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, status
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from api.dependencies import get_current_user, require_project_reader
from brainrh.models.auth import UserDB
from brainrh.services.company_cv_html_renderer import CompanyCvHtmlRenderService
from brainrh.services.company_cv_render_service import CompanyCvRenderService
from brainrh.services.interview_sheet_service import InterviewSheetService

router = APIRouter(tags=["Company CVs"])

_JOB_TTL = timedelta(hours=1)


@dataclass
class _CompanyCvGenerationJob:
    id: str
    interview_sheet_id: str
    kind: str
    status: str = "queued"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    rendered: dict[str, Any] | None = None
    error: str | None = None


_company_cv_jobs: dict[str, _CompanyCvGenerationJob] = {}


def _payload_string(payload: Optional[dict], key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _get_authorized_sheet(interview_sheet_id: str, current_user: UserDB) -> dict[str, Any]:
    sheet = InterviewSheetService.get(interview_sheet_id)
    if not sheet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Interview sheet {interview_sheet_id} not found.",
        )
    require_project_reader(sheet["job_id"], current_user)
    return sheet


def _cleanup_company_cv_jobs() -> None:
    cutoff = datetime.now(timezone.utc) - _JOB_TTL
    for job_id, job in list(_company_cv_jobs.items()):
        if job.updated_at < cutoff:
            _company_cv_jobs.pop(job_id, None)


def _rendered_metadata(rendered: dict[str, Any] | None) -> dict[str, Any] | None:
    if not rendered:
        return None
    template = rendered.get("template") or {}
    renderer = rendered.get("renderer") or {}
    return {
        "filename": rendered.get("filename"),
        "content_type": rendered.get("content_type"),
        "render_fingerprint": rendered.get("render_fingerprint"),
        "template_id": template.get("id"),
        "template_name": template.get("name"),
        "template_version": template.get("version"),
        "mapping_version": template.get("mapping_version"),
        "mapper_version": template.get("mapper_version"),
        "renderer": renderer.get("mode"),
        "renderer_version": renderer.get("version"),
    }


def _job_payload(job: _CompanyCvGenerationJob) -> dict[str, Any]:
    return {
        "job_id": job.id,
        "kind": job.kind,
        "status": job.status,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "error": job.error,
        "result": _rendered_metadata(job.rendered),
    }


def _get_company_cv_job(interview_sheet_id: str, job_id: str, kind: str) -> _CompanyCvGenerationJob:
    _cleanup_company_cv_jobs()
    job = _company_cv_jobs.get(job_id)
    if not job or job.interview_sheet_id != interview_sheet_id or job.kind != kind:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company CV generation job not found.")
    return job


async def _run_company_cv_job(
    job_id: str,
    renderer: Callable[..., dict[str, Any]],
    interview_sheet_id: str,
    template_id: str | None,
    generation_guidance: str | None,
) -> None:
    job = _company_cv_jobs.get(job_id)
    if not job:
        return
    job.status = "running"
    job.updated_at = datetime.now(timezone.utc)
    try:
        rendered = await run_in_threadpool(
            renderer,
            interview_sheet_id,
            template_id,
            generation_guidance=generation_guidance,
        )
        job.rendered = rendered
        job.status = "succeeded"
        job.error = None
    except Exception as exc:  # pragma: no cover - exercised through production provider failures
        job.status = "failed"
        job.error = str(exc) or exc.__class__.__name__
    finally:
        job.updated_at = datetime.now(timezone.utc)


def _start_company_cv_job(
    *,
    interview_sheet_id: str,
    kind: str,
    renderer: Callable[..., dict[str, Any]],
    template_id: str | None,
    generation_guidance: str | None,
) -> _CompanyCvGenerationJob:
    _cleanup_company_cv_jobs()
    job = _CompanyCvGenerationJob(
        id=uuid4().hex,
        interview_sheet_id=interview_sheet_id,
        kind=kind,
    )
    _company_cv_jobs[job.id] = job
    asyncio.create_task(
        _run_company_cv_job(
            job.id,
            renderer,
            interview_sheet_id,
            template_id,
            generation_guidance,
        )
    )
    return job


def _stream_company_cv_rendered(rendered: dict[str, Any]) -> StreamingResponse:
    return StreamingResponse(
        BytesIO(rendered["bytes"]),
        media_type=rendered["content_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{rendered["filename"]}"',
            "X-Company-Cv-Template-Id": rendered["template"]["id"],
            "X-Company-Cv-Template-Name": str(rendered["template"].get("name", "")),
            "X-Company-Cv-Template-Version": str(rendered["template"].get("version", "")),
            "X-Company-Cv-Mapping-Version": str(rendered["template"].get("mapping_version", "")),
            "X-Company-Cv-Mapper-Version": str(rendered["template"].get("mapper_version", "")),
            "X-Company-Cv-Render-Fingerprint": rendered["render_fingerprint"],
        },
    )


def _stream_company_cv_html_docx_rendered(rendered: dict[str, Any]) -> StreamingResponse:
    renderer = rendered.get("renderer") or {}
    return StreamingResponse(
        BytesIO(rendered["bytes"]),
        media_type=rendered["content_type"],
        headers={
            "Content-Disposition": f'attachment; filename="{rendered["filename"]}"',
            "X-Company-Cv-Renderer": str(renderer.get("mode") or "html_docx"),
            "X-Company-Cv-Renderer-Version": str(renderer.get("version") or ""),
            "X-Company-Cv-Template-Id": rendered["template"]["id"],
            "X-Company-Cv-Template-Name": str(rendered["template"].get("name", "")),
            "X-Company-Cv-Template-Version": str(rendered["template"].get("version", "")),
            "X-Company-Cv-Mapping-Version": str(rendered["template"].get("mapping_version", "")),
            "X-Company-Cv-Mapper-Version": str(rendered["template"].get("mapper_version", "")),
            "X-Company-Cv-Render-Fingerprint": rendered["render_fingerprint"],
        },
    )


@router.post("/interview-sheet/{interview_sheet_id}/company-cv")
async def generate_company_cv_from_interview_sheet(
    interview_sheet_id: str,
    payload: Optional[dict] = Body(default=None),
    current_user: UserDB = Depends(get_current_user),
):
    _get_authorized_sheet(interview_sheet_id, current_user)
    template_id = _payload_string(payload, "template_id")
    generation_guidance = _payload_string(payload, "generation_guidance")
    rendered = await run_in_threadpool(
        CompanyCvRenderService.render_company_cv,
        interview_sheet_id,
        template_id,
        generation_guidance=generation_guidance,
    )

    return _stream_company_cv_rendered(rendered)


@router.post("/interview-sheet/{interview_sheet_id}/company-cv/jobs")
async def start_company_cv_generation_job(
    interview_sheet_id: str,
    payload: Optional[dict] = Body(default=None),
    current_user: UserDB = Depends(get_current_user),
):
    _get_authorized_sheet(interview_sheet_id, current_user)
    job = _start_company_cv_job(
        interview_sheet_id=interview_sheet_id,
        kind="company_cv",
        renderer=CompanyCvRenderService.render_company_cv,
        template_id=_payload_string(payload, "template_id"),
        generation_guidance=_payload_string(payload, "generation_guidance"),
    )
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=_job_payload(job))


@router.get("/interview-sheet/{interview_sheet_id}/company-cv/jobs/{job_id}")
async def get_company_cv_generation_job(
    interview_sheet_id: str,
    job_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    _get_authorized_sheet(interview_sheet_id, current_user)
    return _job_payload(_get_company_cv_job(interview_sheet_id, job_id, "company_cv"))


@router.get("/interview-sheet/{interview_sheet_id}/company-cv/jobs/{job_id}/download")
async def download_company_cv_generation_job(
    interview_sheet_id: str,
    job_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    _get_authorized_sheet(interview_sheet_id, current_user)
    job = _get_company_cv_job(interview_sheet_id, job_id, "company_cv")
    if job.status != "succeeded" or not job.rendered:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Company CV generation is not complete.")
    return _stream_company_cv_rendered(job.rendered)


@router.post("/interview-sheet/{interview_sheet_id}/company-cv/html-docx")
async def generate_company_cv_html_docx_from_interview_sheet(
    interview_sheet_id: str,
    payload: Optional[dict] = Body(default=None),
    current_user: UserDB = Depends(get_current_user),
):
    _get_authorized_sheet(interview_sheet_id, current_user)
    template_id = _payload_string(payload, "template_id")
    generation_guidance = _payload_string(payload, "generation_guidance")
    rendered = await run_in_threadpool(
        CompanyCvHtmlRenderService.render_company_cv_html_docx,
        interview_sheet_id,
        template_id,
        generation_guidance=generation_guidance,
    )
    return _stream_company_cv_html_docx_rendered(rendered)


@router.post("/interview-sheet/{interview_sheet_id}/company-cv/html-docx/jobs")
async def start_company_cv_html_docx_generation_job(
    interview_sheet_id: str,
    payload: Optional[dict] = Body(default=None),
    current_user: UserDB = Depends(get_current_user),
):
    _get_authorized_sheet(interview_sheet_id, current_user)
    job = _start_company_cv_job(
        interview_sheet_id=interview_sheet_id,
        kind="company_cv_html_docx",
        renderer=CompanyCvHtmlRenderService.render_company_cv_html_docx,
        template_id=_payload_string(payload, "template_id"),
        generation_guidance=_payload_string(payload, "generation_guidance"),
    )
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=_job_payload(job))


@router.get("/interview-sheet/{interview_sheet_id}/company-cv/html-docx/jobs/{job_id}")
async def get_company_cv_html_docx_generation_job(
    interview_sheet_id: str,
    job_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    _get_authorized_sheet(interview_sheet_id, current_user)
    return _job_payload(_get_company_cv_job(interview_sheet_id, job_id, "company_cv_html_docx"))


@router.get("/interview-sheet/{interview_sheet_id}/company-cv/html-docx/jobs/{job_id}/download")
async def download_company_cv_html_docx_generation_job(
    interview_sheet_id: str,
    job_id: str,
    current_user: UserDB = Depends(get_current_user),
):
    _get_authorized_sheet(interview_sheet_id, current_user)
    job = _get_company_cv_job(interview_sheet_id, job_id, "company_cv_html_docx")
    if job.status != "succeeded" or not job.rendered:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="HTML DOCX generation is not complete.")
    return _stream_company_cv_html_docx_rendered(job.rendered)
