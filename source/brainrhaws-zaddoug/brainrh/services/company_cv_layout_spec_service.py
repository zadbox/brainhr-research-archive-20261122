from __future__ import annotations

import io
import json
import re
from copy import deepcopy
from typing import Any
from zipfile import ZipFile
from xml.etree import ElementTree as ET


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"w": WORD_NS, "r": REL_NS}
LAYOUT_SPEC_VERSION = "company_cv_layout_spec.v1"
RENDER_MODE_CODE_DRIVEN = "code_driven"
RENDER_MODE_LEGACY = "legacy_docxtpl"
LAYOUT_STATUS_READY = "ready"
LAYOUT_STATUS_PARTIAL = "partial"
LAYOUT_STATUS_UNSUPPORTED = "unsupported"
SUPPORTED_RENDER_TYPES = {"block", "block_repeat", "table_row_repeat", "paragraph_repeat"}
PLACEHOLDER_PATTERN = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", flags=re.S)
TEXTBOX_PATTERN = re.compile(r"<w:txbxContent\b.*?</w:txbxContent>|<v:textbox\b.*?</v:textbox>", flags=re.S)

SUPPORTED_SECTION_SPECS: dict[str, dict[str, Any]] = {
    "cv.identity_block": {"required": True, "render_type": "block", "bounded": False, "max_items": None},
    "cv.first_page_teaser_experiences": {"required": False, "render_type": "block_repeat", "bounded": True, "max_items": 3},
    "cv.key_skills_list": {"required": False, "render_type": "block_repeat", "bounded": True, "max_items": 10},
    "cv.technical_skills_block": {"required": False, "render_type": "block", "bounded": True, "max_items": None},
    "cv.domain_skills_block": {"required": False, "render_type": "block", "bounded": True, "max_items": None},
    "cv.experience_detail_list": {"required": True, "render_type": "block_repeat", "bounded": False, "max_items": None},
    "cv.education_list": {"required": False, "render_type": "block_repeat", "bounded": False, "max_items": None},
    "cv.certification_list": {"required": False, "render_type": "block_repeat", "bounded": False, "max_items": None},
    "cv.language_list": {"required": False, "render_type": "block_repeat", "bounded": False, "max_items": None},
    "cv.project_list": {"required": False, "render_type": "block_repeat", "bounded": False, "max_items": None},
}
REQUIRED_READY_SECTIONS = {"cv.identity_block", "cv.experience_detail_list"}
BODY_SECTIONS = {
    "cv.experience_detail_list",
    "cv.education_list",
    "cv.certification_list",
    "cv.language_list",
    "cv.project_list",
}
SECTION_PLACEHOLDER_HINTS: dict[str, set[str]] = {
    "cv.identity_block": {"nom", "titre", "identity.full_name", "identity.title"},
    "cv.first_page_teaser_experiences": {"exp1_periode", "exp1_poste", "exp1_entreprise"},
    "cv.key_skills_list": {"competence_cle_1"},
    "cv.technical_skills_block": {"tech_data_bi", "tech_dev", "tech_cloud", "tech_gestion_1", "tech_gestion_2"},
    "cv.domain_skills_block": {"competences_metiers"},
    "cv.experience_detail_list": {"exp1_entreprise_full", "exp1_periode_full", "exp1_role", "exp1_contexte"},
    "cv.education_list": {"formation_diplome", "formation_etablissement", "formation_annee"},
    "cv.certification_list": {"certif1_intitule_1", "certif1_intitule_2", "certif2_intitule"},
    "cv.language_list": {"langue_1", "langue_1_niveau"},
    "cv.project_list": {"project_1_name", "project_1_description"},
}


