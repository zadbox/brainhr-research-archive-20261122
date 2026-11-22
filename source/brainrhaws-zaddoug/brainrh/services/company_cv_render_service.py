from __future__ import annotations

import io
import re
import tempfile
from pathlib import Path
from typing import Any
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx import Document as WordDocument
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docxtpl import DocxTemplate
from fastapi import HTTPException, status

from brainrh.settings import is_company_cv_trace_enabled
from brainrh.services.company_cv_code_driven_renderer import (
    build_code_driven_render_snapshot,
    render_code_driven_docx,
)
from brainrh.services.company_cv_context_builder import build_company_cv_context
from brainrh.services.company_cv_generation_service import generate_company_cv_contract_payload
from brainrh.services.company_cv_mapping_service import (
    DOCX_CONTENT_TYPE,
    build_render_context,
    build_render_trace,
    find_unrendered_markers,
    render_context_fingerprint,
)
from brainrh.services.company_cv_template_service import CompanyCvTemplateService
from brainrh.services.file_storage import FileStorage


def _slug(value: str) -> str:
    return "".join(character if character.isalnum() or character in {"_", "-"} else "_" for character in value.strip()).strip("_") or "candidate"


EMPTY_RENDER_LABEL_PATTERN = re.compile(
    r"^(?:Name|Email|Phone|Disponibilit[ée]|Projet/Contexte|Contexte\s*/\s*descriptif|Mission|Missions?\s*/\s*projets(?:\s*r[ée]alis[ée]s?)?|Point clé|Environnement\s*technique|Monitoring\s+Production|API\s+Services|Paiements\s+Normes\s+Bancaires)\s*[:：]?\s*[:：,.;\-\s]*$",
    flags=re.IGNORECASE,
)
TEMPLATE_INSTRUCTION_PATTERN = re.compile(
    r"^\s*(?:(?:=>|=+)\s*)?(?:(?:exp[ée]rience|missions?|projets?|environnement|comp[ée]tences?|langues?|formations?|certifications?|titre|profil|synth[èe]se|bloc|contenu)\s+attendu(?:e|es|s)?\b|exemples?\b|indiquer\b|renseigner\b|compl[eé]ter\b|remplir\b)",
    flags=re.IGNORECASE,
)
YEAR_RANGE_PLACEHOLDER_PATTERN = re.compile(r"^\s*\d{4}\s*[–-]\s*$")
LEADING_YEAR_WITH_LABEL_PATTERN = re.compile(r"^\s*(\d{4})\s*[–-]\s*(.+?)\s*$")
SEMANTIC_LABEL_PREFIX_PATTERN = re.compile(r"^(?:Projet/Contexte|Mission|Point clé)\s*[:：]\s*", flags=re.IGNORECASE)
AVAILABILITY_VALUE_PATTERN = re.compile(r"^\s*Disponibilit[ée]\s*[:：]\s*\S+", flags=re.IGNORECASE)
LITERAL_LIST_BULLET_PREFIX_PATTERN = re.compile(r"^[\s\xa0]*(?:[•●▪◦·\u2022]+\s*|[-–—]\s+)")
COMPANY_CV_RENDERER_VERSION = "company_cv_renderer.v12"
WORD_TEXT_PART_PATTERN = re.compile(r"^word/(?:document|header\d+|footer\d+|footnotes|endnotes|comments)\.xml$")
WORDPROCESSINGML_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD_PARAGRAPH_TAG = f"{{{WORDPROCESSINGML_NS}}}p"
WORD_TEXT_TAG = f"{{{WORDPROCESSINGML_NS}}}t"


def _normalize_text_for_cleanup(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("\xa0", " ")).strip()


def _looks_like_empty_render_paragraph(value: str) -> bool:
    normalized = _normalize_text_for_cleanup(value)
    if not normalized:
        return True
    if normalized in {":", ".", ",", ";", "-", "--", "•", "·", "–", "—"}:
        return True
    if re.fullmatch(r"[•·\-–—\s:：,.;]+", normalized):
        return True
    if TEMPLATE_INSTRUCTION_PATTERN.match(normalized):
        return True
    if YEAR_RANGE_PLACEHOLDER_PATTERN.match(normalized):
        return True
    return bool(EMPTY_RENDER_LABEL_PATTERN.match(normalized))


