from __future__ import annotations

import hashlib
import io
import json
import math
import re
import tempfile
from collections import defaultdict
from copy import deepcopy
from html import unescape
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from docxtpl import DocxTemplate
from fastapi import HTTPException, status

from brainrh.services.file_storage import FileStorage
from brainrh.schemas.company_cv import (
    CompanyCvCertification,
    CompanyCvContext,
    CompanyCvEducation,
    CompanyCvExperience,
    CompanyCvIdentity,
    CompanyCvInterviewSheetInfo,
    CompanyCvLanguage,
    CompanyCvMetrics,
    CompanyCvProject,
    CompanyCvProjectInfo,
    CompanyCvSkills,
    CompanyCvEnterpriseInfo,
)


DOCX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MAX_TEMPLATE_SIZE_BYTES = 10 * 1024 * 1024
COMPANY_CV_MAPPER_VERSION = "company_cv_mapper.v1"
COMPANY_CV_MAPPING_VERSION = "company_cv_template_mapping.v1"
COMPANY_CV_TEMPLATE_CONTRACT_VERSION = "company_cv_template_contract.v1"
COMPANY_CV_CONTEXT_ROOTS = [
    "identity",
    "title",
    "summary",
    "availability",
    "experiences",
    "education",
    "certifications",
    "languages",
    "skills",
    "projects",
    "enterprise",
    "project",
    "interview_sheet",
    "metrics",
    "generated_at",
    "generated_date",
]
LEGACY_COMPANY_CV_CONTEXT_ROOTS = [
    "candidate",
    "enterprise",
    "project",
    "sheet",
    "work",
    "education",
    "technical_skills",
    "soft_skills",
    "languages",
    "certifications",
    "projects",
]
COMPANY_CV_EXAMPLE_PLACEHOLDERS = [
    "{{ identity.full_name }}",
    "{{ title }}",
    "{{ enterprise.name }}",
    "{{ experiences[0].position }}",
    "{{ exp1_role }}",
    "{{ competence_cle_1 }}",
]
MARKER_PATTERN = re.compile(r"(\{\{.*?\}\}|\{%.*?%\})", flags=re.S)
SIMPLE_PLACEHOLDER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.\[\]]*$")
DIRECT_INDEX_PATTERN = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*)(\[\d+\])?(\.[a-zA-Z_][a-zA-Z0-9_]*(\[\d+\])?)*$")
PATH_TOKEN_PATTERN = re.compile(r"([a-zA-Z_][a-zA-Z0-9_]*)(?:\[(\d+)\])?")
TEMPLATE_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*(.*?)\s*\}\}", flags=re.S)
TEMPLATE_PARAGRAPH_PATTERN = re.compile(r"<w:p\b.*?</w:p>", flags=re.S)
TEMPLATE_BREAK_PATTERN = re.compile(r"<w:(?:tab|br|cr)[^>]*/>", flags=re.S)
EXPERIENCE_HEADER_FIELDS = {
    "position",
    "role",
    "company",
    "company_full",
    "location",
    "start_date",
    "end_date",
    "duration",
    "period",
    "period_full",
}
EXPERIENCE_BODY_FIELDS = {
    "summary",
    "context",
    "environment",
    "tasks",
    "highlights",
    "key_points",
}
TEMPLATE_SECTION_ORDER = [
    "identity_block",
    "first_page_teaser_experiences",
    "experience_detail_list",
    "education_certification",
    "languages",
    "skills_compact",
    "project_list",
]

IDENTITY_FIELDS = {
    "full_name",
    "first_name",
    "last_name",
    "email",
    "phone",
    "location",
    "title",
    "source_filename",
}
ENTERPRISE_FIELDS = {"id", "name", "sector", "notes"}
PROJECT_FIELDS = {"id", "name", "department", "manager", "manager_contact", "notes"}
INTERVIEW_SHEET_FIELDS = {"id", "status", "summary", "strengths", "concerns", "verdict", "verdict_detail"}
EXPERIENCE_FIELDS = {
    "position",
    "role",
    "company",
    "company_full",
    "location",
    "start_date",
    "end_date",
    "duration",
    "period",
    "period_full",
    "summary",
    "context",
    "environment",
    "tasks",
    "highlights",
    "key_points",
}
EDUCATION_FIELDS = {"degree", "institution", "field", "start_date", "end_date", "year", "description"}
CERTIFICATION_FIELDS = {"name", "issuer", "year", "link"}
LANGUAGE_FIELDS = {"name", "level"}
PROJECT_ENTRY_FIELDS = {"name", "description", "role", "technologies"}
SKILLS_FIELDS = {"technical", "soft", "domain", "key", "categories"}
METRICS_FIELDS = {"total_experience_years", "total_experience_years_label"}
SKILL_CATEGORY_FIELDS = {"api", "cloud", "data_bi", "dev", "gestion", "monitoring", "paiements"}
CHUNK_BASE_TOTALS: dict[str, int] = {
    "certif_intitule": 2,
    "exp_env_tech": 2,
    "tech_gestion": 2,
}


def extract_template_variables(template_bytes: bytes) -> list[str]:
    if not template_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Template file is empty.",
        )

    if len(template_bytes) > MAX_TEMPLATE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Template exceeds {MAX_TEMPLATE_SIZE_BYTES} bytes.",
        )

    with tempfile.NamedTemporaryFile(suffix=".docx") as tmp:
        tmp.write(template_bytes)
        tmp.flush()

        try:
            template = DocxTemplate(tmp.name)
            try:
                detected = template.get_undeclared_template_variables()
            except TypeError:
                detected = template.get_undeclared_template_variables({})
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unreadable DOCX template: {exc}",
            ) from exc

    normalized = []
    for item in detected:
        if not isinstance(item, str):
            continue
        value = " ".join(item.strip().split())
        if value:
            normalized.append(value)
    return sorted(set(normalized))