def compile_layout_spec(
    *,
    template_bytes: bytes,
    detected_variables: list[str] | None = None,
) -> dict[str, Any]:
    detected_variables = sorted({value for value in (detected_variables or []) if isinstance(value, str) and value.strip()})
    errors: list[str] = []
    warnings: list[str] = []

    try:
        with ZipFile(io.BytesIO(template_bytes)) as docx_zip:
            members = set(docx_zip.namelist())
            if "word/document.xml" not in members:
                return _unsupported_payload(
                    errors=["DOCX missing word/document.xml"],
                    warnings=[],
                )

            document_xml = docx_zip.read("word/document.xml").decode("utf-8", "ignore")
            document_root = ET.fromstring(document_xml)
            page = _extract_page_geometry(document_root)
            shell = _extract_shell_metadata(docx_zip, document_root)
            branding = _extract_branding(docx_zip, document_xml)
            anchored_candidates = _extract_anchor_candidates(document_root, document_xml)
            fixed_container_placeholders = _extract_textbox_placeholders(document_xml, detected_variables)
            heuristic_candidates = _build_heuristic_candidates(
                detected_variables=detected_variables,
                fixed_container_placeholders=fixed_container_placeholders,
            )

            candidates = _dedupe_candidates(anchored_candidates + heuristic_candidates)
            if not candidates:
                warnings.append("No semantic anchor or supported placeholder group candidate detected.")

            layout_spec = {
                "version": LAYOUT_SPEC_VERSION,
                "page": page,
                "shell": shell,
                "branding": branding,
                "supported_sections": deepcopy(SUPPORTED_SECTION_SPECS),
                "candidates": candidates,
                "confirmed_mappings": {},
                "sections": {},
                "rules": {
                    "omit_empty_optional_sections": True,
                    "omit_empty_labels": True,
                    "first_page_caps": {"experiences": 3, "key_skills": 10, "languages": 3},
                    "body_collections_unbounded": True,
                },
            }
    except ET.ParseError as exc:
        return _unsupported_payload(errors=[f"Unreadable document.xml: {exc}"], warnings=[])
    except Exception as exc:  # pragma: no cover - defensive fallback
        return _unsupported_payload(errors=[f"Unable to compile DOCX layout spec: {exc}"], warnings=[])

    return evaluate_layout_spec(
        layout_spec=layout_spec,
        extra_errors=errors,
        extra_warnings=warnings,
    )


def update_layout_spec_confirmed_mappings(
    *,
    layout_spec: dict[str, Any],
    confirmed_mappings: dict[str, Any],
) -> dict[str, Any]:
    updated = deepcopy(layout_spec if isinstance(layout_spec, dict) else {})
    updated["confirmed_mappings"] = _normalize_confirmed_mappings(
        confirmed_mappings=confirmed_mappings,
        candidates=updated.get("candidates") or [],
    )
    return evaluate_layout_spec(layout_spec=updated)


def evaluate_layout_spec(
    *,
    layout_spec: dict[str, Any],
    extra_errors: list[str] | None = None,
    extra_warnings: list[str] | None = None,
) -> dict[str, Any]:
    spec = deepcopy(layout_spec if isinstance(layout_spec, dict) else {})
    candidates = spec.get("candidates") or []
    errors = list(extra_errors or [])
    warnings = list(extra_warnings or [])
    sections: dict[str, dict[str, Any]] = {}

    for candidate in candidates:
        section_name = str(candidate.get("section_name_hint") or "").strip()
        anchor_type = str(candidate.get("anchor_type") or "").strip()
        if section_name in SUPPORTED_SECTION_SPECS and anchor_type in {"sdt", "bookmark"}:
            sections[section_name] = _build_section_assignment(
                section_name=section_name,
                candidate=candidate,
                confirmed=False,
                render_type=str(candidate.get("render_type_hint") or ""),
                style_source=str(candidate.get("candidate_id") or ""),
            )

    confirmed = spec.get("confirmed_mappings") or {}
    candidate_by_id = {
        str(candidate.get("candidate_id") or ""): candidate
        for candidate in candidates
        if str(candidate.get("candidate_id") or "")
    }
    for section_name, mapping in confirmed.items():
        if section_name not in SUPPORTED_SECTION_SPECS or not isinstance(mapping, dict):
            continue
        candidate_id = str(mapping.get("candidate_id") or "")
        candidate = candidate_by_id.get(candidate_id)
        if not candidate:
            errors.append(f"Confirmed mapping for {section_name} references unknown candidate {candidate_id}.")
            continue
        render_type = str(mapping.get("render_type") or SUPPORTED_SECTION_SPECS[section_name]["render_type"])
        if render_type not in SUPPORTED_RENDER_TYPES:
            errors.append(f"Unsupported render type {render_type} for {section_name}.")
            continue
        sections[section_name] = _build_section_assignment(
            section_name=section_name,
            candidate=candidate,
            confirmed=True,
            render_type=render_type,
            style_source=str(mapping.get("style_source") or candidate_id),
        )

    for section_name, assignment in sections.items():
        if section_name in BODY_SECTIONS and bool(assignment.get("inside_fixed_container")):
            errors.append(
                f"{section_name} cannot be code-driven because its mapped candidate lives inside a fixed-size container."
            )

    missing_required = sorted(section for section in REQUIRED_READY_SECTIONS if section not in sections)
    if missing_required:
        warnings.append("Missing required sections: " + ", ".join(missing_required))

    if "cv.first_page_teaser_experiences" not in sections and "cv.key_skills_list" not in sections:
        warnings.append("No compact first-page section is mapped yet.")

    if errors:
        status = LAYOUT_STATUS_UNSUPPORTED if not sections else LAYOUT_STATUS_PARTIAL
    elif not sections:
        status = LAYOUT_STATUS_UNSUPPORTED
    elif missing_required:
        status = LAYOUT_STATUS_PARTIAL
    elif "cv.first_page_teaser_experiences" not in sections and "cv.key_skills_list" not in sections:
        status = LAYOUT_STATUS_PARTIAL
    else:
        status = LAYOUT_STATUS_READY

    render_mode = RENDER_MODE_CODE_DRIVEN if status == LAYOUT_STATUS_READY else RENDER_MODE_LEGACY
    spec["sections"] = sections

    return {
        "render_mode": render_mode,
        "layout_spec_version": LAYOUT_SPEC_VERSION,
        "layout_spec_status": status,
        "layout_spec": spec,
        "layout_spec_errors": sorted(set(filter(None, errors))),
        "layout_spec_warnings": sorted(set(filter(None, warnings))),
    }