def _looks_like_template_instruction_paragraph(value: str) -> bool:
    normalized = _normalize_text_for_cleanup(value)
    return bool(normalized and TEMPLATE_INSTRUCTION_PATTERN.match(normalized))


def _delete_paragraph(paragraph) -> None:
    element = paragraph._element
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)


def _register_xml_namespaces(xml_bytes: bytes) -> None:
    try:
        for _, namespace in ET.iterparse(io.BytesIO(xml_bytes), events=("start-ns",)):
            prefix, uri = namespace
            try:
                ET.register_namespace(prefix or "", uri)
            except ValueError:
                continue
    except ET.ParseError:
        return


def _word_paragraph_text_xml(paragraph: ET.Element) -> str:
    return "".join(text_node.text or "" for text_node in paragraph.iter(WORD_TEXT_TAG))


def _xml_local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _paragraph_has_xml_child(paragraph: ET.Element, local_name: str) -> bool:
    return any(_xml_local_name(element.tag) == local_name for element in paragraph.iter())


def _paragraph_has_visual_marker_xml(paragraph: ET.Element) -> bool:
    visual_markers = {"AlternateContent", "drawing", "pict"}
    return any(_xml_local_name(element.tag) in visual_markers for element in paragraph.iter())


def _strip_literal_list_bullet_from_first_text_node(paragraph: ET.Element) -> bool:
    for text_node in paragraph.iter(WORD_TEXT_TAG):
        value = text_node.text or ""
        if not value.replace("\xa0", " ").strip():
            continue
        cleaned_value = LITERAL_LIST_BULLET_PREFIX_PATTERN.sub("", value, count=1)
        if cleaned_value == value:
            return False
        text_node.text = cleaned_value
        return True
    return False


def _remove_template_instruction_paragraphs_from_xml(xml_bytes: bytes) -> tuple[bytes, int]:
    _register_xml_namespaces(xml_bytes)
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return xml_bytes, 0

    parent_by_child = {child: parent for parent in root.iter() for child in parent}
    removed_count = 0
    for paragraph in list(root.iter(WORD_PARAGRAPH_TAG)):
        if not _looks_like_template_instruction_paragraph(_word_paragraph_text_xml(paragraph)):
            continue
        parent = parent_by_child.get(paragraph)
        if parent is None:
            continue
        parent.remove(paragraph)
        removed_count += 1

    if not removed_count:
        return xml_bytes, 0
    return ET.tostring(root, encoding="utf-8", xml_declaration=xml_bytes.lstrip().startswith(b"<?xml")), removed_count


def _strip_numbered_literal_bullets_from_xml(xml_bytes: bytes) -> tuple[bytes, int]:
    _register_xml_namespaces(xml_bytes)
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return xml_bytes, 0

    changed_count = 0
    for paragraph in root.iter(WORD_PARAGRAPH_TAG):
        if not _paragraph_has_xml_child(paragraph, "numPr"):
            continue
        if _strip_literal_list_bullet_from_first_text_node(paragraph):
            changed_count += 1

    if not changed_count:
        return xml_bytes, 0
    return ET.tostring(root, encoding="utf-8", xml_declaration=xml_bytes.lstrip().startswith(b"<?xml")), changed_count


def _clear_availability_value_text_from_xml(xml_bytes: bytes) -> tuple[bytes, int]:
    _register_xml_namespaces(xml_bytes)
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return xml_bytes, 0

    changed_count = 0
    for paragraph in root.iter(WORD_PARAGRAPH_TAG):
        normalized_paragraph_text = _normalize_text_for_cleanup(_word_paragraph_text_xml(paragraph))
        if "disponibilit" not in normalized_paragraph_text.casefold():
            continue
        changed_node_count = 0
        for text_node in paragraph.iter(WORD_TEXT_TAG):
            normalized_node_text = _normalize_text_for_cleanup(text_node.text or "")
            if (
                AVAILABILITY_VALUE_PATTERN.search(normalized_node_text)
                or "disponibilit" in normalized_node_text.casefold()
                or "immédiate" in normalized_node_text.casefold()
            ):
                text_node.text = ""
                changed_node_count += 1
        if changed_node_count:
            changed_count += 1

    if not changed_count:
        return xml_bytes, 0
    return ET.tostring(root, encoding="utf-8", xml_declaration=xml_bytes.lstrip().startswith(b"<?xml")), changed_count