def analyze_template_variables(detected_variables: list[str]) -> dict[str, Any]:
    mappings = [_infer_placeholder_mapping(variable) for variable in detected_variables]
    resolved_placeholders = sorted(
        mapping["placeholder"]
        for mapping in mappings
        if mapping["status"] == "resolved"
    )
    unknown_placeholders = sorted(
        mapping["placeholder"]
        for mapping in mappings
        if mapping["status"] == "unknown"
    )
    ambiguous_placeholders = sorted(
        mapping["placeholder"]
        for mapping in mappings
        if mapping["status"] == "ambiguous"
    )

    return {
        "detected_variables": detected_variables,
        "resolved_placeholders": resolved_placeholders,
        "unknown_placeholders": unknown_placeholders,
        "ambiguous_placeholders": ambiguous_placeholders,
        "unsupported_variables": sorted(set(unknown_placeholders + ambiguous_placeholders)),
        "supported_context_roots": COMPANY_CV_CONTEXT_ROOTS + LEGACY_COMPANY_CV_CONTEXT_ROOTS,
        "example_placeholders": COMPANY_CV_EXAMPLE_PLACEHOLDERS,
        "placeholder_mappings": mappings,
        "mapping_version": COMPANY_CV_MAPPING_VERSION,
        "mapper_version": COMPANY_CV_MAPPER_VERSION,
        "is_valid": not unknown_placeholders and not ambiguous_placeholders,
    }


def ensure_template_mapping_metadata(template_record: dict[str, Any]) -> dict[str, Any]:
    detected_variables = [
        value
        for value in template_record.get("detected_variables", [])
        if isinstance(value, str) and value.strip()
    ]
    analysis = analyze_template_variables(sorted(set(detected_variables)))
    updated = dict(template_record)
    updated.update(analysis)
    updated.update(build_template_contract(updated))
    return updated


def build_template_contract(
    template_record: dict[str, Any],
    *,
    template_bytes: bytes | None = None,
) -> dict[str, Any]:
    slot_definitions: list[dict[str, Any]] = []
    adapter_plan: list[dict[str, Any]] = []
    list_group_meta: dict[str, dict[str, Any]] = {}
    list_group_fields: dict[str, set[str]] = defaultdict(set)
    object_root_fields: dict[str, set[str]] = defaultdict(set)
    scalar_roots: set[str] = set()
    slot_definition_by_placeholder: dict[str, dict[str, Any]] = {}

    for mapping in template_record.get("placeholder_mappings", []):
        if mapping.get("status") != "resolved":
            continue

        source_path = str(mapping.get("source_path") or "")
        transform = str(mapping.get("transform") or "identity")
        contract_path, group_name, field_name, source_kind = _contract_path_from_mapping(
            source_path,
            transform,
        )

        slot_definition = {
            "slot_id": str(mapping.get("placeholder") or contract_path or source_path),
            "placeholder": str(mapping.get("placeholder") or ""),
            "contract_path": contract_path,
            "source_path": source_path,
            "transform": transform,
            "required": bool(mapping.get("required")),
            "params": mapping.get("params") or {},
            "group": group_name,
            "field": field_name,
            "source_kind": source_kind,
        }
        slot_definitions.append(slot_definition)
        if slot_definition["placeholder"]:
            slot_definition_by_placeholder[slot_definition["placeholder"]] = slot_definition
        adapter_plan.append(
            {
                "placeholder": slot_definition["placeholder"],
                "contract_path": contract_path,
                "source_path": source_path,
                "transform": transform,
                "required": slot_definition["required"],
            }
        )

        normalized_field_name = _normalize_contract_field_path(field_name)

        if group_name:
            group_state = list_group_meta.setdefault(
                group_name,
                {
                    "source_kind": source_kind,
                    "template_capacity": 0,
                    "top_level_capacity": 0,
                    "nested_capacities": {},
                },
            )
            if normalized_field_name:
                list_group_fields[group_name].add(normalized_field_name)
            if source_path:
                top_level_capacity = _top_level_capacity_from_source_path(source_path, group_name)
                if top_level_capacity:
                    group_state["template_capacity"] = max(
                        int(group_state.get("template_capacity") or 0),
                        top_level_capacity,
                    )
                    group_state["top_level_capacity"] = max(
                        int(group_state.get("top_level_capacity") or 0),
                        top_level_capacity,
                    )
                nested_capacities = group_state.setdefault("nested_capacities", {})
                for nested_field, nested_capacity in _nested_capacities_from_source_path(
                    source_path,
                    group_name,
                ).items():
                    nested_capacities[nested_field] = max(
                        int(nested_capacities.get(nested_field) or 0),
                        nested_capacity,
                    )
        else:
            root_name = contract_path.split(".", 1)[0] if contract_path else ""
            if "." in contract_path:
                object_root_fields[root_name].add(
                    _normalize_contract_field_path(contract_path.split(".", 1)[1])
                )
            elif contract_path:
                scalar_roots.add(contract_path)

    template_contract = _build_template_contract_skeleton(
        scalar_roots=scalar_roots,
        object_root_fields=object_root_fields,
        list_group_fields=list_group_fields,
    )

    template_text_outline, ordered_placeholders = _extract_template_outline(
        template_record=template_record,
        slot_definitions=slot_definitions,
        template_bytes=template_bytes,
    )
    slot_families: dict[str, str] = {}
    section_buckets: dict[str, list[str]] = defaultdict(list)
    seen_placeholders: set[str] = set()

    for placeholder in ordered_placeholders:
        slot = slot_definition_by_placeholder.get(placeholder)
        if slot is None or placeholder in seen_placeholders:
            continue
        seen_placeholders.add(placeholder)
        family = _classify_slot_family(slot)
        section_name = _classify_slot_section(slot, family)
        slot_families[placeholder] = family
        if section_name:
            section_buckets[section_name].append(placeholder)

    for slot in slot_definitions:
        placeholder = str(slot.get("placeholder") or "")
        if not placeholder or placeholder in seen_placeholders:
            continue
        seen_placeholders.add(placeholder)
        family = _classify_slot_family(slot)
        section_name = _classify_slot_section(slot, family)
        slot_families[placeholder] = family
        if section_name:
            section_buckets[section_name].append(placeholder)

    section_slot_map: dict[str, list[str]] = {}
    for section_name in TEMPLATE_SECTION_ORDER:
        placeholders = section_buckets.get(section_name) or []
        if placeholders:
            section_slot_map[section_name] = placeholders
    for section_name, placeholders in section_buckets.items():
        if section_name not in section_slot_map and placeholders:
            section_slot_map[section_name] = placeholders

    group_definitions = {
        group_name: {
            "mode": "list",
            "template_capacity": max(1, int(meta.get("template_capacity") or 1)),
            "top_level_capacity": max(1, int(meta.get("top_level_capacity") or meta.get("template_capacity") or 1)),
            "nested_capacities": {
                key: int(value)
                for key, value in sorted((meta.get("nested_capacities") or {}).items())
                if int(value or 0) > 0
            },
            "unbounded": True,
            "fields": sorted(list_group_fields.get(group_name, set())),
            "source_kind": meta.get("source_kind"),
        }
        for group_name, meta in list_group_meta.items()
    }

    return {
        "contract_version": COMPANY_CV_TEMPLATE_CONTRACT_VERSION,
        "template_contract": template_contract,
        "slot_definitions": slot_definitions,
        "group_definitions": group_definitions,
        "adapter_plan": adapter_plan,
        "template_text_outline": template_text_outline,
        "slot_families": slot_families,
        "section_slot_map": section_slot_map,
    }