def _unsupported_payload(*, errors: list[str], warnings: list[str]) -> dict[str, Any]:
    return {
        "render_mode": RENDER_MODE_LEGACY,
        "layout_spec_version": LAYOUT_SPEC_VERSION,
        "layout_spec_status": LAYOUT_STATUS_UNSUPPORTED,
        "layout_spec": {
            "version": LAYOUT_SPEC_VERSION,
            "page": {},
            "shell": {},
            "branding": {},
            "supported_sections": deepcopy(SUPPORTED_SECTION_SPECS),
            "candidates": [],
            "confirmed_mappings": {},
            "sections": {},
            "rules": {
                "omit_empty_optional_sections": True,
                "omit_empty_labels": True,
                "first_page_caps": {"experiences": 3, "key_skills": 10, "languages": 3},
                "body_collections_unbounded": True,
            },
        },
        "layout_spec_errors": errors,
        "layout_spec_warnings": warnings,
    }


def _extract_page_geometry(root: ET.Element) -> dict[str, Any]:
    sect = root.find(".//w:sectPr", NS)
    if sect is None:
        return {}
    page_size = sect.find("w:pgSz", NS)
    page_margin = sect.find("w:pgMar", NS)
    return {
        "size": {
            "width": page_size.get(f"{{{WORD_NS}}}w") if page_size is not None else None,
            "height": page_size.get(f"{{{WORD_NS}}}h") if page_size is not None else None,
        },
        "orientation": page_size.get(f"{{{WORD_NS}}}orient", "portrait") if page_size is not None else "portrait",
        "margins": {
            "top": page_margin.get(f"{{{WORD_NS}}}top") if page_margin is not None else None,
            "right": page_margin.get(f"{{{WORD_NS}}}right") if page_margin is not None else None,
            "bottom": page_margin.get(f"{{{WORD_NS}}}bottom") if page_margin is not None else None,
            "left": page_margin.get(f"{{{WORD_NS}}}left") if page_margin is not None else None,
        },
    }


def _extract_shell_metadata(docx_zip: ZipFile, root: ET.Element) -> dict[str, Any]:
    rel_targets = _relationship_targets(docx_zip)
    sect = root.find(".//w:sectPr", NS)
    header_refs: list[str] = []
    footer_refs: list[str] = []
    if sect is not None:
        for tag_name, bucket in (("headerReference", header_refs), ("footerReference", footer_refs)):
            for element in sect.findall(f"w:{tag_name}", NS):
                rel_id = element.get(f"{{{REL_NS}}}id")
                if rel_id and rel_id in rel_targets:
                    bucket.append(rel_targets[rel_id])

    media_parts = sorted(name for name in docx_zip.namelist() if name.startswith("word/media/"))
    return {
        "preserve_header_footer_ooxml": True,
        "preserve_static_assets": True,
        "header_parts": header_refs,
        "footer_parts": footer_refs,
        "media_parts": media_parts,
    }