def _remove_empty_render_paragraphs_from_xml(xml_bytes: bytes) -> tuple[bytes, int]:
    _register_xml_namespaces(xml_bytes)
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return xml_bytes, 0

    parent_by_child = {child: parent for parent in root.iter() for child in parent}
    removed_count = 0
    for paragraph in list(root.iter(WORD_PARAGRAPH_TAG)):
        if _paragraph_has_visual_marker_xml(paragraph):
            continue
        if not _looks_like_empty_render_paragraph(_word_paragraph_text_xml(paragraph)):
            continue
        parent = parent_by_child.get(paragraph)
        if parent is None:
            continue
        parent.remove(paragraph)
        removed_count += 1

    if not removed_count:
        return xml_bytes, 0
    return ET.tostring(root, encoding="utf-8", xml_declaration=xml_bytes.lstrip().startswith(b"<?xml")), removed_count


def _cleanup_template_instruction_xml_parts(output_path: Path) -> None:
    cleanup_path = output_path.with_suffix(".xml-cleanup.docx")
    removed_count = 0

    with ZipFile(output_path, "r") as source, ZipFile(cleanup_path, "w") as target:
        for entry in source.infolist():
            entry_bytes = source.read(entry.filename)
            if WORD_TEXT_PART_PATTERN.match(entry.filename):
                entry_bytes, entry_removed_count = _remove_template_instruction_paragraphs_from_xml(entry_bytes)
                removed_count += entry_removed_count
            target.writestr(entry, entry_bytes)

    if removed_count:
        cleanup_path.replace(output_path)
    else:
        cleanup_path.unlink(missing_ok=True)


def _cleanup_literal_list_bullet_xml_parts(output_path: Path) -> None:
    cleanup_path = output_path.with_suffix(".xml-cleanup.docx")
    changed_count = 0

    with ZipFile(output_path, "r") as source, ZipFile(cleanup_path, "w") as target:
        for entry in source.infolist():
            entry_bytes = source.read(entry.filename)
            if WORD_TEXT_PART_PATTERN.match(entry.filename):
                entry_bytes, entry_changed_count = _strip_numbered_literal_bullets_from_xml(entry_bytes)
                changed_count += entry_changed_count
            target.writestr(entry, entry_bytes)

    if changed_count:
        cleanup_path.replace(output_path)
    else:
        cleanup_path.unlink(missing_ok=True)


def _cleanup_availability_value_xml_parts(output_path: Path) -> None:
    cleanup_path = output_path.with_suffix(".xml-cleanup.docx")
    changed_count = 0

    with ZipFile(output_path, "r") as source, ZipFile(cleanup_path, "w") as target:
        for entry in source.infolist():
            entry_bytes = source.read(entry.filename)
            if WORD_TEXT_PART_PATTERN.match(entry.filename):
                entry_bytes, entry_changed_count = _clear_availability_value_text_from_xml(entry_bytes)
                changed_count += entry_changed_count
            target.writestr(entry, entry_bytes)

    if changed_count:
        cleanup_path.replace(output_path)
    else:
        cleanup_path.unlink(missing_ok=True)


def _cleanup_empty_render_xml_parts(output_path: Path) -> None:
    cleanup_path = output_path.with_suffix(".xml-cleanup.docx")
    removed_count = 0

    with ZipFile(output_path, "r") as source, ZipFile(cleanup_path, "w") as target:
        for entry in source.infolist():
            entry_bytes = source.read(entry.filename)
            if WORD_TEXT_PART_PATTERN.match(entry.filename):
                entry_bytes, entry_removed_count = _remove_empty_render_paragraphs_from_xml(entry_bytes)
                removed_count += entry_removed_count
            target.writestr(entry, entry_bytes)

    if removed_count:
        cleanup_path.replace(output_path)
    else:
        cleanup_path.unlink(missing_ok=True)