def build_render_context(
    template_record: dict[str, Any],
    canonical_context: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    render_context: dict[str, Any] = {}
    missing_required: list[str] = []

    for mapping in template_record.get("placeholder_mappings", []):
        if mapping.get("status") != "resolved":
            continue
        placeholder = str(mapping["placeholder"])
        value = _resolve_mapping_value(canonical_context, mapping)
        if mapping.get("required") and _is_missing_value(value):
            if _is_missing_due_to_absent_collection_item(
                canonical_context,
                str(mapping.get("source_path") or ""),
            ):
                _assign_render_value(render_context, placeholder, value)
                continue
            missing_required.append(placeholder)
            continue
        _assign_render_value(render_context, placeholder, value)

    return render_context, sorted(set(missing_required))


def render_context_fingerprint(
    *,
    template_record: dict[str, Any],
    canonical_context: dict[str, Any],
    render_context: dict[str, Any] | None = None,
    sheet_id: str,
    renderer_version: str = "company_cv_renderer.v1",
) -> str:
    payload = {
        "sheet_id": sheet_id,
        "renderer_version": renderer_version,
        "schema_version": canonical_context.get("schema_version"),
        "template_id": template_record.get("id"),
        "template_hash": template_record.get("content_hash"),
        "template_version": template_record.get("version"),
        "mapping_version": template_record.get("mapping_version"),
        "mapper_version": template_record.get("mapper_version"),
        "placeholder_mappings": template_record.get("placeholder_mappings", []),
        "canonical_context": canonical_context,
        "render_context": render_context or {},
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:20]


def build_render_trace(
    *,
    template_record: dict[str, Any],
    canonical_context: dict[str, Any],
    render_context: dict[str, Any],
    render_fingerprint: str,
    tenant_id: str | None,
    enterprise_id: str,
    project_id: str,
    sheet_id: str,
) -> dict[str, Any]:
    mapping_fingerprint = hashlib.sha256(
        json.dumps(
            template_record.get("placeholder_mappings", []),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    canonical_context_fingerprint = hashlib.sha256(
        json.dumps(
            canonical_context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    render_context_fingerprint = hashlib.sha256(
        json.dumps(
            render_context,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    return {
        "render_fingerprint": render_fingerprint,
        "template": {
            "id": template_record.get("id"),
            "name": template_record.get("name"),
            "version": template_record.get("version"),
            "content_hash": template_record.get("content_hash"),
        },
        "mapping": {
            "version": template_record.get("mapping_version"),
            "mapper_version": template_record.get("mapper_version"),
            "fingerprint": mapping_fingerprint,
        },
        "context": {
            "schema_version": canonical_context.get("schema_version"),
            "fingerprint": canonical_context_fingerprint,
            "snapshot": canonical_context,
        },
        "render_context": {
            "fingerprint": render_context_fingerprint,
            "snapshot": render_context,
        },
        "tenant_id": tenant_id,
        "enterprise_id": enterprise_id,
        "project_id": project_id,
        "sheet_id": sheet_id,
        "generated_at": canonical_context.get("generated_at", ""),
    }


def find_unrendered_markers(docx_bytes: bytes) -> list[str]:
    markers: set[str] = set()
    with tempfile.NamedTemporaryFile(suffix=".docx") as tmp:
        tmp.write(docx_bytes)
        tmp.flush()
        with ZipFile(tmp.name) as archive:
            for name in archive.namelist():
                if not name.endswith(".xml"):
                    continue
                content = archive.read(name).decode("utf-8", errors="ignore")
                for match in MARKER_PATTERN.findall(content):
                    markers.add(" ".join(match.split()))
    return sorted(markers)


def _infer_placeholder_mapping(placeholder: str) -> dict[str, Any]:
    if not SIMPLE_PLACEHOLDER_PATTERN.match(placeholder):
        return _mapping_record(
            placeholder=placeholder,
            status="ambiguous",
            reason="Only plain variable placeholders are supported for deterministic rendering.",
        )

    direct_path = _translate_direct_placeholder(placeholder)
    if direct_path is not None:
        return _mapping_record(
            placeholder=placeholder,
            status="resolved",
            source_path=direct_path["source_path"],
            transform=direct_path.get("transform", "identity"),
            required=direct_path.get("required", False),
            params=direct_path.get("params", {}),
        )

    if placeholder == "nom":
        return _resolved_placeholder(placeholder, "identity.full_name", required=False)
    if placeholder == "titre":
        return _resolved_placeholder(placeholder, "title", required=True)
    if placeholder == "annees_exp":
        return _resolved_placeholder(
            placeholder,
            "metrics.total_experience_years",
            transform="number_without_unit",
        )
    if placeholder == "competences_metiers":
        return _resolved_placeholder(
            placeholder,
            "skills.domain",
            transform="join_list",
            params={"separator": ", "},
        )
    if placeholder == "disponibilite":
        return _resolved_placeholder(placeholder, "availability")
    if placeholder == "formation_diplome":
        return _resolved_placeholder(
            placeholder,
            "education[0].degree",
            required=True,
            transform="suffix_if_present",
            params={"suffix": " – "},
        )
    if placeholder == "formation_etablissement":
        return _resolved_placeholder(placeholder, "education[0].institution", required=True)
    if placeholder == "formation_annee":
        return _resolved_placeholder(placeholder, "education[0].year", required=True)

    match = re.match(r"^langue_(\d+)$", placeholder)
    if match:
        return _resolved_placeholder(placeholder, f"languages[{int(match.group(1)) - 1}].name")

    match = re.match(r"^langue_(\d+)_niveau$", placeholder)
    if match:
        return _resolved_placeholder(placeholder, f"languages[{int(match.group(1)) - 1}].level")

    match = re.match(r"^competence_cle_(\d+)$", placeholder)
    if match:
        return _resolved_placeholder(placeholder, f"skills.key[{int(match.group(1)) - 1}]")

    match = re.match(r"^certif(\d+)_intitule(?:_(\d+))?$", placeholder)
    if match:
        cert_index = int(match.group(1)) - 1
        chunk_index = int(match.group(2)) if match.group(2) else None
        params = {"index": chunk_index, "total": 2} if chunk_index else {}
        transform = "chunk_text" if chunk_index else "identity"
        return _resolved_placeholder(
            placeholder,
            f"certifications[{cert_index}].name",
            transform=transform,
            params=params,
        )

    match = re.match(r"^certif(\d+)_lien$", placeholder)
    if match:
        return _resolved_placeholder(placeholder, f"certifications[{int(match.group(1)) - 1}].link")

    match = re.match(r"^tech_([a-z_]+?)(?:_(\d+))?$", placeholder)
    if match:
        category = match.group(1)
        item_index = int(match.group(2)) - 1 if match.group(2) else None
        source_path = f"skills.categories.{category}"
        if item_index is None:
            return _resolved_placeholder(
                placeholder,
                source_path,
                transform="join_list",
                params={"separator": ", "},
            )
        return _resolved_placeholder(placeholder, f"{source_path}[{item_index}]")

    match = re.match(r"^exp(\d+)_([a-z0-9_]+)$", placeholder)
    if match:
        exp_index = int(match.group(1)) - 1
        field_name = match.group(2)
        experience_mapping = _map_experience_placeholder(exp_index, field_name, placeholder)
        if experience_mapping is not None:
            return experience_mapping

    return _mapping_record(
        placeholder=placeholder,
        status="unknown",
        reason="No deterministic mapper rule matches this placeholder.",
    )


def _map_experience_placeholder(exp_index: int, field_name: str, placeholder: str) -> dict[str, Any] | None:
    base_path = f"experiences[{exp_index}]"
    if field_name == "role":
        return _resolved_placeholder(placeholder, f"{base_path}.role", required=True)
    if field_name == "poste":
        return _resolved_placeholder(
            placeholder,
            f"{base_path}.position",
            required=True,
            transform="suffix_if_present",
            params={"suffix": " – "},
        )
    if field_name == "entreprise":
        return _resolved_placeholder(placeholder, f"{base_path}.company", required=True)
    if field_name == "entreprise_full":
        return _resolved_placeholder(placeholder, f"{base_path}.company_full", required=True)
    if field_name == "contexte":
        return _resolved_placeholder(placeholder, f"{base_path}.context")
    if field_name == "periode":
        return _resolved_placeholder(placeholder, f"{base_path}.period", required=True)
    if field_name == "periode_full":
        return _resolved_placeholder(placeholder, f"{base_path}.period_full", required=True)
    if field_name == "point_cle":
        return _resolved_placeholder(placeholder, f"{base_path}.key_points[0]")

    match = re.match(r"^tache(\d+)$", field_name)
    if match:
        task_index = int(match.group(1)) - 1
        return _resolved_placeholder(placeholder, f"{base_path}.tasks[{task_index}]")

    match = re.match(r"^axe(\d+)$", field_name)
    if match:
        highlight_index = int(match.group(1)) - 1
        return _resolved_placeholder(placeholder, f"{base_path}.highlights[{highlight_index}]")

    match = re.match(r"^env_tech(?:_(\d+))?$", field_name)
    if match:
        chunk_index = int(match.group(1)) if match.group(1) else None
        params = {"index": chunk_index, "total": 2} if chunk_index else {}
        transform = "chunk_text" if chunk_index else "identity"
        return _resolved_placeholder(
            placeholder,
            f"{base_path}.environment",
            transform=transform,
            params=params,
        )

    return None


def _translate_direct_placeholder(placeholder: str) -> dict[str, Any] | None:
    if placeholder in COMPANY_CV_CONTEXT_ROOTS:
        return {"source_path": placeholder}

    if placeholder == "candidate":
        return {"source_path": "identity", "transform": "legacy_candidate"}
    if placeholder == "work":
        return {"source_path": "experiences", "transform": "legacy_experiences"}
    if placeholder == "technical_skills":
        return {"source_path": "skills.technical"}
    if placeholder == "soft_skills":
        return {"source_path": "skills.soft"}

    if not DIRECT_INDEX_PATTERN.match(placeholder):
        return None

    parts = placeholder.split(".", 1)
    root = parts[0].split("[", 1)[0]
    remainder = parts[1] if len(parts) > 1 else ""

    if root == "candidate":
        if not remainder:
            return {"source_path": "identity", "transform": "legacy_candidate"}
        if remainder in IDENTITY_FIELDS:
            source_path = "title" if remainder == "title" else f"identity.{remainder}"
            return {"source_path": source_path}
        if remainder == "summary":
            return {"source_path": "summary"}
        return None

    if root == "enterprise":
        if not remainder:
            return {"source_path": "enterprise", "transform": "legacy_enterprise"}
        if remainder in ENTERPRISE_FIELDS:
            return {"source_path": f"enterprise.{remainder}"}
        return None

    if root == "project":
        if not remainder:
            return {"source_path": "project", "transform": "legacy_project"}
        if remainder in PROJECT_FIELDS:
            return {"source_path": f"project.{remainder}"}
        return None

    if root == "sheet":
        if not remainder:
            return {"source_path": "interview_sheet", "transform": "legacy_interview_sheet"}
        if remainder in INTERVIEW_SHEET_FIELDS:
            return {"source_path": f"interview_sheet.{remainder}"}
        return None

    if root == "education":
        return _translate_indexed_root(placeholder, "education", EDUCATION_FIELDS, "legacy_education")
    if root == "certifications":
        return _translate_indexed_root(placeholder, "certifications", CERTIFICATION_FIELDS, "legacy_certifications")
    if root == "languages":
        return _translate_indexed_root(placeholder, "languages", LANGUAGE_FIELDS, "legacy_languages")
    if root == "projects":
        return _translate_indexed_root(placeholder, "projects", PROJECT_ENTRY_FIELDS, "legacy_projects")
    if root == "work":
        return _translate_indexed_root(placeholder, "experiences", EXPERIENCE_FIELDS, "legacy_experiences")

    canonical_root_translation = {
        "identity": IDENTITY_FIELDS,
        "experiences": EXPERIENCE_FIELDS,
        "education": EDUCATION_FIELDS,
        "certifications": CERTIFICATION_FIELDS,
        "languages": LANGUAGE_FIELDS,
        "projects": PROJECT_ENTRY_FIELDS,
        "skills": SKILLS_FIELDS,
        "enterprise": ENTERPRISE_FIELDS,
        "project": PROJECT_FIELDS,
        "interview_sheet": INTERVIEW_SHEET_FIELDS,
        "metrics": METRICS_FIELDS,
    }
    if root in canonical_root_translation:
        return _translate_canonical_root(placeholder)

    return None


def _translate_canonical_root(placeholder: str) -> dict[str, Any] | None:
    if placeholder in {"title", "summary", "availability", "generated_at", "generated_date"}:
        return {"source_path": placeholder}

    if placeholder == "identity":
        return {"source_path": "identity"}
    if placeholder.startswith("identity."):
        remainder = placeholder.split(".", 1)[1]
        return {"source_path": placeholder} if remainder in IDENTITY_FIELDS else None

    if placeholder == "enterprise":
        return {"source_path": "enterprise"}
    if placeholder.startswith("enterprise."):
        remainder = placeholder.split(".", 1)[1]
        return {"source_path": placeholder} if remainder in ENTERPRISE_FIELDS else None

    if placeholder == "project":
        return {"source_path": "project"}
    if placeholder.startswith("project."):
        remainder = placeholder.split(".", 1)[1]
        return {"source_path": placeholder} if remainder in PROJECT_FIELDS else None

    if placeholder == "interview_sheet":
        return {"source_path": "interview_sheet"}
    if placeholder.startswith("interview_sheet."):
        remainder = placeholder.split(".", 1)[1]
        return {"source_path": placeholder} if remainder in INTERVIEW_SHEET_FIELDS else None

    if placeholder == "metrics":
        return {"source_path": "metrics"}
    if placeholder.startswith("metrics."):
        remainder = placeholder.split(".", 1)[1]
        return {"source_path": placeholder} if remainder in METRICS_FIELDS else None

    if placeholder == "skills":
        return {"source_path": "skills"}
    if placeholder.startswith("skills."):
        return _translate_canonical_skills_path(placeholder)

    if placeholder == "experiences":
        return {"source_path": "experiences"}
    if placeholder.startswith("experiences["):
        return _translate_indexed_root(
            placeholder,
            "experiences",
            EXPERIENCE_FIELDS,
            "legacy_experiences",
            nested_list_fields={"tasks", "highlights", "key_points"},
            allow_direct_root=False,
        )

    if placeholder == "education":
        return {"source_path": "education"}
    if placeholder.startswith("education["):
        return _translate_indexed_root(
            placeholder,
            "education",
            EDUCATION_FIELDS,
            "legacy_education",
            allow_direct_root=False,
        )

    if placeholder == "certifications":
        return {"source_path": "certifications"}
    if placeholder.startswith("certifications["):
        return _translate_indexed_root(
            placeholder,
            "certifications",
            CERTIFICATION_FIELDS,
            "legacy_certifications",
            allow_direct_root=False,
        )

    if placeholder == "languages":
        return {"source_path": "languages"}
    if placeholder.startswith("languages["):
        return _translate_indexed_root(
            placeholder,
            "languages",
            LANGUAGE_FIELDS,
            "legacy_languages",
            allow_direct_root=False,
        )

    if placeholder == "projects":
        return {"source_path": "projects"}
    if placeholder.startswith("projects["):
        return _translate_indexed_root(
            placeholder,
            "projects",
            PROJECT_ENTRY_FIELDS,
            "legacy_projects",
            nested_list_fields={"technologies"},
            allow_direct_root=False,
        )

    return None


def _translate_canonical_skills_path(placeholder: str) -> dict[str, Any] | None:
    if placeholder == "skills.categories":
        return {"source_path": "skills.categories"}

    skill_match = re.match(r"^skills\.(technical|soft|domain|key)(?:\[(\d+)\])?$", placeholder)
    if skill_match:
        return {"source_path": placeholder}

    category_match = re.match(r"^skills\.categories\.([a-z_][a-z0-9_]*)(?:\[(\d+)\])?$", placeholder)
    if category_match and category_match.group(1) in SKILL_CATEGORY_FIELDS:
        return {"source_path": placeholder}

    return None


def _translate_indexed_root(
    placeholder: str,
    canonical_root: str,
    allowed_fields: set[str],
    root_transform: str,
    *,
    nested_list_fields: set[str] | None = None,
    allow_direct_root: bool = True,
) -> dict[str, Any] | None:
    root_part, *tail = placeholder.split(".", 1)
    if not tail:
        if allow_direct_root:
            return {"source_path": canonical_root, "transform": root_transform}
        return None

    root_match = re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*\[(\d+)\]$", root_part)
    if not root_match:
        return None

    index = int(root_match.group(1))
    remainder = tail[0]
    if "." in remainder:
        return None
    field_match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)(?:\[(\d+)\])?$", remainder)
    if not field_match:
        return None

    field_name = field_match.group(1)
    nested_index = field_match.group(2)
    if field_name not in allowed_fields:
        return None
    if nested_index and field_name not in (nested_list_fields or set()):
        return None

    return {"source_path": f"{canonical_root}[{index}].{remainder}"}


def _contract_path_from_mapping(
    source_path: str,
    transform: str,
) -> tuple[str, str | None, str | None, str]:
    if transform == "legacy_candidate":
        return "identity", None, None, "cv"
    if transform == "legacy_experiences":
        return "experiences", "experiences", None, "cv"
    if transform == "legacy_education":
        return "education", "education", None, "cv"
    if transform == "legacy_certifications":
        return "certifications", "certifications", None, "cv"
    if transform == "legacy_languages":
        return "languages", "languages", None, "cv"
    if transform == "legacy_projects":
        return "projects", "projects", None, "cv"
    if transform == "legacy_enterprise":
        return "enterprise", None, None, "system"
    if transform == "legacy_project":
        return "project", None, None, "system"
    if transform == "legacy_interview_sheet":
        return "interview_sheet", None, None, "system"

    normalized_contract_path = re.sub(r"\[\d+\]", "[]", source_path or "")
    group_name = None
    field_name = None
    source_kind = "cv"
    top_level_list_groups = {"experiences", "education", "certifications", "languages", "projects"}

    if normalized_contract_path:
        root_name = normalized_contract_path.split(".", 1)[0].replace("[]", "")
        if root_name in {"enterprise", "project", "interview_sheet", "metrics", "generated_at", "generated_date"}:
            source_kind = "system"
        if "[]" in normalized_contract_path and root_name in top_level_list_groups:
            group_name = root_name
            tail = normalized_contract_path.split(".", 1)
            if len(tail) > 1:
                field_name = tail[1]
    return normalized_contract_path, group_name, field_name, source_kind


def _max_index_from_source_path(source_path: str) -> int:
    matches = [int(index) for index in re.findall(r"\[(\d+)\]", source_path or "")]
    return max(matches, default=0)


def _top_level_capacity_from_source_path(source_path: str, group_name: str | None) -> int:
    if not source_path or not group_name:
        return 0
    match = re.match(rf"^{re.escape(group_name)}\[(\d+)\]", source_path)
    if not match:
        return 0
    return int(match.group(1)) + 1


def _nested_capacities_from_source_path(source_path: str, group_name: str | None) -> dict[str, int]:
    if not source_path or not group_name:
        return {}
    match = re.match(rf"^{re.escape(group_name)}\[\d+\]\.(.+)$", source_path)
    if not match:
        return {}

    nested_path = match.group(1)
    capacities: dict[str, int] = {}
    current_path: list[str] = []
    for token_name, token_index in PATH_TOKEN_PATTERN.findall(nested_path):
        current_path.append(token_name)
        if token_index:
            capacities[".".join(current_path)] = max(
                capacities.get(".".join(current_path), 0),
                int(token_index) + 1,
            )
    return capacities


def _extract_template_outline(
    *,
    template_record: dict[str, Any],
    slot_definitions: list[dict[str, Any]],
    template_bytes: bytes | None,
) -> tuple[str, list[str]]:
    known_placeholders = {
        str(value).strip()
        for value in template_record.get("detected_variables", [])
        if isinstance(value, str) and value.strip()
    }
    known_placeholders.update(
        str(slot.get("placeholder") or "").strip()
        for slot in slot_definitions
        if str(slot.get("placeholder") or "").strip()
    )
    payload = _extract_template_outline_from_bytes(
        _resolve_template_bytes(template_record, template_bytes),
        known_placeholders,
    )
    if payload is None:
        fallback_order = [
            str(slot.get("placeholder") or "")
            for slot in slot_definitions
            if str(slot.get("placeholder") or "")
        ]
        fallback_lines = [f"{{{{ {placeholder} }}}}" for placeholder in fallback_order]
        return "\n".join(fallback_lines), fallback_order
    return payload["outline"], payload["ordered_placeholders"]


def _resolve_template_bytes(template_record: dict[str, Any], template_bytes: bytes | None) -> bytes | None:
    if template_bytes:
        return template_bytes
    storage_path = str(template_record.get("storage_path") or "").strip()
    if not storage_path:
        return None
    try:
        return FileStorage.load_bytes(storage_path)
    except Exception:
        return None


def _extract_template_outline_from_bytes(
    template_bytes: bytes | None,
    known_placeholders: set[str],
) -> dict[str, Any] | None:
    if not template_bytes or not known_placeholders:
        return None
    try:
        with ZipFile(io.BytesIO(template_bytes)) as archive:
            document_xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    except Exception:
        return None

    outline_lines: list[str] = []
    ordered_placeholders: list[str] = []
    seen_placeholders: set[str] = set()

    for paragraph in TEMPLATE_PARAGRAPH_PATTERN.findall(document_xml):
        text = _strip_template_xml(paragraph)
        if not text:
            continue
        placeholders = _extract_placeholders_from_text(text, known_placeholders)
        if not placeholders:
            continue
        outline_lines.append(text)
        for placeholder in placeholders:
            if placeholder not in seen_placeholders:
                ordered_placeholders.append(placeholder)
                seen_placeholders.add(placeholder)

    if not outline_lines and not ordered_placeholders:
        return None
    return {
        "outline": "\n".join(outline_lines),
        "ordered_placeholders": ordered_placeholders,
    }


def _strip_template_xml(xml_fragment: str) -> str:
    text = TEMPLATE_BREAK_PATTERN.sub(" ", xml_fragment)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text)
    return " ".join(text.split())


def _extract_placeholders_from_text(text: str, known_placeholders: set[str]) -> list[str]:
    placeholders: list[str] = []
    for raw_value in TEMPLATE_PLACEHOLDER_PATTERN.findall(text):
        normalized = " ".join(str(raw_value).split())
        if normalized in known_placeholders:
            placeholders.append(normalized)
    return placeholders


def _classify_slot_family(slot_definition: dict[str, Any]) -> str:
    placeholder = str(slot_definition.get("placeholder") or "")
    contract_path = str(slot_definition.get("contract_path") or "")
    field_name = _normalize_contract_field_path(str(slot_definition.get("field") or ""))
    root_name = contract_path.split(".", 1)[0].replace("[]", "") if contract_path else ""

    if root_name in {"identity", "title", "summary"} or placeholder in {"nom", "titre"}:
        return "identity"
    if root_name == "availability" or placeholder == "disponibilite":
        return "availability"
    if root_name == "metrics" or placeholder == "annees_exp":
        return "metrics"
    if root_name in {"education", "certifications"} or placeholder.startswith(("formation_", "certif")):
        return "education_certification"
    if root_name == "languages" or placeholder.startswith("langue_"):
        return "languages"
    if root_name == "skills" or placeholder.startswith(("tech_", "competence_cle_", "competences_metiers")):
        return "skills_compact"
    if root_name == "projects":
        return "project_list"
    if root_name == "experiences":
        leaf_name = field_name.split(".", 1)[0] if field_name else ""
        if leaf_name in EXPERIENCE_BODY_FIELDS or placeholder.startswith(("exp",)) and (
            "_contexte" in placeholder
            or "_tache" in placeholder
            or "_axe" in placeholder
            or "_point_cle" in placeholder
            or "_env_tech" in placeholder
        ):
            return "experience_body"
        if leaf_name in EXPERIENCE_HEADER_FIELDS or placeholder.startswith("exp"):
            return "experience_header"
    return "identity"


def _classify_slot_section(slot_definition: dict[str, Any], family_name: str) -> str:
    if family_name in {"identity", "availability", "metrics"}:
        return "identity_block"
    if family_name == "experience_header":
        placeholder = str(slot_definition.get("placeholder") or "")
        if (
            "_entreprise_full" in placeholder
            or "_periode_full" in placeholder
            or placeholder.endswith("_role")
        ):
            return "experience_detail_list"
        return "first_page_teaser_experiences"
    if family_name == "experience_body":
        return "experience_detail_list"
    if family_name == "education_certification":
        return "education_certification"
    if family_name == "languages":
        return "languages"
    if family_name == "skills_compact":
        return "skills_compact"
    if family_name == "project_list":
        return "project_list"
    return "identity_block"


def _base_contract_scalar_roots() -> dict[str, Any]:
    return {
        "title": "",
        "summary": "",
        "availability": "",
        "generated_at": "",
        "generated_date": "",
    }


def _base_contract_object_roots() -> dict[str, dict[str, Any]]:
    return {
        "identity": CompanyCvIdentity().model_dump(mode="json"),
        "skills": CompanyCvSkills().model_dump(mode="json"),
        "enterprise": CompanyCvEnterpriseInfo().model_dump(mode="json"),
        "project": CompanyCvProjectInfo().model_dump(mode="json"),
        "interview_sheet": CompanyCvInterviewSheetInfo().model_dump(mode="json"),
        "metrics": CompanyCvMetrics().model_dump(mode="json"),
    }


def _base_contract_list_group_items() -> dict[str, dict[str, Any]]:
    return {
        "experiences": CompanyCvExperience().model_dump(mode="json"),
        "education": CompanyCvEducation().model_dump(mode="json"),
        "certifications": CompanyCvCertification().model_dump(mode="json"),
        "languages": CompanyCvLanguage().model_dump(mode="json"),
        "projects": CompanyCvProject().model_dump(mode="json"),
    }


def _build_template_contract_skeleton(
    *,
    scalar_roots: set[str],
    object_root_fields: dict[str, set[str]],
    list_group_fields: dict[str, set[str]],
) -> dict[str, Any]:
    skeleton: dict[str, Any] = {}
    base_scalars = _base_contract_scalar_roots()
    base_objects = _base_contract_object_roots()
    base_lists = _base_contract_list_group_items()

    for root in sorted(scalar_roots):
        if root in base_scalars:
            skeleton[root] = base_scalars[root]

    for root, fields in object_root_fields.items():
        base = base_objects.get(root)
        if base is None:
            continue
        if not fields:
            skeleton[root] = deepcopy(base)
            continue
        partial_root: dict[str, Any] = {}
        for field_path in sorted(fields):
            _copy_base_field_path(partial_root, base, field_path)
        if partial_root:
            skeleton[root] = partial_root

    for group_name, fields in list_group_fields.items():
        base_item = base_lists.get(group_name)
        if base_item is None:
            continue
        if not fields:
            skeleton[group_name] = [deepcopy(base_item)]
            continue
        partial_item: dict[str, Any] = {}
        for field_path in sorted(fields):
            _copy_base_field_path(partial_item, base_item, field_path)
        if partial_item:
            skeleton[group_name] = [partial_item]

    return {
        "schema_version": COMPANY_CV_TEMPLATE_CONTRACT_VERSION,
        **skeleton,
    }


def _normalize_contract_field_path(field_path: str | None) -> str:
    return re.sub(r"\[\]", "", field_path or "")


def _copy_base_field_path(target: dict[str, Any], base: dict[str, Any], field_path: str) -> None:
    parts = [part for part in field_path.split(".") if part]
    if not parts:
        return

    current_target = target
    current_base: Any = base

    for index, part in enumerate(parts):
        is_last = index == len(parts) - 1
        base_has_key = isinstance(current_base, dict) and part in current_base
        base_value = current_base.get(part) if base_has_key else None

        if is_last:
            if isinstance(base_value, list):
                current_target[part] = [""]
            elif isinstance(base_value, dict):
                current_target[part] = deepcopy(base_value)
            elif base_has_key:
                current_target[part] = deepcopy(base_value)
            else:
                # Dynamic dictionaries like skills.categories.<bucket> are template-driven.
                current_target[part] = [""]
            return

        next_target = current_target.get(part)
        if not isinstance(next_target, dict):
            next_target = {}
            current_target[part] = next_target
        current_target = next_target
        current_base = base_value if isinstance(base_value, dict) else {}


def _resolve_mapping_value(canonical_context: dict[str, Any], mapping: dict[str, Any]) -> Any:
    source_path = str(mapping.get("source_path") or "")
    transform = str(mapping.get("transform") or "identity")
    params = mapping.get("params") if isinstance(mapping.get("params"), dict) else {}
    value = _resolve_context_path(canonical_context, source_path)

    if transform == "identity":
        return value
    if transform == "number_without_unit":
        return _number_without_unit(value)
    if transform == "suffix_if_present":
        return _suffix_if_present(value, suffix=str(params.get("suffix") or ""))
    if transform == "join_list":
        return _join_list(value, separator=str(params.get("separator", ", ")))
    if transform == "chunk_text":
        return _chunk_text(
            value,
            index=int(params.get("index") or 1),
            total=int(params.get("total") or 2),
        )
    if transform == "legacy_candidate":
        return _legacy_candidate(value, canonical_context)
    if transform == "legacy_enterprise":
        return _legacy_entity(value)
    if transform == "legacy_project":
        return _legacy_entity(value)
    if transform == "legacy_interview_sheet":
        return _legacy_interview_sheet(value)
    if transform == "legacy_experiences":
        return [_legacy_experience(item) for item in _ensure_list(value)]
    if transform == "legacy_education":
        return [_legacy_education(item) for item in _ensure_list(value)]
    if transform == "legacy_certifications":
        return [_legacy_certification(item) for item in _ensure_list(value)]
    if transform == "legacy_languages":
        return [_legacy_language(item) for item in _ensure_list(value)]
    if transform == "legacy_projects":
        return [_legacy_project(item) for item in _ensure_list(value)]
    return value


def _resolve_context_path(value: Any, path: str) -> Any:
    if not path:
        return None
    current = value
    for token_name, token_index in PATH_TOKEN_PATTERN.findall(path):
        if not isinstance(current, dict):
            return None
        current = current.get(token_name)
        if token_index:
            if not isinstance(current, list):
                return None
            index = int(token_index)
            if index >= len(current):
                return None
            current = current[index]
    return current


def _is_missing_due_to_absent_collection_item(canonical_context: dict[str, Any], path: str) -> bool:
    if not path:
        return False

    current: Any = canonical_context
    for token_name, token_index in PATH_TOKEN_PATTERN.findall(path):
        if not isinstance(current, dict):
            return False
        if token_name not in current:
            return False
        current = current.get(token_name)
        if token_index:
            if not isinstance(current, list):
                return False
            index = int(token_index)
            if index >= len(current):
                return True
            current = current[index]
    return False


def _assign_render_value(render_context: dict[str, Any], placeholder: str, value: Any) -> None:
    if "." not in placeholder and "[" not in placeholder:
        render_context[placeholder] = _normalize_render_value(value)
        return

    tokens = list(PATH_TOKEN_PATTERN.finditer(placeholder))
    current: Any = render_context
    for index, match in enumerate(tokens):
        key = match.group(1)
        list_index = int(match.group(2)) if match.group(2) is not None else None
        is_last = index == len(tokens) - 1

        if not isinstance(current, dict):
            return

        if list_index is None:
            if is_last:
                current[key] = _normalize_render_value(value)
                return
            current = current.setdefault(key, {})
            continue

        target_list = current.setdefault(key, [])
        if not isinstance(target_list, list):
            return
        while len(target_list) <= list_index:
            target_list.append({})
        if is_last:
            target_list[list_index] = _normalize_render_value(value)
            return
        if not isinstance(target_list[list_index], dict):
            target_list[list_index] = {}
        current = target_list[list_index]


def _normalize_render_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, list):
        return [_normalize_render_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_render_value(item) for key, item in value.items()}
    return value


def _join_list(value: Any, *, separator: str) -> str:
    items = [str(item).strip() for item in _ensure_list(value) if str(item).strip()]
    return separator.join(items)


def _number_without_unit(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        text = str(value).strip()
        match = re.search(r"\d+(?:[.,]\d+)?", text)
        if not match:
            return text
        try:
            numeric = float(match.group(0).replace(",", "."))
        except ValueError:
            return text
    return str(int(round(numeric)))


def _suffix_if_present(value: Any, *, suffix: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return f"{text}{suffix}"


def _chunk_text(value: Any, *, index: int, total: int) -> str:
    if index < 1 or total < 1:
        return ""
    text = _stringify_text(value)
    if not text:
        return ""

    chunks = _split_text_into_chunks(text, total)
    if index > len(chunks):
        return ""
    return chunks[index - 1]


def _split_text_into_chunks(text: str, total: int) -> list[str]:
    if total <= 1 or not text:
        return [text]

    if "," in text:
        tokens = [item.strip() for item in text.split(",") if item.strip()]
    elif ";" in text:
        tokens = [item.strip() for item in text.split(";") if item.strip()]
    else:
        tokens = text.split()

    if not tokens:
        return [text]

    size = int(math.ceil(len(tokens) / total))
    chunks = [
        " ".join(tokens[start:start + size]).strip()
        for start in range(0, len(tokens), size)
    ]
    while len(chunks) < total:
        chunks.append("")
    return chunks[:total]


def _stringify_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _legacy_candidate(value: Any, canonical_context: dict[str, Any]) -> dict[str, Any]:
    identity = value if isinstance(value, dict) else {}
    return {
        **identity,
        "title": canonical_context.get("title", ""),
        "summary": canonical_context.get("summary", ""),
    }


def _legacy_entity(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _legacy_interview_sheet(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _legacy_experience(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {
            "position": "",
            "company": "",
            "location": "",
            "start_date": "",
            "end_date": "",
            "duration": "",
            "description": "",
            "missions": [],
        }
    return {
        "position": value.get("position", ""),
        "company": value.get("company", ""),
        "location": value.get("location", ""),
        "start_date": value.get("start_date", ""),
        "end_date": value.get("end_date", ""),
        "duration": value.get("duration", ""),
        "description": value.get("summary") or value.get("context") or "",
        "missions": value.get("tasks", []),
    }


def _legacy_education(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"degree": "", "institution": "", "field": "", "start_date": "", "end_date": "", "description": ""}
    return {
        "degree": value.get("degree", ""),
        "institution": value.get("institution", ""),
        "field": value.get("field", ""),
        "start_date": value.get("start_date", ""),
        "end_date": value.get("end_date", ""),
        "description": value.get("description", ""),
    }


def _legacy_certification(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"name": "", "issuer": "", "date": ""}
    return {
        "name": value.get("name", ""),
        "issuer": value.get("issuer", ""),
        "date": value.get("year", ""),
    }


def _legacy_language(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"name": "", "level": ""}
    return {
        "name": value.get("name", ""),
        "level": value.get("level", ""),
    }


def _legacy_project(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"name": "", "description": "", "role": "", "technologies": []}
    return {
        "name": value.get("name", ""),
        "description": value.get("description", ""),
        "role": value.get("role", ""),
        "technologies": value.get("technologies", []),
    }


def _ensure_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not any(not _is_missing_value(item) for item in value)
    if isinstance(value, dict):
        return not any(not _is_missing_value(item) for item in value.values())
    return False


def _mapping_record(
    *,
    placeholder: str,
    status: str,
    source_path: str | None = None,
    transform: str | None = None,
    required: bool = False,
    params: dict[str, Any] | None = None,
    reason: str | None = None,
) -> dict[str, Any]:
    record = {
        "placeholder": placeholder,
        "status": status,
        "source_path": source_path,
        "transform": transform or "identity",
        "required": required,
        "params": params or {},
    }
    if reason:
        record["reason"] = reason
    return record


def _resolved_placeholder(
    placeholder: str,
    source_path: str,
    *,
    transform: str = "identity",
    required: bool = False,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _mapping_record(
        placeholder=placeholder,
        status="resolved",
        source_path=source_path,
        transform=transform,
        required=required,
        params=params,
    )