def _relationship_targets(docx_zip: ZipFile) -> dict[str, str]:
    if "word/_rels/document.xml.rels" not in docx_zip.namelist():
        return {}
    rel_root = ET.fromstring(docx_zip.read("word/_rels/document.xml.rels"))
    rels: dict[str, str] = {}
    for rel in rel_root:
        rel_id = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rel_id and target:
            rels[rel_id] = f"word/{target}" if not target.startswith("word/") else target
    return rels


def _extract_branding(docx_zip: ZipFile, document_xml: str) -> dict[str, Any]:
    color_matches = re.findall(r'w:color w:val="([0-9A-Fa-f]{6})"', document_xml)
    seen_colors: list[str] = []
    for color in color_matches:
        normalized = color.upper()
        if normalized in {"000000", "FFFFFF", "AUTO"} or normalized in seen_colors:
            continue
        seen_colors.append(normalized)
        if len(seen_colors) >= 2:
            break

    font_family = None
    if "word/styles.xml" in docx_zip.namelist():
        styles_xml = docx_zip.read("word/styles.xml").decode("utf-8", "ignore")
        font_match = re.search(r'w:rFonts[^>]*w:ascii="([^"]+)"', styles_xml)
        if font_match:
            font_family = font_match.group(1)

    return {
        "logo_refs": sorted(name for name in docx_zip.namelist() if name.startswith("word/media/")),
        "primary_color": seen_colors[0] if seen_colors else None,
        "secondary_color": seen_colors[1] if len(seen_colors) > 1 else None,
        "font_family": font_family,
    }


def _extract_anchor_candidates(root: ET.Element, document_xml: str) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for sdt in root.findall(".//w:sdt", NS):
        tag_node = sdt.find("w:sdtPr/w:tag", NS)
        if tag_node is None:
            continue
        tag_value = str(tag_node.get(f"{{{WORD_NS}}}val") or "").strip()
        if not tag_value:
            continue
        candidates.append(
            {
                "candidate_id": f"anchor:sdt:{tag_value}",
                "source": "anchor",
                "anchor_type": "sdt",
                "anchor": tag_value,
                "section_name_hint": tag_value if tag_value in SUPPORTED_SECTION_SPECS else "",
                "render_type_hint": SUPPORTED_SECTION_SPECS.get(tag_value, {}).get("render_type"),
                "inside_fixed_container": _anchor_is_inside_fixed_container(
                    document_xml=document_xml,
                    anchor_type="sdt",
                    anchor_value=tag_value,
                ),
                "confidence": "explicit",
                "placeholders": [],
                "preview_text": _node_text(sdt)[:240],
            }
        )

    for bookmark in root.findall(".//w:bookmarkStart", NS):
        name = str(bookmark.get(f"{{{WORD_NS}}}name") or "").strip()
        if not name or name.startswith("_"):
            continue
        candidates.append(
            {
                "candidate_id": f"anchor:bookmark:{name}",
                "source": "anchor",
                "anchor_type": "bookmark",
                "anchor": name,
                "section_name_hint": name if name in SUPPORTED_SECTION_SPECS else "",
                "render_type_hint": SUPPORTED_SECTION_SPECS.get(name, {}).get("render_type"),
                "inside_fixed_container": _anchor_is_inside_fixed_container(
                    document_xml=document_xml,
                    anchor_type="bookmark",
                    anchor_value=name,
                ),
                "confidence": "explicit",
                "placeholders": [],
                "preview_text": "",
            }
        )
    return candidates


def _anchor_is_inside_fixed_container(
    *,
    document_xml: str,
    anchor_type: str,
    anchor_value: str,
) -> bool:
    if not document_xml or not anchor_value:
        return False

    escaped_value = re.escape(str(anchor_value).strip())
    if not escaped_value:
        return False

    if anchor_type == "sdt":
        pattern = re.compile(rf'w:tag[^>]*w:val="{escaped_value}"')
    elif anchor_type == "bookmark":
        pattern = re.compile(rf'w:bookmarkStart[^>]*w:name="{escaped_value}"')
    else:
        return False

    return any(pattern.search(fragment) for fragment in TEXTBOX_PATTERN.findall(document_xml))