def _save_trace_text(path: str, content: str) -> None:
    FileStorage.save_bytes(
        path,
        content.encode("utf-8"),
        content_type="text/plain; charset=utf-8",
    )


def _persist_llm_trace_artifacts(
    *,
    base_storage_path: str,
    output_bytes: bytes,
    generation_trace: dict[str, Any],
    llm_trace_payload: dict[str, Any] | None,
    template_record: dict[str, Any],
    enterprise_id: str,
    project_id: str,
    sheet_id: str,
    render_fingerprint: str,
) -> str | None:
    if not is_company_cv_trace_enabled() or not isinstance(llm_trace_payload, dict):
        return None

    llm_trace_prefix = f"{base_storage_path}.llm"
    manifest_path = f"{llm_trace_prefix}/00-manifest.json"
    generation_prompt_path = f"{llm_trace_prefix}/01-generation-prompt.txt"
    generation_raw_path = f"{llm_trace_prefix}/02-generation-response.raw.txt"
    generation_parsed_path = f"{llm_trace_prefix}/03-generation-response.parsed.json"
    verification_prompt_path = f"{llm_trace_prefix}/04-verification-prompt.txt"
    verification_raw_path = f"{llm_trace_prefix}/05-verification-response.raw.txt"
    verification_parsed_path = f"{llm_trace_prefix}/06-verification-response.parsed.json"
    final_docx_path = f"{llm_trace_prefix}/07-final-docx.docx"

    _save_trace_text(generation_prompt_path, str(llm_trace_payload.get("generation_prompt") or ""))
    _save_trace_text(generation_raw_path, str(llm_trace_payload.get("generation_response_raw") or ""))
    if isinstance(llm_trace_payload.get("generation_response_parsed"), dict):
        FileStorage.save_json(generation_parsed_path, llm_trace_payload["generation_response_parsed"])
    _save_trace_text(verification_prompt_path, str(llm_trace_payload.get("verification_prompt") or ""))
    _save_trace_text(verification_raw_path, str(llm_trace_payload.get("verification_response_raw") or ""))
    if isinstance(llm_trace_payload.get("verification_response_parsed"), dict):
        FileStorage.save_json(verification_parsed_path, llm_trace_payload["verification_response_parsed"])
    FileStorage.save_bytes(
        final_docx_path,
        output_bytes,
        content_type=DOCX_CONTENT_TYPE,
    )

    manifest = {
        "sheet_id": sheet_id,
        "enterprise_id": enterprise_id,
        "project_id": project_id,
        "template_id": template_record.get("id"),
        "template_name": template_record.get("name"),
        "render_fingerprint": render_fingerprint,
        "provider": generation_trace.get("provider"),
        "model": generation_trace.get("model"),
        "trace_enabled": True,
        "generation_parse_error": llm_trace_payload.get("generation_parse_error"),
        "verification_parse_error": llm_trace_payload.get("verification_parse_error"),
        "files": {
            "generation_prompt": generation_prompt_path,
            "generation_response_raw": generation_raw_path,
            "generation_response_parsed": generation_parsed_path,
            "verification_prompt": verification_prompt_path,
            "verification_response_raw": verification_raw_path,
            "verification_response_parsed": verification_parsed_path,
            "final_docx": final_docx_path,
        },
    }
    FileStorage.save_json(manifest_path, manifest)
    return llm_trace_prefix


def _iter_table_paragraphs(table):
    for row in table.rows:
        for cell in row.cells:
            for paragraph in cell.paragraphs:
                yield paragraph
            for nested_table in cell.tables:
                yield from _iter_table_paragraphs(nested_table)


def _iter_unique_table_cells(table):
    seen: set[int] = set()
    for row in table.rows:
        for cell in row.cells:
            cell_id = id(cell._tc)
            if cell_id in seen:
                continue
            seen.add(cell_id)
            yield cell


def _set_run_font(
    run,
    *,
    size_pt: float,
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
    color: str = "6F6F6F",
    font_name: str = "Arial",
) -> None:
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run.font.italic = italic
    run.font.underline = underline
    run.font.color.rgb = RGBColor.from_string(color)
    r_pr = run._element.get_or_add_rPr()
    r_fonts = r_pr.rFonts
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.append(r_fonts)
    r_fonts.set(qn("w:ascii"), font_name)
    r_fonts.set(qn("w:hAnsi"), font_name)