def _extract_textbox_placeholders(document_xml: str, detected_variables: list[str]) -> set[str]:
    found: set[str] = set()
    if not detected_variables:
        return found
    for match in TEXTBOX_PATTERN.findall(document_xml):
        text = _strip_xml(match)
        normalized_text = " ".join(text.split())
        for variable in detected_variables:
            if variable and variable in normalized_text:
                found.add(variable)
    return found


def _build_heuristic_candidates(
    *,
    detected_variables: list[str],
    fixed_container_placeholders: set[str],
) -> list[dict[str, Any]]:
    detected_set = set(detected_variables)
    candidates: list[dict[str, Any]] = []
    for section_name, hints in SECTION_PLACEHOLDER_HINTS.items():
        matched = sorted(value for value in detected_set if value in hints)
        if not matched:
            continue
        candidates.append(
            {
                "candidate_id": f"heuristic:{section_name}",
                "source": "heuristic",
                "anchor_type": "placeholder_group",
                "anchor": section_name,
                "section_name_hint": section_name,
                "render_type_hint": SUPPORTED_SECTION_SPECS[section_name]["render_type"],
                "inside_fixed_container": any(value in fixed_container_placeholders for value in matched),
                "confidence": "candidate",
                "placeholders": matched,
                "preview_text": ", ".join(matched[:8]),
            }
        )
    return candidates


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        if not candidate_id:
            continue
        existing = deduped.get(candidate_id)
        if existing is None:
            deduped[candidate_id] = candidate
            continue
        existing_placeholders = set(existing.get("placeholders") or [])
        next_placeholders = sorted(existing_placeholders.union(candidate.get("placeholders") or []))
        existing["placeholders"] = next_placeholders
        existing["inside_fixed_container"] = bool(existing.get("inside_fixed_container")) or bool(candidate.get("inside_fixed_container"))
    return list(deduped.values())


def _normalize_confirmed_mappings(
    *,
    confirmed_mappings: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_ids = {str(candidate.get("candidate_id") or "") for candidate in candidates}
    normalized: dict[str, Any] = {}
    for section_name, payload in (confirmed_mappings or {}).items():
        if section_name not in SUPPORTED_SECTION_SPECS or not isinstance(payload, dict):
            continue
        candidate_id = str(payload.get("candidate_id") or "").strip()
        if not candidate_id or candidate_id not in candidate_ids:
            continue
        render_type = str(payload.get("render_type") or SUPPORTED_SECTION_SPECS[section_name]["render_type"]).strip()
        if render_type not in SUPPORTED_RENDER_TYPES:
            continue
        normalized[section_name] = {
            "candidate_id": candidate_id,
            "render_type": render_type,
            "style_source": str(payload.get("style_source") or candidate_id).strip(),
        }
    return normalized


def _build_section_assignment(
    *,
    section_name: str,
    candidate: dict[str, Any],
    confirmed: bool,
    render_type: str,
    style_source: str,
) -> dict[str, Any]:
    section_defaults = SUPPORTED_SECTION_SPECS[section_name]
    return {
        "anchor": str(candidate.get("anchor") or ""),
        "anchor_type": str(candidate.get("anchor_type") or ""),
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "required": bool(section_defaults["required"]),
        "render_type": render_type or section_defaults["render_type"],
        "bounded": bool(section_defaults["bounded"]),
        "max_items": section_defaults["max_items"],
        "style_source": style_source,
        "confirmed": confirmed,
        "inside_fixed_container": bool(candidate.get("inside_fixed_container")),
        "placeholders": list(candidate.get("placeholders") or []),
    }


def _strip_xml(xml_fragment: str) -> str:
    text = re.sub(r"<w:t[^>]*>", "\n", xml_fragment)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return text


def _node_text(node: ET.Element) -> str:
    parts: list[str] = []
    for text_node in node.findall(".//w:t", NS):
        if text_node.text:
            parts.append(text_node.text)
    return " ".join(" ".join(parts).split())