def _set_cell_lines(
    cell,
    lines: list[str],
    *,
    size_pt: float,
    bold: bool = False,
    italic: bool = False,
    underline: bool = False,
    color: str = "6F6F6F",
) -> None:
    cell.text = ""
    paragraphs = cell.paragraphs
    for index, line in enumerate(lines):
        paragraph = paragraphs[0] if index == 0 else cell.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(1)
        paragraph.paragraph_format.line_spacing = 1.0
        run = paragraph.add_run(line)
        _set_run_font(
            run,
            size_pt=size_pt,
            bold=bold,
            italic=italic,
            underline=underline,
            color=color,
        )


def _format_cell_paragraphs(cell, *, size_pt: float = 8.5, color: str = "6F6F6F") -> None:
    for paragraph in cell.paragraphs:
        paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(1)
        paragraph.paragraph_format.line_spacing = 1.0


def _format_education_line(item: dict[str, Any]) -> str:
    year = str(item.get("year") or item.get("end_date") or "").strip()
    degree = str(item.get("degree") or "").strip()
    institution = str(item.get("institution") or "").strip()
    return " - ".join(value for value in (year, degree, institution) if value)


def _format_certification_line(item: dict[str, Any]) -> str:
    year = str(item.get("year") or "").strip()
    name = str(item.get("name") or "").strip()
    issuer = str(item.get("issuer") or "").strip()
    return " - ".join(value for value in (year, name, issuer) if value)


def _format_language_line(item: dict[str, Any]) -> str:
    name = str(item.get("name") or "").strip()
    level = str(item.get("level") or "").strip()
    if name and level:
        return f"{name} : {level}"
    return name or level


def _support_section_lines(canonical_context: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    education_lines = [
        line
        for item in canonical_context.get("education") or []
        if isinstance(item, dict)
        for line in [_format_education_line(item)]
        if line
    ]
    certification_lines = [
        line
        for item in canonical_context.get("certifications") or []
        if isinstance(item, dict)
        for line in [_format_certification_line(item)]
        if line
    ]
    language_lines = [
        line
        for item in canonical_context.get("languages") or []
        if isinstance(item, dict)
        for line in [_format_language_line(item)]
        if line
    ]

    return education_lines, certification_lines, language_lines


def _table_text(table) -> str:
    return "\n".join(cell.text for cell in _iter_unique_table_cells(table))


def _looks_like_support_section_table(table) -> bool:
    normalized = _normalize_text_for_cleanup(_table_text(table)).casefold()
    return "formation/certification" in normalized and "langues" in normalized


def _rewrite_support_section_table(table, canonical_context: dict[str, Any]) -> bool:
    education_lines, certification_lines, language_lines = _support_section_lines(canonical_context)
    if not education_lines and not certification_lines and not language_lines:
        return False
    if len(table.rows) < 2 or len(table.rows[0].cells) < 4:
        return False

    for cell in _iter_unique_table_cells(table):
        cell.text = ""

    support_lines = ["Formation/Certification"]
    support_lines.extend(education_lines)
    if certification_lines:
        support_lines.append("Certifications")
        support_lines.extend(certification_lines)
    if language_lines:
        support_lines.append("Langues")
        support_lines.extend(language_lines)

    support_cell = table.rows[0].cells[1]
    _set_cell_lines(support_cell, support_lines, size_pt=8.5, bold=False, color="6F6F6F")
    for paragraph in support_cell.paragraphs:
        normalized_text = _normalize_text_for_cleanup(paragraph.text)
        if normalized_text in {"Formation/Certification", "Certifications", "Langues"}:
            for run in paragraph.runs:
                _set_run_font(run, size_pt=9.5, bold=True, italic=normalized_text != "Formation/Certification", underline=True, color="004A73" if normalized_text != "Formation/Certification" else "6F6F6F")
        elif normalized_text.startswith("Anglais") or ":" in normalized_text and normalized_text in set(language_lines):
            for run in paragraph.runs:
                _set_run_font(run, size_pt=8.5, bold=True, italic=True, color="004A73")

    for cell in _iter_unique_table_cells(table):
        _format_cell_paragraphs(cell)
    return True


def _rewrite_support_sections(document: WordDocument, canonical_context: dict[str, Any]) -> None:
    if not isinstance(canonical_context, dict):
        return
    for table in document.tables:
        if _looks_like_support_section_table(table):
            _rewrite_support_section_table(table, canonical_context)


def _cleanup_overlapping_key_skills_heading(document: WordDocument) -> None:
    for table in document.tables:
        for paragraph in _iter_table_paragraphs(table):
            if _normalize_text_for_cleanup(paragraph.text).casefold() == "compétences clés":
                if not paragraph.runs:
                    paragraph.add_run("Compétences Clés")
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(8)
                for run in paragraph.runs:
                    _set_run_font(run, size_pt=11, bold=True, underline=False, color="FFFFFF")


def _rewrite_certification_years(document: WordDocument, certifications: list[dict[str, Any]]) -> None:
    normalized_certifications = [
        {
            "name": _normalize_text_for_cleanup(str(item.get("name") or "")),
            "year": str(item.get("year") or "").strip(),
        }
        for item in certifications
        if isinstance(item, dict) and str(item.get("name") or "").strip() and str(item.get("year") or "").strip()
    ]
    if not normalized_certifications:
        return

    paragraphs = list(document.paragraphs)
    for table in document.tables:
        paragraphs.extend(list(_iter_table_paragraphs(table)))

    for paragraph in paragraphs:
        text = paragraph.text or ""
        normalized_text = _normalize_text_for_cleanup(text)
        match = LEADING_YEAR_WITH_LABEL_PATTERN.match(normalized_text)
        if not match:
            continue
        rendered_year, rendered_label = match.groups()
        normalized_label = _normalize_text_for_cleanup(rendered_label)
        for cert in normalized_certifications:
            if cert["name"] and cert["name"] in normalized_label and cert["year"] != rendered_year:
                for run in paragraph.runs:
                    run.text = ""
                if paragraph.runs:
                    paragraph.runs[0].text = f"{cert['year']} – {rendered_label}"
                else:
                    paragraph.add_run(f"{cert['year']} – {rendered_label}")
                break


def _paragraph_semantic_key(value: str) -> str:
    normalized = _normalize_text_for_cleanup(value)
    normalized = SEMANTIC_LABEL_PREFIX_PATTERN.sub("", normalized)
    return normalized


def _dedupe_repeated_paragraphs(document: WordDocument) -> None:
    recent_keys: list[str] = []
    paragraphs_to_remove = []

    for paragraph in document.paragraphs:
        key = _paragraph_semantic_key(paragraph.text or "")
        if not key:
            continue
        if len(key) >= 20 and key in recent_keys:
            paragraphs_to_remove.append(paragraph)
            continue
        recent_keys.append(key)
        if len(recent_keys) > 6:
            recent_keys.pop(0)

    for paragraph in paragraphs_to_remove:
        _delete_paragraph(paragraph)


def _cleanup_rendered_docx(output_path: Path, canonical_context: dict[str, Any]) -> None:
    document = WordDocument(str(output_path))
    paragraphs_to_remove = []

    _rewrite_certification_years(
        document,
        canonical_context.get("certifications", []) if isinstance(canonical_context, dict) else [],
    )
    _dedupe_repeated_paragraphs(document)
    _rewrite_support_sections(document, canonical_context)
    _cleanup_overlapping_key_skills_heading(document)

    for paragraph in document.paragraphs:
        if _looks_like_empty_render_paragraph(paragraph.text):
            paragraphs_to_remove.append(paragraph)

    for table in document.tables:
        for paragraph in _iter_table_paragraphs(table):
            if _looks_like_empty_render_paragraph(paragraph.text):
                paragraphs_to_remove.append(paragraph)

    for paragraph in paragraphs_to_remove:
        _delete_paragraph(paragraph)

    document.save(str(output_path))
    _cleanup_template_instruction_xml_parts(output_path)
    _cleanup_literal_list_bullet_xml_parts(output_path)
    _cleanup_availability_value_xml_parts(output_path)
    _cleanup_empty_render_xml_parts(output_path)


class CompanyCvRenderService:
    @staticmethod
    def build_context(
        sheet_id: str,
        *,
        generation_guidance: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
        context, sheet, project, enterprise = build_company_cv_context(
            sheet_id,
            generation_guidance=generation_guidance,
        )
        return context.model_dump(mode="json"), sheet, project, enterprise

    @staticmethod
    def render_company_cv(
        sheet_id: str,
        template_id: str | None = None,
        *,
        generation_guidance: str | None = None,
    ) -> dict[str, Any]:
        canonical_context, sheet, project, enterprise = CompanyCvRenderService.build_context(
            sheet_id,
            generation_guidance=generation_guidance,
        )
        enterprise_id = project["enterprise_id"]
        template, template_bytes = CompanyCvTemplateService.load_template_bytes(enterprise_id, template_id)
        tenant_id = template.get("tenant_id") or enterprise.get("tenant_id")

        if not template.get("is_valid"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The selected company CV template has unresolved or ambiguous placeholders.",
            )

        generation_trace: dict[str, Any] | None = None
        llm_trace_payload: dict[str, Any] | None = None
        if template.get("contract_version") and template.get("template_contract"):
            generation_payload = generate_company_cv_contract_payload(
                sheet_id=sheet_id,
                template=template,
                generation_guidance=generation_guidance,
            )
            canonical_context = generation_payload["canonical_context"]
            render_context = generation_payload["render_context"]
            generation_trace = generation_payload["generation_trace"]
            llm_trace_payload = generation_payload.get("llm_trace_payload")
        else:
            render_context, missing_required = build_render_context(template, canonical_context)
            if missing_required:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "Company CV generation blocked because critical template placeholders are missing data: "
                        + ", ".join(missing_required)
                    ),
                )

        if _use_code_driven_render(template):
            render_context = {
                "mode": "code_driven",
                "snapshot": build_code_driven_render_snapshot(
                    canonical_context=canonical_context,
                    layout_spec=template.get("layout_spec") or {},
                ),
            }

        candidate_filename = canonical_context["identity"]["source_filename"] or sheet["candidate_id"]
        candidate_safe = _slug(Path(candidate_filename).stem)
        template_safe = _slug(template.get("name") or template.get("original_filename") or "template")
        output_filename = f"{candidate_safe}_{template_safe}.docx"
        render_fingerprint = render_context_fingerprint(
            template_record=template,
            canonical_context=canonical_context,
            render_context=render_context,
            sheet_id=sheet_id,
            renderer_version=COMPANY_CV_RENDERER_VERSION,
        )
        base_storage_path = (
            f"enterprises/{enterprise_id}/projects/{project['id']}/generated_cvs/"
            f"{candidate_safe}/{render_fingerprint}"
        )
        storage_path = f"{base_storage_path}.docx"
        trace_storage_path = f"{base_storage_path}.trace.json"

        if FileStorage.file_exists(storage_path):
            llm_trace_prefix = None
            if generation_trace is not None:
                llm_trace_prefix = _persist_llm_trace_artifacts(
                    base_storage_path=base_storage_path,
                    output_bytes=FileStorage.load_bytes(storage_path),
                    generation_trace=generation_trace,
                    llm_trace_payload=llm_trace_payload,
                    template_record=template,
                    enterprise_id=enterprise_id,
                    project_id=project["id"],
                    sheet_id=sheet_id,
                    render_fingerprint=render_fingerprint,
                )
                if llm_trace_prefix:
                    generation_trace["llm_trace_prefix"] = llm_trace_prefix
            if not FileStorage.file_exists(trace_storage_path):
                trace_payload = build_render_trace(
                    template_record=template,
                    canonical_context=canonical_context,
                    render_context=render_context,
                    render_fingerprint=render_fingerprint,
                    tenant_id=tenant_id,
                    enterprise_id=enterprise_id,
                    project_id=project["id"],
                    sheet_id=sheet_id,
                )
                if generation_trace is not None:
                    trace_payload["generation"] = generation_trace
                FileStorage.save_json(trace_storage_path, trace_payload)
            return {
                "template": template,
                "context": canonical_context,
                "render_context": render_context,
                "storage_path": storage_path,
                "trace_storage_path": trace_storage_path,
                "filename": output_filename,
                "content_type": DOCX_CONTENT_TYPE,
                "bytes": FileStorage.load_bytes(storage_path),
                "tenant_id": tenant_id,
                "enterprise_id": enterprise_id,
                "project_id": project["id"],
                "sheet_id": sheet_id,
                "render_fingerprint": render_fingerprint,
            }

        with tempfile.TemporaryDirectory(prefix="brainrh-company-cv-") as tmp_dir:
            template_path = Path(tmp_dir) / "template.docx"
            output_path = Path(tmp_dir) / output_filename
            template_path.write_bytes(template_bytes)

            try:
                if _use_code_driven_render(template):
                    render_code_driven_docx(
                        template_path=template_path,
                        output_path=output_path,
                        canonical_context=canonical_context,
                        layout_spec=template.get("layout_spec") or {},
                    )
                else:
                    doc = DocxTemplate(str(template_path))
                    doc.render(render_context)
                    doc.save(str(output_path))
                _cleanup_rendered_docx(output_path, canonical_context)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unable to render company CV with the validated template: {exc}",
                ) from exc

            output_bytes = output_path.read_bytes()

        remaining_markers = find_unrendered_markers(output_bytes)
        if remaining_markers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Rendered DOCX still contains template markers, generation blocked: "
                    + ", ".join(remaining_markers[:10])
                ),
            )

        trace_payload = build_render_trace(
            template_record=template,
            canonical_context=canonical_context,
            render_context=render_context,
            render_fingerprint=render_fingerprint,
            tenant_id=tenant_id,
            enterprise_id=enterprise_id,
            project_id=project["id"],
            sheet_id=sheet_id,
        )
        if generation_trace is not None:
            llm_trace_prefix = _persist_llm_trace_artifacts(
                base_storage_path=base_storage_path,
                output_bytes=output_bytes,
                generation_trace=generation_trace,
                llm_trace_payload=llm_trace_payload,
                template_record=template,
                enterprise_id=enterprise_id,
                project_id=project["id"],
                sheet_id=sheet_id,
                render_fingerprint=render_fingerprint,
            )
            if llm_trace_prefix:
                generation_trace["llm_trace_prefix"] = llm_trace_prefix
            trace_payload["generation"] = generation_trace
        FileStorage.save_bytes(storage_path, output_bytes, content_type=DOCX_CONTENT_TYPE)
        FileStorage.save_json(trace_storage_path, trace_payload)

        return {
            "template": template,
            "context": canonical_context,
            "render_context": render_context,
            "storage_path": storage_path,
            "trace_storage_path": trace_storage_path,
            "filename": output_filename,
            "content_type": DOCX_CONTENT_TYPE,
            "bytes": output_bytes,
            "tenant_id": tenant_id,
            "enterprise_id": enterprise_id,
            "project_id": project["id"],
            "sheet_id": sheet_id,
            "render_fingerprint": render_fingerprint,
        }


def _use_code_driven_render(template_record: dict[str, Any]) -> bool:
    if (
        str(template_record.get("render_mode") or "") != "code_driven"
        or str(template_record.get("layout_spec_status") or "") != "ready"
    ):
        return False
    return _layout_spec_supports_safe_code_driven_render(template_record)


def _layout_spec_supports_safe_code_driven_render(template_record: dict[str, Any]) -> bool:
    layout_spec = template_record.get("layout_spec") or {}
    sections = layout_spec.get("sections") or {}
    if not isinstance(sections, dict) or not sections:
        return False

    required_sections = ("cv.identity_block", "cv.experience_detail_list")
    safe_anchor_types = {"bookmark", "sdt"}

    for section_name in required_sections:
        section = sections.get(section_name)
        if not isinstance(section, dict):
            return False
        if str(section.get("anchor_type") or "") not in safe_anchor_types:
            return False
        if bool(section.get("inside_fixed_container")):
            return False

    for section in sections.values():
        if not isinstance(section, dict):
            continue
        anchor_type = str(section.get("anchor_type") or "")
        if anchor_type and anchor_type not in safe_anchor_types:
            return False
        if bool(section.get("inside_fixed_container")):
            return False

    return True
