from __future__ import annotations

import io
import json
import posixpath
import re
import subprocess
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from html import escape, unescape
from pathlib import Path
from typing import Any
from zipfile import ZipFile
from xml.etree import ElementTree as ET

from fastapi import HTTPException, status

from brainrh.services.company_cv_generation_service import (
    _build_experience_source_blocks,
    _filter_experiences_removed_by_guidance,
    _generation_guidance_exclusion_markers,
    _normalize_guidance_matchable_text,
    generate_company_cv_contract_payload,
)
from brainrh.services.company_cv_mapping_service import (
    DOCX_CONTENT_TYPE,
    build_render_trace,
    find_unrendered_markers,
    render_context_fingerprint,
)
from brainrh.services.company_cv_render_service import CompanyCvRenderService
from brainrh.services.company_cv_template_service import CompanyCvTemplateService
from brainrh.services.cv_service import CVService
from brainrh.services.file_storage import FileStorage
from lib.cv_parsing import extract_text_from_file


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
NS = {"w": WORD_NS, "r": REL_NS}
ET.register_namespace("w", WORD_NS)
ET.register_namespace("r", REL_NS)
HTML_RENDER_MODE = "html_docx"
HTML_RENDERER_VERSION = "company_cv_html_renderer.v36"
HTML_SPEC_VERSION = "company_cv_html_template_spec.v2"
HTML_INTERFACE_VERSION = "company_cv_html_interface.v2"
HTML_BINDING_MATRIX_VERSION = "company_cv_html_binding_matrix.v1"
HTML_CONTEXT_AUGMENTATION_VERSION = "render_context_experience_augmentation.v1"
HTML_OOXML_NORMALIZATION_VERSION = "html_docx_word_render_normalization.v14"
HTML_TEMPLATE_SHELL_VERSION = "template_shell_graft.v6"
HTML_OOXML_AUDIT_VERSION = "html_docx_word_ooxml_audit.v1"
HTML_SOURCE_FAITHFUL_VERSION = "source_faithful_absis_docx.v1"
HTML_SOURCE_CONTEXT_HINTS_VERSION = "source_docx_context_hints.v1"
DOC_REL_TYPE_HEADER = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/header"
DOC_REL_TYPE_FOOTER = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer"
ABSIS_SOURCE_STYLE_IDS = {
    "DISPOetEXPERIENCE",
    "Titrestabeau",
    "FONCTIONPRINCIPALE",
    "EnteteCaratristique",
    "Exprience",
    "Rle",
    "Mission",
    "DtailCaractristique",
    "Environnement",
    "ProjetNormal",
}
TEMPLATE_SHELL_CORE_PARTS = (
    "word/styles.xml",
    "word/stylesWithEffects.xml",
    "word/numbering.xml",
    "word/fontTable.xml",
    "word/theme/theme1.xml",
)
HTML_PAGE_WIDTH = "7.10in"
HTML_SIDEBAR_WIDTH = "0in"
HTML_MAIN_WIDTH = "7.10in"
HTML_MAIN_CONTENT_WIDTH = "6.78in"
HTML_EXPERIENCE_PERIOD_WIDTH = "1.35in"
HTML_EXPERIENCE_DETAIL_WIDTH = "5.43in"
HTML_TASK_BULLET_WIDTH = "0.16in"
HTML_TASK_TEXT_WIDTH = "5.25in"
HTML_ABSIS_META_WIDTH = "1.58in"
HTML_ABSIS_TITLE_WIDTH = "5.20in"
HTML_ABSIS_TEASER_PERIOD_WIDTH = "1.05in"
HTML_ABSIS_TEASER_DETAIL_WIDTH = "4.85in"
HTML_ABSIS_PRIMARY_COLOR = "004161"
HTML_ABSIS_ROLE_COLOR = "3DAAD6"
HTML_ABSIS_SECTION_TITLE_COLOR = "797979"
HTML_ABSIS_MUTED_COLOR = "808080"
HTML_ABSIS_ENVIRONMENT_COLOR = "0085C8"
HTML_ABSIS_BORDER_COLOR = "A9C9DA"
HTML_DEFAULT_FONT_FAMILY = "Calibri"
HTML_DEFAULT_FONT_SIZE_HALF_POINTS = 22
HTML_DEFAULT_LANG = "fr-FR"
DXA_PER_INCH = 1440
ABSIS_MAIN_CONTENT_DXA = 9763
ABSIS_IDENTITY_COLUMN_DXA = (7488, 2275)
ABSIS_SUPPORT_COLUMN_DXA = (4896, 4867)
ABSIS_TECHNICAL_COLUMN_DXA = (2448, 6883)
PARAGRAPH_PROPERTY_ORDER = (
    "pStyle",
    "keepNext",
    "keepLines",
    "pageBreakBefore",
    "framePr",
    "widowControl",
    "numPr",
    "suppressLineNumbers",
    "pBdr",
    "shd",
    "tabs",
    "suppressAutoHyphens",
    "kinsoku",
    "wordWrap",
    "overflowPunct",
    "topLinePunct",
    "autoSpaceDE",
    "autoSpaceDN",
    "bidi",
    "adjustRightInd",
    "snapToGrid",
    "spacing",
    "ind",
    "contextualSpacing",
    "mirrorIndents",
    "suppressOverlap",
    "jc",
    "textDirection",
    "textAlignment",
    "textboxTightWrap",
    "outlineLvl",
    "divId",
    "cnfStyle",
    "rPr",
    "sectPr",
    "pPrChange",
)
TABLE_PROPERTY_ORDER = (
    "tblStyle",
    "tblpPr",
    "tblOverlap",
    "bidiVisual",
    "tblStyleRowBandSize",
    "tblStyleColBandSize",
    "tblW",
    "jc",
    "tblCellSpacing",
    "tblInd",
    "tblBorders",
    "shd",
    "tblLayout",
    "tblCellMar",
    "tblLook",
    "tblCaption",
    "tblDescription",
    "tblPrChange",
)
TABLE_CELL_PROPERTY_ORDER = (
    "cnfStyle",
    "tcW",
    "gridSpan",
    "hMerge",
    "vMerge",
    "tcBorders",
    "shd",
    "noWrap",
    "tcMar",
    "textDirection",
    "tcFitText",
    "vAlign",
    "hideMark",
    "headers",
    "cellIns",
    "cellDel",
    "cellMerge",
    "tcPrChange",
)
TABLE_CELL_MARGIN_ORDER = ("top", "start", "left", "bottom", "end", "right")
TABLE_CELL_BORDER_ORDER = ("top", "start", "left", "bottom", "end", "right", "insideH", "insideV", "tl2br", "tr2bl")
PARAGRAPH_RUN_PROPERTY_TAGS = {
    "b",
    "bCs",
    "i",
    "iCs",
    "caps",
    "smallCaps",
    "strike",
    "dstrike",
    "outline",
    "shadow",
    "emboss",
    "imprint",
    "noProof",
    "vanish",
    "webHidden",
    "color",
    "w",
    "kern",
    "position",
    "sz",
    "szCs",
    "highlight",
    "u",
    "effect",
    "bdr",
    "fitText",
    "vertAlign",
    "rtl",
    "cs",
    "em",
    "lang",
    "eastAsianLayout",
    "specVanish",
    "oMath",
    "rFonts",
}
FORBIDDEN_HTML_LAYOUT_PATTERNS = (
    re.compile(r"display\s*:\s*(?:flex|grid)\b", flags=re.I),
    re.compile(r"position\s*:\s*(?:absolute|fixed|sticky)\b", flags=re.I),
    re.compile(r"@media\b", flags=re.I),
    re.compile(r"<style\b", flags=re.I),
    re.compile(r"<script\b", flags=re.I),
)


@dataclass(frozen=True)
class CompanyCvHtmlRenderPayload:
    html: str
    header_html: str
    footer_html: str
    document_options: dict[str, Any]
    trace: dict[str, Any]

    def model_dump(self) -> dict[str, Any]:
        return {
            "html": self.html,
            "headerHtml": self.header_html,
            "footerHtml": self.footer_html,
            "documentOptions": self.document_options,
            "trace": self.trace,
        }


@dataclass(frozen=True)
class SourceCvDocx:
    storage_path: str
    filename: str
    content_hash: str
    bytes: bytes


@dataclass(frozen=True)
class SourceCvDocxResolution:
    docx: SourceCvDocx | None
    reason: str
    error: str = ""


@dataclass(frozen=True)
class SourceCvTextResolution:
    text: str
    storage_path: str | None
    reason: str
    error: str = ""


class HtmlDocxStructuralError(RuntimeError):
    pass


def capture_company_cv_template_as_html_spec(
    *,
    template_bytes: bytes,
    template_name: str = "company-cv-template",
) -> dict[str, Any]:
    """Capture a DOCX template into a constrained HTML layout contract.

    This is intentionally not a generic DOCX-to-HTML converter. It extracts the
    reusable page, branding, header/footer, and section hints, then maps them to
    a BrainRH-owned table layout that is safe for HTML-to-DOCX conversion.
    """

    source_hash = sha256(template_bytes).hexdigest()
    page: dict[str, Any] = {}
    branding = {
        "font_family": HTML_DEFAULT_FONT_FAMILY,
        "primary_color": HTML_ABSIS_PRIMARY_COLOR,
        "secondary_color": HTML_ABSIS_ROLE_COLOR,
        "muted_color": HTML_ABSIS_MUTED_COLOR,
        "section_title_color": HTML_ABSIS_SECTION_TITLE_COLOR,
        "environment_color": HTML_ABSIS_ENVIRONMENT_COLOR,
        "border_color": HTML_ABSIS_BORDER_COLOR,
        "sidebar_background": "FFFFFF",
    }
    shell = {"header_text": "", "footer_text": "", "media_parts": []}
    warnings: list[str] = []

    try:
        with ZipFile(io.BytesIO(template_bytes)) as archive:
            members = set(archive.namelist())
            if "word/document.xml" not in members:
                warnings.append("DOCX package has no word/document.xml; default HTML shell used.")
            else:
                document_xml = archive.read("word/document.xml").decode("utf-8", "ignore")
                root = ET.fromstring(document_xml)
                page = _extract_page_options(root)
                branding.update(_extract_branding(archive, document_xml))
                shell.update(_extract_shell_text(archive, root))
    except Exception as exc:  # pragma: no cover - defensive fallback
        warnings.append(f"Unable to capture DOCX template shell: {exc}")

    return {
        "schema_version": HTML_SPEC_VERSION,
        "interface_version": HTML_INTERFACE_VERSION,
        "renderer_version": HTML_RENDERER_VERSION,
        "template_name": template_name,
        "source_hash": source_hash,
        "source_kind": "docx_template_capture",
        "layout_model": "word_safe_table_html",
        "rules": {
            "tables_only": False,
            "table_based_layout": True,
            "block_wrappers_allowed": ["div", "p"],
            "inline_styles_only": True,
            "forbidden_css": ["display:flex", "display:grid", "position:absolute", "@media"],
            "unbounded_sections": ["experiences", "education", "certifications", "languages", "projects"],
        },
        "page": page,
        "branding": branding,
        "shell": shell,
        "sections": _html_section_contract(),
        "binding_matrix": _build_html_binding_matrix(
            canonical_context={},
            template_record=None,
        ),
        "warnings": warnings,
    }


def build_company_cv_html_render_payload(
    *,
    canonical_context: dict[str, Any],
    template_record: dict[str, Any] | None = None,
    template_bytes: bytes | None = None,
    html_spec: dict[str, Any] | None = None,
) -> CompanyCvHtmlRenderPayload:
    canonical_context, guidance_experience_filter = _filter_experiences_removed_by_guidance(
        canonical_context,
    )
    if html_spec is None:
        html_spec = capture_company_cv_template_as_html_spec(
            template_bytes=template_bytes or b"",
            template_name=str((template_record or {}).get("name") or "company-cv-template"),
        )
    else:
        html_spec = deepcopy(html_spec)

    binding_matrix = _build_html_binding_matrix(
        canonical_context=canonical_context,
        template_record=template_record,
    )
    html_spec["interface_version"] = HTML_INTERFACE_VERSION
    html_spec["binding_matrix"] = binding_matrix

    html = render_company_cv_html(
        canonical_context=canonical_context,
        html_spec=html_spec,
    )
    validation_warnings = validate_word_safe_html(html)
    trace = {
        "renderer_version": HTML_RENDERER_VERSION,
        "interface_version": HTML_INTERFACE_VERSION,
        "template": {
            "id": (template_record or {}).get("id"),
            "name": (template_record or {}).get("name") or html_spec.get("template_name"),
            "content_hash": (template_record or {}).get("content_hash") or html_spec.get("source_hash"),
        },
        "html_spec": {
            "schema_version": html_spec.get("schema_version"),
            "interface_version": html_spec.get("interface_version"),
            "source_hash": html_spec.get("source_hash"),
            "layout_model": html_spec.get("layout_model"),
            "warnings": html_spec.get("warnings", []),
        },
        "binding_matrix": binding_matrix,
        "validation": {
            "word_safe": not validation_warnings,
            "warnings": validation_warnings,
        },
        "context": {
            "schema_version": canonical_context.get("schema_version"),
            "fingerprint": sha256(
                json.dumps(canonical_context, ensure_ascii=False, sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "generation_guidance_experience_filter": guidance_experience_filter,
        },
    }
    return CompanyCvHtmlRenderPayload(
        html=html,
        header_html=_render_header_footer_html(str((html_spec.get("shell") or {}).get("header_text") or ""), html_spec),
        footer_html=_render_header_footer_html(str((html_spec.get("shell") or {}).get("footer_text") or ""), html_spec),
        document_options=_document_options_from_spec(html_spec),
        trace=trace,
    )


def render_company_cv_html(
    *,
    canonical_context: dict[str, Any],
    html_spec: dict[str, Any],
) -> str:
    canonical_context, _guidance_experience_filter = _filter_experiences_removed_by_guidance(
        canonical_context,
    )
    branding = html_spec.get("branding") or {}
    font_family = _safe_font_family(str(branding.get("font_family") or HTML_DEFAULT_FONT_FAMILY))
    primary = _hex_color(branding.get("primary_color"), HTML_ABSIS_PRIMARY_COLOR)
    secondary = _hex_color(branding.get("secondary_color"), HTML_ABSIS_ROLE_COLOR)
    muted = _hex_color(branding.get("muted_color"), HTML_ABSIS_MUTED_COLOR)
    section_title = _hex_color(branding.get("section_title_color"), HTML_ABSIS_SECTION_TITLE_COLOR)
    environment = _hex_color(branding.get("environment_color"), HTML_ABSIS_ENVIRONMENT_COLOR)
    border = _hex_color(branding.get("border_color"), HTML_ABSIS_BORDER_COLOR)
    sidebar_bg = _hex_color(branding.get("sidebar_background"), "F4F8FA")
    binding_matrix = _dict(html_spec.get("binding_matrix"))
    binding_fingerprint = str(binding_matrix.get("fingerprint") or "")
    binding_matrix_html = _html_metadata_json(binding_matrix)

    identity = _dict(canonical_context.get("identity"))
    metrics = _dict(canonical_context.get("metrics"))
    skills = _dict(canonical_context.get("skills"))
    experiences = [_dict(item) for item in _list(canonical_context.get("experiences"))]
    education = [_dict(item) for item in _list(canonical_context.get("education"))]
    certifications = [_dict(item) for item in _list(canonical_context.get("certifications"))]
    languages = [_dict(item) for item in _list(canonical_context.get("languages"))]
    extra_sections = [_dict(item) for item in _list(canonical_context.get("extra_sections"))]

    body_style = f"font-family:{font_family};font-size:9.4pt;line-height:1.15;color:#{muted};margin:0;padding:0;"
    wrapper_style = f"width:{HTML_PAGE_WIDTH};margin:0;padding:8pt 4pt 4pt 4pt;"
    first_page_html = _render_absis_first_page(
        identity,
        canonical_context,
        metrics,
        skills,
        experiences,
        education,
        certifications,
        languages,
        extra_sections,
        primary,
        secondary,
        muted,
        section_title,
        environment,
        border,
    )
    detail_html = "".join(
        [
            _render_summary(canonical_context, section_title, muted),
            _render_experiences(experiences, primary, secondary, muted, section_title, environment, border),
        ]
    )
    detail_page_break_style = "page-break-before: always;"

    return "".join(
        [
            '<!doctype html><html><head><meta charset="utf-8">',
            f'<meta name="brainrh-interface-version" content="{escape(HTML_INTERFACE_VERSION, quote=True)}">',
            f'<meta name="brainrh-binding-matrix-version" content="{escape(HTML_BINDING_MATRIX_VERSION, quote=True)}">',
            f'<meta name="brainrh-binding-matrix-fingerprint" content="{escape(binding_fingerprint, quote=True)}">',
            f'<meta name="brainrh-binding-matrix" content="{escape(binding_matrix_html, quote=True)}">',
            f"<title>{escape(_first(identity.get('full_name'), 'Company CV'))}</title>",
            "</head>",
            f'<body {_data_attrs({"data-brain-interface-version": HTML_INTERFACE_VERSION})} style="{body_style}">',
            '<div role="presentation" data-layout="company-cv" '
            f'{_data_attrs({"data-brain-binding-fingerprint": binding_fingerprint})} style="{wrapper_style}">',
            first_page_html,
            "</div>",
            (
                f'<div data-section="absis-detail-pages" style="{wrapper_style}{detail_page_break_style}">'
                f"{detail_html}</div>"
                if detail_html
                else ""
            ),
            "</body></html>",
        ]
    )


def validate_word_safe_html(html: str) -> list[str]:
    warnings: list[str] = []
    for pattern in FORBIDDEN_HTML_LAYOUT_PATTERNS:
        if pattern.search(html):
            warnings.append(f"Unsupported Word-safe HTML construct detected: {pattern.pattern}")
    return warnings


def render_html_payload_to_docx_bytes(
    *,
    payload: CompanyCvHtmlRenderPayload,
    node_executable: str = "node",
    converter_script_path: Path | None = None,
) -> bytes:
    script_path = converter_script_path or _default_converter_script_path()
    if not script_path.exists():
        raise RuntimeError(f"Missing HTML-to-DOCX converter script: {script_path}")

    with tempfile.TemporaryDirectory(prefix="brainrh-html-docx-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "payload.json"
        output_path = tmp_path / "output.docx"
        input_path.write_text(json.dumps(payload.model_dump(), ensure_ascii=False), encoding="utf-8")

        completed = subprocess.run(
            [node_executable, str(script_path), str(input_path), str(output_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(
                "HTML-to-DOCX conversion failed. Install tools/company_cv_html_renderer "
                f"dependencies and retry. Details: {stderr}"
            )
        return _normalize_html_docx_table_grids(output_path.read_bytes())


def _normalize_html_docx_table_grids(docx_bytes: bytes) -> bytes:
    output = io.BytesIO()
    with ZipFile(io.BytesIO(docx_bytes)) as source, ZipFile(output, "w") as target:
        has_absis_template_styles = False
        if "word/styles.xml" in source.namelist():
            try:
                styles_root = ET.fromstring(source.read("word/styles.xml"))
                has_absis_template_styles = _has_absis_template_styles(styles_root)
            except ET.ParseError:
                has_absis_template_styles = False

        for info in source.infolist():
            payload = source.read(info.filename)
            if info.filename == "word/document.xml":
                payload = _normalize_table_grids_xml(payload)
                payload = _normalize_word_document_rendering_xml(
                    payload,
                    prefer_template_styles=has_absis_template_styles,
                )
                payload = _normalize_word_schema_xml(payload)
            elif info.filename == "word/styles.xml":
                payload = _normalize_word_style_defaults_xml(payload)
            target.writestr(info, payload)
    return output.getvalue()


def _finalize_html_docx_bytes(docx_bytes: bytes, template_bytes: bytes) -> bytes:
    output_bytes = _apply_template_shell_to_docx(docx_bytes, template_bytes)
    output_bytes = _normalize_html_docx_table_grids(output_bytes)
    _assert_html_docx_ooxml_stable(output_bytes)
    return output_bytes


def _assert_html_docx_ooxml_stable(docx_bytes: bytes) -> None:
    issues = _audit_html_docx_ooxml(docx_bytes)
    if issues:
        raise HtmlDocxStructuralError("; ".join(issues[:10]))


def _audit_html_docx_ooxml(docx_bytes: bytes) -> list[str]:
    issues: list[str] = []
    try:
        archive = ZipFile(io.BytesIO(docx_bytes))
    except Exception as exc:
        return [f"docx_zip_invalid:{exc}"]

    with archive:
        names = archive.namelist()
        duplicate_names = sorted({name for name in names if names.count(name) > 1})
        issues.extend(f"docx_zip_duplicate_entry:{name}" for name in duplicate_names)

        members = set(names)
        required_parts = {"[Content_Types].xml", "word/document.xml", "word/_rels/document.xml.rels"}
        for part in sorted(required_parts - members):
            issues.append(f"docx_missing_required_part:{part}")
        if issues:
            return issues

        parsed: dict[str, ET.Element] = {}
        for name in names:
            if not (name.endswith(".xml") or name.endswith(".rels")):
                continue
            try:
                parsed[name] = ET.fromstring(archive.read(name))
            except Exception as exc:
                issues.append(f"docx_xml_invalid:{name}:{exc}")
        if issues:
            return issues

        document_root = parsed.get("word/document.xml")
        rels_root = parsed.get("word/_rels/document.xml.rels")
        content_types_root = parsed.get("[Content_Types].xml")
        if document_root is not None and rels_root is not None and content_types_root is not None:
            issues.extend(
                _audit_header_footer_references(
                    document_root=document_root,
                    rels_root=rels_root,
                    content_types_root=content_types_root,
                    members=members,
                )
            )

        for name, root in parsed.items():
            if name.startswith("word/") and name.endswith(".xml"):
                if name == "word/document.xml":
                    issues.extend(_audit_schema_sensitive_ooxml(root, part_name=name))
                    issues.extend(_audit_word_tables(root, part_name=name))
                text = _xml_text(root)
                if any(marker in text for marker in ("**", "<u>", "</u>", "&lt;u&gt;", "&lt;/u&gt;")):
                    issues.append(f"visible_markup_marker:{name}")
    return issues


def _audit_schema_sensitive_ooxml(root: ET.Element, *, part_name: str) -> list[str]:
    issues: list[str] = []
    for index, paragraph_props in enumerate(root.iter(f"{{{WORD_NS}}}pPr"), start=1):
        direct_run_props = [
            _local_name(child.tag)
            for child in list(paragraph_props)
            if _local_name(child.tag) in PARAGRAPH_RUN_PROPERTY_TAGS
        ]
        if direct_run_props:
            issues.append(f"paragraph_run_property_in_pPr:{part_name}:{index}:{','.join(direct_run_props)}")
        if _known_child_order_is_invalid(paragraph_props, PARAGRAPH_PROPERTY_ORDER):
            issues.append(f"paragraph_property_order_invalid:{part_name}:{index}")

    for index, table_props in enumerate(root.iter(f"{{{WORD_NS}}}tblPr"), start=1):
        if _known_child_order_is_invalid(table_props, TABLE_PROPERTY_ORDER):
            issues.append(f"table_property_order_invalid:{part_name}:{index}")

    for index, cell_props in enumerate(root.iter(f"{{{WORD_NS}}}tcPr"), start=1):
        if _known_child_order_is_invalid(cell_props, TABLE_CELL_PROPERTY_ORDER):
            issues.append(f"table_cell_property_order_invalid:{part_name}:{index}")

    for index, borders in enumerate(root.iter(f"{{{WORD_NS}}}tcBorders"), start=1):
        if _known_child_order_is_invalid(borders, TABLE_CELL_BORDER_ORDER):
            issues.append(f"table_cell_border_order_invalid:{part_name}:{index}")

    for index, margins in enumerate(root.iter(f"{{{WORD_NS}}}tblCellMar"), start=1):
        if _known_child_order_is_invalid(margins, TABLE_CELL_MARGIN_ORDER):
            issues.append(f"table_cell_margin_order_invalid:{part_name}:{index}")
    return issues


def _known_child_order_is_invalid(parent: ET.Element, order: tuple[str, ...]) -> bool:
    order_index = {name: index for index, name in enumerate(order)}
    known_positions = [
        order_index[_local_name(child.tag)]
        for child in list(parent)
        if _local_name(child.tag) in order_index
    ]
    return known_positions != sorted(known_positions)


def _audit_header_footer_references(
    *,
    document_root: ET.Element,
    rels_root: ET.Element,
    content_types_root: ET.Element,
    members: set[str],
) -> list[str]:
    issues: list[str] = []
    rels = {
        str(rel.get("Id")): rel
        for rel in rels_root.findall(f"{{{PKG_REL_NS}}}Relationship")
        if rel.get("Id")
    }
    content_type_overrides = {
        str(item.get("PartName")): str(item.get("ContentType"))
        for item in content_types_root.findall(f"{{{CONTENT_TYPES_NS}}}Override")
        if item.get("PartName")
    }
    expected = {
        f"{{{WORD_NS}}}headerReference": (
            DOC_REL_TYPE_HEADER,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml",
            "header",
        ),
        f"{{{WORD_NS}}}footerReference": (
            DOC_REL_TYPE_FOOTER,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml",
            "footer",
        ),
    }
    for sect in document_root.findall(".//w:sectPr", NS):
        seen_types: set[tuple[str, str]] = set()
        for ref in list(sect):
            if ref.tag not in expected:
                continue
            expected_rel_type, expected_content_type, label = expected[ref.tag]
            ref_type = str(ref.get(f"{{{WORD_NS}}}type") or "default")
            key = (label, ref_type)
            if key in seen_types:
                issues.append(f"{label}_reference_duplicate_type:{ref_type}")
            seen_types.add(key)

            rel_id = ref.get(f"{{{REL_NS}}}id")
            if not rel_id:
                issues.append(f"{label}_reference_missing_rid:{ref_type}")
                continue
            rel = rels.get(str(rel_id))
            if rel is None:
                issues.append(f"{label}_reference_missing_relationship:{rel_id}")
                continue
            if rel.get("Type") != expected_rel_type:
                issues.append(f"{label}_reference_wrong_relationship_type:{rel_id}")
            if rel.get("TargetMode") == "External":
                issues.append(f"{label}_reference_external_target:{rel_id}")
            target = _resolve_docx_part("word/document.xml", str(rel.get("Target") or ""))
            if target not in members:
                issues.append(f"{label}_reference_missing_target:{target}")
                continue
            part_name = "/" + target
            if content_type_overrides.get(part_name) != expected_content_type:
                issues.append(f"{label}_reference_missing_content_type:{part_name}")
    return issues


def _audit_word_tables(root: ET.Element, *, part_name: str) -> list[str]:
    issues: list[str] = []
    for table_index, table in enumerate(root.iter(f"{{{WORD_NS}}}tbl"), start=1):
        grid_widths = _existing_table_grid_widths(table)
        if len(grid_widths) < 2:
            continue
        table_width = table.find(f"./{{{WORD_NS}}}tblPr/{{{WORD_NS}}}tblW")
        if table_width is None or table_width.get(f"{{{WORD_NS}}}type") != "dxa":
            issues.append(f"table_missing_dxa_width:{part_name}:{table_index}")
        elif _int_value(table_width.get(f"{{{WORD_NS}}}w")) != sum(grid_widths):
            issues.append(f"table_width_grid_mismatch:{part_name}:{table_index}")

        for row_index, row in enumerate(table.findall(f"{{{WORD_NS}}}tr"), start=1):
            cells = row.findall(f"{{{WORD_NS}}}tc")
            if not cells:
                continue
            covered_columns = 0
            row_width = 0
            for cell in cells:
                cell_width = _cell_width_dxa(cell)
                if cell_width <= 0:
                    issues.append(f"table_cell_missing_dxa_width:{part_name}:{table_index}:{row_index}")
                    covered_columns = 0
                    break
                grid_span = max(1, _cell_grid_span(cell))
                covered_columns += grid_span
                row_width += cell_width
            if not covered_columns:
                continue
            if covered_columns != len(grid_widths) or row_width != sum(grid_widths):
                issues.append(f"table_cell_grid_mismatch:{part_name}:{table_index}:{row_index}")
            if row_index >= 2:
                break
    return issues


def _normalize_table_grids_xml(xml_bytes: bytes) -> bytes:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return xml_bytes

    changed = False
    for table in root.iter(f"{{{WORD_NS}}}tbl"):
        widths = _semantic_table_widths(table) or _first_row_cell_widths(table) or _existing_table_grid_widths(table)
        if len(widths) < 2:
            continue

        table_props = _ensure_child(table, "tblPr", index=0)
        _set_table_width(table_props, str(sum(widths)), width_type="dxa")
        _set_table_layout_fixed(table_props)
        _set_table_grid(table, tuple(str(width) for width in widths))
        for row in table.findall(f"{{{WORD_NS}}}tr"):
            _set_row_cell_widths(row, widths)
        changed = True

    if not changed:
        return xml_bytes
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _existing_table_grid_widths(table: ET.Element) -> list[int]:
    widths: list[int] = []
    for column in table.findall(f"./{{{WORD_NS}}}tblGrid/{{{WORD_NS}}}gridCol"):
        width = _int_value(column.get(f"{{{WORD_NS}}}w"))
        if width and width > 0:
            widths.append(width)
    return widths


def _first_row_cell_widths(table: ET.Element) -> list[int]:
    first_row = table.find(f"{{{WORD_NS}}}tr")
    if first_row is None:
        return []

    widths: list[int] = []
    for cell in first_row.findall(f"{{{WORD_NS}}}tc"):
        cell_width = _cell_width_dxa(cell)
        if cell_width <= 0:
            return []
        grid_span = _cell_grid_span(cell)
        if grid_span > 1:
            split_width = max(1, cell_width // grid_span)
            widths.extend([split_width] * grid_span)
        else:
            widths.append(cell_width)
    return widths


def _semantic_table_widths(table: ET.Element) -> list[int]:
    rows = table.findall(f"{{{WORD_NS}}}tr")
    if not rows:
        return []
    first_row_cells = rows[0].findall(f"{{{WORD_NS}}}tc")
    if len(first_row_cells) != 2:
        return []

    text = _normalize_text(_xml_text(table))
    first_cell_text = _normalize_text(_xml_text(first_row_cells[0]))
    if "expérience" in text and len(rows) == 2:
        return list(ABSIS_IDENTITY_COLUMN_DXA)
    if "formation/certification" in text and "langues" in text:
        return list(ABSIS_SUPPORT_COLUMN_DXA)
    if first_cell_text in {
        "data / bi",
        "développement",
        "big data",
        "cloud & architecture",
        "gestion de projet",
        "monitoring & production",
        "api & services",
        "paiements & normes bancaires",
        "outils / techniques",
    }:
        return list(ABSIS_TECHNICAL_COLUMN_DXA)
    return []


def _normalize_word_style_defaults_xml(xml_bytes: bytes, *, font_family: str = "Calibri") -> bytes:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return xml_bytes

    if _has_absis_template_styles(root):
        return xml_bytes

    changed = False
    doc_defaults = _ensure_child(root, "docDefaults", index=0)
    rpr_default = _ensure_child(doc_defaults, "rPrDefault")
    rpr = _ensure_child(rpr_default, "rPr")
    changed = _set_run_fonts(rpr, font_family) or changed

    for style in root.findall("w:style", NS):
        if style.get(f"{{{WORD_NS}}}type") != "paragraph":
            continue
        style_id = style.get(f"{{{WORD_NS}}}styleId")
        if style_id not in {"Normal", "BodyText", "DefaultParagraphFont"}:
            continue
        rpr = _ensure_child(style, "rPr")
        changed = _set_run_fonts(rpr, font_family) or changed

    if not changed:
        return xml_bytes
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _has_absis_template_styles(styles_root: ET.Element) -> bool:
    style_ids = {
        str(style.get(f"{{{WORD_NS}}}styleId") or "")
        for style in styles_root.findall("w:style", NS)
        if style.get(f"{{{WORD_NS}}}styleId")
    }
    return len(style_ids.intersection(ABSIS_SOURCE_STYLE_IDS)) >= 3


def _normalize_word_schema_xml(xml_bytes: bytes) -> bytes:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return xml_bytes

    changed = False
    for paragraph_props in root.iter(f"{{{WORD_NS}}}pPr"):
        changed = _move_direct_run_properties_into_paragraph_run_props(paragraph_props) or changed
        changed = _sort_children_by_ooxml_order(paragraph_props, PARAGRAPH_PROPERTY_ORDER) or changed

    for table_props in root.iter(f"{{{WORD_NS}}}tblPr"):
        changed = _sort_children_by_ooxml_order(table_props, TABLE_PROPERTY_ORDER) or changed

    for cell_props in root.iter(f"{{{WORD_NS}}}tcPr"):
        changed = _sort_children_by_ooxml_order(cell_props, TABLE_CELL_PROPERTY_ORDER) or changed

    for borders in root.iter(f"{{{WORD_NS}}}tcBorders"):
        changed = _sort_children_by_ooxml_order(borders, TABLE_CELL_BORDER_ORDER) or changed

    for margins in root.iter(f"{{{WORD_NS}}}tblCellMar"):
        changed = _sort_children_by_ooxml_order(margins, TABLE_CELL_MARGIN_ORDER) or changed

    if not changed:
        return xml_bytes
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _move_direct_run_properties_into_paragraph_run_props(paragraph_props: ET.Element) -> bool:
    direct_run_props = [
        child
        for child in list(paragraph_props)
        if _local_name(child.tag) in PARAGRAPH_RUN_PROPERTY_TAGS
    ]
    if not direct_run_props:
        return False

    run_props = paragraph_props.find(f"{{{WORD_NS}}}rPr")
    if run_props is None:
        run_props = ET.Element(f"{{{WORD_NS}}}rPr")
        paragraph_props.append(run_props)

    for child in direct_run_props:
        paragraph_props.remove(child)
        run_props.append(child)
    return True


def _sort_children_by_ooxml_order(parent: ET.Element, order: tuple[str, ...]) -> bool:
    children = list(parent)
    if len(children) < 2:
        return False

    order_index = {name: index for index, name in enumerate(order)}
    sorted_children = sorted(
        enumerate(children),
        key=lambda item: (order_index.get(_local_name(item[1].tag), len(order_index)), item[0]),
    )
    reordered = [child for _, child in sorted_children]
    if reordered == children:
        return False
    parent[:] = reordered
    return True


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if "}" in tag else tag


def _normalize_word_document_rendering_xml(
    xml_bytes: bytes,
    *,
    font_family: str = "Calibri",
    prefer_template_styles: bool = False,
) -> bytes:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return xml_bytes

    changed = False
    for run in root.iter(f"{{{WORD_NS}}}r"):
        run_props = run.find(f"{{{WORD_NS}}}rPr")
        if run_props is None:
            run_props = ET.Element(f"{{{WORD_NS}}}rPr")
            run.insert(0, run_props)
            changed = True
        if prefer_template_styles:
            changed = _remove_run_fonts(run_props) or changed
        else:
            changed = _set_run_fonts(run_props, font_family) or changed

    heading_font_family = None if prefer_template_styles else font_family
    changed = (
        _replace_experience_heading_tables_with_paragraphs(root, font_family=heading_font_family)
        or changed
    )

    for table in root.iter(f"{{{WORD_NS}}}tbl"):
        if _looks_like_experience_heading_table(table):
            _normalize_experience_heading_table(table, font_family=heading_font_family)
            changed = True
    if prefer_template_styles:
        changed = _apply_absis_semantic_paragraph_styles(root) or changed
        changed = _insert_section_break_before_first_summary(root) or changed

    if not changed:
        return xml_bytes
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _replace_experience_heading_tables_with_paragraphs(root: ET.Element, *, font_family: str | None) -> bool:
    changed = False
    table_tag = f"{{{WORD_NS}}}tbl"
    for parent in root.iter():
        for index, child in enumerate(list(parent)):
            if child.tag != table_tag or not _looks_like_experience_heading_table(child):
                continue
            paragraph = _experience_heading_table_to_paragraph(child, font_family=font_family)
            paragraph.tail = child.tail
            parent.remove(child)
            parent.insert(index, paragraph)
            changed = True
    return changed


def _experience_heading_table_to_paragraph(table: ET.Element, *, font_family: str | None) -> ET.Element:
    rows = table.findall(f"{{{WORD_NS}}}tr")
    cells = rows[0].findall(f"{{{WORD_NS}}}tc") if rows else []
    company = _xml_text(cells[0]).strip() if len(cells) > 0 else ""
    period = _xml_text(cells[1]).strip() if len(cells) > 1 else ""

    paragraph = ET.Element(f"{{{WORD_NS}}}p")
    paragraph_props = ET.SubElement(paragraph, f"{{{WORD_NS}}}pPr")
    if font_family is None:
        _set_paragraph_style(paragraph_props, "Rle")

    borders = ET.SubElement(paragraph_props, f"{{{WORD_NS}}}pBdr")
    left = ET.SubElement(borders, f"{{{WORD_NS}}}left")
    left.set(f"{{{WORD_NS}}}val", "single")
    left.set(f"{{{WORD_NS}}}sz", "16")
    left.set(f"{{{WORD_NS}}}space", "4")
    left.set(f"{{{WORD_NS}}}color", "004161")

    tabs = ET.SubElement(paragraph_props, f"{{{WORD_NS}}}tabs")
    right_tab = ET.SubElement(tabs, f"{{{WORD_NS}}}tab")
    right_tab.set(f"{{{WORD_NS}}}val", "right")
    right_tab.set(f"{{{WORD_NS}}}pos", "9300")

    spacing = ET.SubElement(paragraph_props, f"{{{WORD_NS}}}spacing")
    spacing.set(f"{{{WORD_NS}}}before", "240")
    spacing.set(f"{{{WORD_NS}}}after", "120")

    _append_heading_run(paragraph, company, font_family=font_family)
    tab_run = ET.SubElement(paragraph, f"{{{WORD_NS}}}r")
    ET.SubElement(tab_run, f"{{{WORD_NS}}}tab")
    _append_heading_run(paragraph, period, font_family=font_family)
    return paragraph


def _append_heading_run(paragraph: ET.Element, text: str, *, font_family: str | None) -> None:
    run = ET.SubElement(paragraph, f"{{{WORD_NS}}}r")
    run_props = ET.SubElement(run, f"{{{WORD_NS}}}rPr")
    if font_family:
        _set_run_fonts(run_props, font_family)
        _set_run_bold(run_props)
        _set_run_color(run_props, HTML_ABSIS_PRIMARY_COLOR)
        _set_run_size(run_props, "22")
    text_node = ET.SubElement(run, f"{{{WORD_NS}}}t")
    text_node.text = text


def _looks_like_experience_heading_table(table: ET.Element) -> bool:
    rows = table.findall(f"{{{WORD_NS}}}tr")
    if len(rows) != 1:
        return False
    cells = rows[0].findall(f"{{{WORD_NS}}}tc")
    if len(cells) != 2:
        return False

    company = _xml_text(cells[0]).strip()
    period = _xml_text(cells[1]).strip()
    if not company or not period:
        return False
    if len(company) > 80 or len(period) > 70:
        return False
    return _looks_like_period_label(period)


def _looks_like_period_label(text: str) -> bool:
    normalized = _normalize_text(text)
    if not normalized:
        return False
    month_tokens = (
        "janvier",
        "fevrier",
        "février",
        "mars",
        "avril",
        "mai",
        "juin",
        "juillet",
        "aout",
        "août",
        "septembre",
        "octobre",
        "novembre",
        "decembre",
        "décembre",
    )
    if "poste actuel" in normalized:
        return True
    if re.fullmatch(r"(?:19|20)\d{2}", normalized):
        return True
    if re.search(
        r"\b(?:19|20)\d{2}\s*(?:-|–|—|a|à)\s*(?:(?:19|20)\d{2}|aujourd'hui|aujourd’hui|present|présent)\b",
        normalized,
    ):
        return True
    if any(month in normalized for month in month_tokens) and re.search(r"\b20\d{2}\b", normalized):
        return True
    return bool(re.search(r"\b(?:0[1-9]|1[0-2])\s*/\s*20\d{2}\b", normalized))


def _normalize_experience_heading_table(table: ET.Element, *, font_family: str | None) -> None:
    table_props = _ensure_child(table, "tblPr", index=0)
    _set_table_width(table_props, "9763", width_type="dxa")
    _set_table_justification(table_props, "left")
    _set_table_cell_margins(table_props)
    _set_table_borders(table_props)
    _set_table_grid(table, ("6000", "3763"))

    rows = table.findall(f"{{{WORD_NS}}}tr")
    cells = rows[0].findall(f"{{{WORD_NS}}}tc") if rows else []
    for index, cell in enumerate(cells):
        cell_props = _ensure_child(cell, "tcPr", index=0)
        if index < 2:
            _set_cell_width(cell_props, ("6000", "3763")[index])
        _set_cell_borders(cell_props)
        if index == 0:
            _set_cell_left_accent(cell_props, color="004161")
        _set_cell_margins(cell_props)
        for paragraph in cell.findall(f".//{{{WORD_NS}}}p"):
            paragraph_props = _ensure_child(paragraph, "pPr", index=0)
            if font_family is None:
                _set_paragraph_style(paragraph_props, "Rle")
            _set_paragraph_alignment(paragraph_props, "right" if index == 1 else "left")
            for run in paragraph.findall(f"{{{WORD_NS}}}r"):
                run_props = run.find(f"{{{WORD_NS}}}rPr")
                if run_props is None:
                    run_props = ET.Element(f"{{{WORD_NS}}}rPr")
                    run.insert(0, run_props)
                if font_family:
                    _set_run_fonts(run_props, font_family)
                    _set_run_bold(run_props)
                    _set_run_color(run_props, HTML_ABSIS_PRIMARY_COLOR)
                    _set_run_size(run_props, "22")
                else:
                    _remove_run_template_overrides(run_props, remove_emphasis=True)


def _xml_text(node: ET.Element) -> str:
    return "".join(text.text or "" for text in node.iter(f"{{{WORD_NS}}}t"))


def _ensure_child(parent: ET.Element, local_name: str, *, index: int | None = None) -> ET.Element:
    tag = f"{{{WORD_NS}}}{local_name}"
    child = parent.find(tag)
    if child is not None:
        return child
    child = ET.Element(tag)
    if index is None:
        parent.append(child)
    else:
        parent.insert(index, child)
    return child


def _set_run_fonts(run_props: ET.Element, font_family: str) -> bool:
    fonts = _ensure_child(run_props, "rFonts", index=0)
    changed = False
    for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
        key = f"{{{WORD_NS}}}{attr}"
        if fonts.get(key) != font_family:
            fonts.set(key, font_family)
            changed = True
    return changed


def _remove_run_fonts(run_props: ET.Element) -> bool:
    fonts = run_props.find(f"{{{WORD_NS}}}rFonts")
    if fonts is None:
        return False
    run_props.remove(fonts)
    return True


def _remove_run_template_overrides(run_props: ET.Element, *, remove_emphasis: bool = False) -> bool:
    changed = _remove_run_fonts(run_props)
    for local_name in ("color", "sz", "szCs"):
        node = run_props.find(f"{{{WORD_NS}}}{local_name}")
        if node is not None:
            run_props.remove(node)
            changed = True
    if remove_emphasis:
        for local_name in ("b", "i", "u"):
            node = run_props.find(f"{{{WORD_NS}}}{local_name}")
            if node is not None:
                run_props.remove(node)
                changed = True
    return changed


def _set_paragraph_style(paragraph_props: ET.Element, style_id: str) -> bool:
    style = paragraph_props.find(f"{{{WORD_NS}}}pStyle")
    if style is None:
        style = ET.Element(f"{{{WORD_NS}}}pStyle")
        paragraph_props.insert(0, style)
    current = style.get(f"{{{WORD_NS}}}val")
    if current == style_id:
        return False
    style.set(f"{{{WORD_NS}}}val", style_id)
    return True


def _apply_absis_semantic_paragraph_styles(root: ET.Element) -> bool:
    changed = False
    for paragraph in root.iter(f"{{{WORD_NS}}}p"):
        text = _normalize_text(_xml_text(paragraph))
        if not text:
            continue
        style_id = _absis_style_for_paragraph(paragraph, text)
        if not style_id:
            continue
        paragraph_props = _ensure_child(paragraph, "pPr", index=0)
        changed = _set_paragraph_style(paragraph_props, style_id) or changed
        if text == "synthèse":
            changed = _set_paragraph_page_break_before(paragraph_props) or changed
        if style_id == "DtailCaractristique":
            changed = _remove_literal_list_marker(paragraph) or changed
        remove_emphasis = style_id in {"Titrestabeau", "Rle", "Mission", "Environnement"}
        for run_props in paragraph.findall(".//w:rPr", NS):
            changed = _remove_run_template_overrides(run_props, remove_emphasis=remove_emphasis) or changed
    return changed


def _absis_style_for_paragraph(paragraph: ET.Element, normalized_text: str) -> str:
    if paragraph.find("./w:pPr/w:pBdr/w:left", NS) is not None:
        return "Rle"

    headings = {
        "synthèse",
        "competences",
        "compétences",
        "competences cles",
        "compétences clés",
        "competences metiers",
        "compétences métiers",
        "competences techniques",
        "compétences techniques",
        "formation/certification",
        "certifications",
        "langues",
        "loisirs",
        "engagements",
    }
    if normalized_text in headings:
        return "Titrestabeau"
    if normalized_text.startswith("projet/contexte") or normalized_text.startswith("contexte"):
        return "ProjetNormal"
    if normalized_text in {"missions", "missions :"}:
        return "Mission"
    if normalized_text.startswith("environnement"):
        return "Environnement"
    if normalized_text.startswith("•") or normalized_text.startswith("- "):
        return "DtailCaractristique"
    return ""


def _set_paragraph_page_break_before(paragraph_props: ET.Element) -> bool:
    if paragraph_props.find(f"{{{WORD_NS}}}pageBreakBefore") is not None:
        return False
    paragraph_props.append(ET.Element(f"{{{WORD_NS}}}pageBreakBefore"))
    return True


def _remove_literal_list_marker(paragraph: ET.Element) -> bool:
    for text_node in paragraph.iter(f"{{{WORD_NS}}}t"):
        text = text_node.text or ""
        stripped = re.sub(r"^\s*(?:•|-)\s*", "", text, count=1)
        if stripped != text:
            text_node.text = stripped
            return True
    return False


def _insert_section_break_before_first_summary(root: ET.Element) -> bool:
    body = root.find(".//w:body", NS)
    if body is None:
        return False
    terminal_section = body.find("w:sectPr", NS)
    children = list(body)
    for index, child in enumerate(children):
        if child.tag != f"{{{WORD_NS}}}p" or _normalize_text(_xml_text(child)) != "synthèse":
            continue
        if index > 0 and _paragraph_is_empty_page_break_before(children[index - 1]):
            body.remove(children[index - 1])
            index -= 1
        if index > 0 and _paragraph_contains_section_break(children[index - 1]):
            return False
        section_break = ET.Element(f"{{{WORD_NS}}}p")
        paragraph_props = ET.SubElement(section_break, f"{{{WORD_NS}}}pPr")
        section_props = deepcopy(terminal_section) if terminal_section is not None else ET.Element(f"{{{WORD_NS}}}sectPr")
        section_type = section_props.find("w:type", NS)
        if section_type is None:
            section_type = ET.Element(f"{{{WORD_NS}}}type")
            section_props.insert(_section_type_insert_index(section_props), section_type)
        section_type.set(f"{{{WORD_NS}}}val", "nextPage")
        paragraph_props.append(section_props)
        _remove_paragraph_page_break_before(child)
        body.insert(index, section_break)
        return True
    return False


def _paragraph_is_empty_page_break_before(paragraph: ET.Element) -> bool:
    if paragraph.tag != f"{{{WORD_NS}}}p" or _normalize_text(_xml_text(paragraph)):
        return False
    paragraph_props = paragraph.find("w:pPr", NS)
    return paragraph_props is not None and paragraph_props.find("w:pageBreakBefore", NS) is not None


def _remove_paragraph_page_break_before(paragraph: ET.Element) -> bool:
    paragraph_props = paragraph.find("w:pPr", NS)
    page_break = paragraph_props.find("w:pageBreakBefore", NS) if paragraph_props is not None else None
    if paragraph_props is None or page_break is None:
        return False
    paragraph_props.remove(page_break)
    return True


def _section_type_insert_index(section_props: ET.Element) -> int:
    index = 0
    for child_index, child in enumerate(list(section_props)):
        if child.tag in {f"{{{WORD_NS}}}headerReference", f"{{{WORD_NS}}}footerReference"}:
            index = child_index + 1
    return index


def _paragraph_contains_section_break(paragraph: ET.Element) -> bool:
    return paragraph.find(".//w:sectPr", NS) is not None


def _set_run_bold(run_props: ET.Element) -> None:
    bold = _ensure_child(run_props, "b")
    bold.set(f"{{{WORD_NS}}}val", "1")


def _set_run_color(run_props: ET.Element, color: str) -> None:
    color_node = _ensure_child(run_props, "color")
    color_node.set(f"{{{WORD_NS}}}val", color)


def _set_run_size(run_props: ET.Element, size_half_points: str) -> None:
    size = _ensure_child(run_props, "sz")
    size.set(f"{{{WORD_NS}}}val", size_half_points)
    complex_size = _ensure_child(run_props, "szCs")
    complex_size.set(f"{{{WORD_NS}}}val", size_half_points)


def _set_paragraph_alignment(paragraph_props: ET.Element, value: str) -> None:
    alignment = _ensure_child(paragraph_props, "jc")
    alignment.set(f"{{{WORD_NS}}}val", value)


def _set_table_width(table_props: ET.Element, width: str, *, width_type: str = "auto") -> None:
    table_width = _ensure_child(table_props, "tblW", index=0)
    table_width.set(f"{{{WORD_NS}}}w", width)
    table_width.set(f"{{{WORD_NS}}}type", width_type)


def _set_table_layout_fixed(table_props: ET.Element) -> None:
    layout = _ensure_child(table_props, "tblLayout")
    layout.set(f"{{{WORD_NS}}}type", "fixed")


def _set_table_grid(table: ET.Element, widths: tuple[str, ...]) -> None:
    grid = table.find(f"{{{WORD_NS}}}tblGrid")
    if grid is None:
        grid = ET.Element(f"{{{WORD_NS}}}tblGrid")
        table_props = table.find(f"{{{WORD_NS}}}tblPr")
        insert_at = list(table).index(table_props) + 1 if table_props is not None else 0
        table.insert(insert_at, grid)
    grid.clear()
    for width in widths:
        ET.SubElement(grid, f"{{{WORD_NS}}}gridCol", {f"{{{WORD_NS}}}w": width})


def _set_cell_width(cell_props: ET.Element, width: str) -> None:
    cell_width = _ensure_child(cell_props, "tcW", index=0)
    cell_width.set(f"{{{WORD_NS}}}w", width)
    cell_width.set(f"{{{WORD_NS}}}type", "dxa")


def _set_row_cell_widths(row: ET.Element, grid_widths: list[int]) -> None:
    cells = row.findall(f"{{{WORD_NS}}}tc")
    if not cells or not grid_widths:
        return
    if len(cells) == 1 and len(grid_widths) > 1 and _cell_grid_span(cells[0]) == 1:
        cell_props = _ensure_child(cells[0], "tcPr", index=0)
        _set_cell_grid_span(cell_props, len(grid_widths))
        _set_cell_width(cell_props, str(sum(grid_widths)))
        return

    grid_index = 0
    for cell_index, cell in enumerate(cells):
        span = max(1, _cell_grid_span(cell))
        width = sum(grid_widths[grid_index : grid_index + span])
        if width <= 0:
            remaining_cells = len(cells) - cell_index
            remaining_width = sum(grid_widths[grid_index:])
            width = max(1, remaining_width // max(1, remaining_cells))
        cell_props = _ensure_child(cell, "tcPr", index=0)
        _set_cell_width(cell_props, str(width))
        grid_index += span


def _set_cell_grid_span(cell_props: ET.Element, span: int) -> None:
    grid_span = _ensure_child(cell_props, "gridSpan")
    grid_span.set(f"{{{WORD_NS}}}val", str(span))


def _set_table_justification(table_props: ET.Element, value: str) -> None:
    justification = _ensure_child(table_props, "jc")
    justification.set(f"{{{WORD_NS}}}val", value)


def _set_table_cell_margins(table_props: ET.Element) -> None:
    margins = _ensure_child(table_props, "tblCellMar")
    for side in ("top", "left", "bottom", "right"):
        margin = _ensure_child(margins, side)
        margin.set(f"{{{WORD_NS}}}w", "35" if side in {"left", "right"} else "0")
        margin.set(f"{{{WORD_NS}}}type", "dxa")


def _set_table_borders(
    table_props: ET.Element,
    *,
    bottom_color: str | None = None,
    left_color: str | None = None,
) -> None:
    borders = _ensure_child(table_props, "tblBorders")
    for side in ("top", "right", "insideH", "insideV"):
        edge = _ensure_child(borders, side)
        edge.set(f"{{{WORD_NS}}}val", "nil")
    left = _ensure_child(borders, "left")
    if left_color:
        left.set(f"{{{WORD_NS}}}val", "single")
        left.set(f"{{{WORD_NS}}}sz", "16")
        left.set(f"{{{WORD_NS}}}space", "0")
        left.set(f"{{{WORD_NS}}}color", left_color)
    else:
        left.set(f"{{{WORD_NS}}}val", "nil")
    bottom = _ensure_child(borders, "bottom")
    if bottom_color:
        bottom.set(f"{{{WORD_NS}}}val", "single")
        bottom.set(f"{{{WORD_NS}}}sz", "6")
        bottom.set(f"{{{WORD_NS}}}space", "0")
        bottom.set(f"{{{WORD_NS}}}color", bottom_color)
    else:
        bottom.set(f"{{{WORD_NS}}}val", "nil")


def _set_cell_borders(cell_props: ET.Element) -> None:
    borders = _ensure_child(cell_props, "tcBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        edge = _ensure_child(borders, side)
        edge.set(f"{{{WORD_NS}}}val", "nil")


def _set_cell_left_accent(cell_props: ET.Element, *, color: str) -> None:
    borders = _ensure_child(cell_props, "tcBorders")
    left = _ensure_child(borders, "left")
    left.set(f"{{{WORD_NS}}}val", "single")
    left.set(f"{{{WORD_NS}}}sz", "16")
    left.set(f"{{{WORD_NS}}}space", "0")
    left.set(f"{{{WORD_NS}}}color", color)


def _set_cell_margins(cell_props: ET.Element) -> None:
    margins = _ensure_child(cell_props, "tcMar")
    for side in ("top", "left", "bottom", "right"):
        margin = _ensure_child(margins, side)
        margin.set(f"{{{WORD_NS}}}w", "90" if side == "left" else "35" if side == "right" else "0")
        margin.set(f"{{{WORD_NS}}}type", "dxa")


def _cell_width_dxa(cell: ET.Element) -> int:
    width = cell.find(f"./{{{WORD_NS}}}tcPr/{{{WORD_NS}}}tcW")
    if width is None or width.get(f"{{{WORD_NS}}}type") != "dxa":
        return 0
    return _int_value(width.get(f"{{{WORD_NS}}}w"))


def _cell_grid_span(cell: ET.Element) -> int:
    span = cell.find(f"./{{{WORD_NS}}}tcPr/{{{WORD_NS}}}gridSpan")
    if span is None:
        return 1
    value = _int_value(span.get(f"{{{WORD_NS}}}val"))
    return value if value > 1 else 1


def _apply_template_shell_to_docx(docx_bytes: bytes, template_bytes: bytes) -> bytes:
    if not template_bytes:
        return docx_bytes

    with ZipFile(io.BytesIO(template_bytes)) as template_archive:
        template_members = set(template_archive.namelist())
        if "word/document.xml" not in template_members or "word/_rels/document.xml.rels" not in template_members:
            return docx_bytes

        template_root = ET.fromstring(template_archive.read("word/document.xml"))
        template_sect = template_root.find(".//w:sectPr", NS)
        if template_sect is None:
            return docx_bytes

        template_doc_rels = ET.fromstring(template_archive.read("word/_rels/document.xml.rels"))
        template_rels_by_id = {
            str(rel.get("Id")): rel
            for rel in template_doc_rels.findall(f"{{{PKG_REL_NS}}}Relationship")
        }
        shell_refs: list[dict[str, str]] = []
        copied_parts: set[str] = set()
        for ref in list(template_sect):
            if ref.tag not in {f"{{{WORD_NS}}}headerReference", f"{{{WORD_NS}}}footerReference"}:
                continue
            rel_id = ref.get(f"{{{REL_NS}}}id")
            rel = template_rels_by_id.get(str(rel_id))
            if rel is None:
                continue
            rel_type = str(rel.get("Type") or "")
            if rel_type not in {DOC_REL_TYPE_HEADER, DOC_REL_TYPE_FOOTER}:
                continue
            target = str(rel.get("Target") or "")
            part = _resolve_docx_part("word/document.xml", target)
            if part not in template_members:
                continue
            shell_refs.append(
                {
                    "tag": ref.tag,
                    "type": str(ref.get(f"{{{WORD_NS}}}type") or "default"),
                    "part": part,
                    "rel_type": rel_type,
                }
            )
            copied_parts.add(part)
            copied_parts.update(_shell_related_parts(template_archive, part))

        if not shell_refs:
            return docx_bytes

        for part in TEMPLATE_SHELL_CORE_PARTS:
            if part in template_members:
                copied_parts.add(part)
                copied_parts.update(_shell_related_parts(template_archive, part))

        replacements: dict[str, bytes] = {}
        for part in copied_parts:
            replacements[part] = template_archive.read(part)

        template_content_types = template_archive.read("[Content_Types].xml") if "[Content_Types].xml" in template_members else b""
        template_pg_sz = template_sect.find("w:pgSz", NS)
        template_pg_mar = template_sect.find("w:pgMar", NS)
        template_title_pg = template_sect.find("w:titlePg", NS)

    with ZipFile(io.BytesIO(docx_bytes)) as source_archive:
        source_members = set(source_archive.namelist())
        document_xml = source_archive.read("word/document.xml")
        document_rels_xml = (
            source_archive.read("word/_rels/document.xml.rels")
            if "word/_rels/document.xml.rels" in source_members
            else b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>'
        )
        content_types_xml = (
            source_archive.read("[Content_Types].xml")
            if "[Content_Types].xml" in source_members
            else b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
        )

        document_xml, document_rels_xml = _attach_template_shell_references(
            document_xml=document_xml,
            document_rels_xml=document_rels_xml,
            shell_refs=shell_refs,
            template_pg_sz=template_pg_sz,
            template_pg_mar=template_pg_mar,
            template_title_pg=template_title_pg,
        )
        replacements["word/document.xml"] = document_xml
        replacements["word/_rels/document.xml.rels"] = document_rels_xml
        replacements["[Content_Types].xml"] = _merge_shell_content_types(
            content_types_xml=content_types_xml,
            template_content_types_xml=template_content_types,
            copied_parts=copied_parts,
        )

        output = io.BytesIO()
        with ZipFile(output, "w") as target_archive:
            for info in source_archive.infolist():
                if info.filename in replacements:
                    target_archive.writestr(info, replacements.pop(info.filename))
                else:
                    target_archive.writestr(info, source_archive.read(info.filename))
            for part, payload in replacements.items():
                target_archive.writestr(part, payload)
    return output.getvalue()


def _attach_template_shell_references(
    *,
    document_xml: bytes,
    document_rels_xml: bytes,
    shell_refs: list[dict[str, str]],
    template_pg_sz: ET.Element | None,
    template_pg_mar: ET.Element | None,
    template_title_pg: ET.Element | None,
) -> tuple[bytes, bytes]:
    document_root = ET.fromstring(document_xml)
    sect = document_root.find(".//w:sectPr", NS)
    if sect is None:
        body = document_root.find(f".//{{{WORD_NS}}}body")
        if body is None:
            return document_xml, document_rels_xml
        sect = ET.SubElement(body, f"{{{WORD_NS}}}sectPr")

    rels_root = ET.fromstring(document_rels_xml)
    for rel in list(rels_root.findall(f"{{{PKG_REL_NS}}}Relationship")):
        if rel.get("Type") in {DOC_REL_TYPE_HEADER, DOC_REL_TYPE_FOOTER}:
            rels_root.remove(rel)

    existing_ids = {
        str(rel.get("Id"))
        for rel in rels_root.findall(f"{{{PKG_REL_NS}}}Relationship")
        if rel.get("Id")
    }
    rel_id_map: dict[tuple[str, str], str] = {}
    for index, shell_ref in enumerate(shell_refs, start=1):
        rel_id = _unique_relationship_id(existing_ids, f"rIdBrainHtmlShell{index}")
        existing_ids.add(rel_id)
        rel_id_map[(shell_ref["tag"], shell_ref["part"])] = rel_id
        ET.SubElement(
            rels_root,
            f"{{{PKG_REL_NS}}}Relationship",
            {
                "Id": rel_id,
                "Type": shell_ref["rel_type"],
                "Target": _document_relationship_target(shell_ref["part"]),
            },
        )

    for ref in list(sect):
        if ref.tag in {f"{{{WORD_NS}}}headerReference", f"{{{WORD_NS}}}footerReference"}:
            sect.remove(ref)
    for title_pg in list(sect.findall("w:titlePg", NS)):
        sect.remove(title_pg)
    if template_title_pg is not None:
        sect.insert(0, deepcopy(template_title_pg))

    for index, shell_ref in enumerate(shell_refs):
        ref = ET.Element(
            shell_ref["tag"],
            {
                f"{{{WORD_NS}}}type": shell_ref["type"],
                f"{{{REL_NS}}}id": rel_id_map[(shell_ref["tag"], shell_ref["part"])],
            },
        )
        sect.insert(index, ref)

    if template_pg_sz is not None:
        _replace_or_insert_section_property(sect, "pgSz", template_pg_sz, before_local_name="pgMar")
    if template_pg_mar is not None:
        _replace_or_insert_section_property(sect, "pgMar", template_pg_mar)

    body = document_root.find(f".//{{{WORD_NS}}}body")
    if body is not None and sect in list(body) and list(body)[-1] is not sect:
        body.remove(sect)
        body.append(sect)

    return (
        ET.tostring(document_root, encoding="utf-8", xml_declaration=True),
        _serialize_xml(rels_root, default_namespace=PKG_REL_NS),
    )


def _replace_or_insert_section_property(
    sect: ET.Element,
    local_name: str,
    replacement: ET.Element,
    *,
    before_local_name: str | None = None,
) -> None:
    tag = f"{{{WORD_NS}}}{local_name}"
    current = sect.find(tag)
    replacement_copy = deepcopy(replacement)
    if current is not None:
        index = list(sect).index(current)
        sect.remove(current)
        sect.insert(index, replacement_copy)
        return

    if before_local_name:
        before = sect.find(f"{{{WORD_NS}}}{before_local_name}")
        if before is not None:
            sect.insert(list(sect).index(before), replacement_copy)
            return
    sect.append(replacement_copy)


def _merge_shell_content_types(
    *,
    content_types_xml: bytes,
    template_content_types_xml: bytes,
    copied_parts: set[str],
) -> bytes:
    root = ET.fromstring(content_types_xml)
    existing_overrides = {
        str(item.get("PartName"))
        for item in root.findall(f"{{{CONTENT_TYPES_NS}}}Override")
        if item.get("PartName")
    }
    existing_defaults = {
        str(item.get("Extension"))
        for item in root.findall(f"{{{CONTENT_TYPES_NS}}}Default")
        if item.get("Extension")
    }
    template_overrides: dict[str, ET.Element] = {}
    template_defaults: dict[str, ET.Element] = {}
    if template_content_types_xml:
        template_root = ET.fromstring(template_content_types_xml)
        template_overrides = {
            str(item.get("PartName")): item
            for item in template_root.findall(f"{{{CONTENT_TYPES_NS}}}Override")
            if item.get("PartName")
        }
        template_defaults = {
            str(item.get("Extension")): item
            for item in template_root.findall(f"{{{CONTENT_TYPES_NS}}}Default")
            if item.get("Extension")
        }

    for part in sorted(copied_parts):
        part_name = "/" + part
        if part_name not in existing_overrides:
            override = template_overrides.get(part_name) or _default_shell_override(part_name)
            if override is not None:
                root.append(deepcopy(override))
                existing_overrides.add(part_name)
                continue
        extension = part.rsplit(".", 1)[-1] if "." in part else ""
        if extension and extension not in existing_defaults:
            default = template_defaults.get(extension)
            if default is not None:
                root.append(deepcopy(default))
                existing_defaults.add(extension)
    return _serialize_xml(root, default_namespace=CONTENT_TYPES_NS)


def _serialize_xml(root: ET.Element, *, default_namespace: str | None = None) -> bytes:
    payload = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if not default_namespace:
        return payload

    text = payload.decode("utf-8")
    match = re.search(rf'xmlns:(?P<prefix>ns\d+)="{re.escape(default_namespace)}"', text)
    if not match:
        return payload
    prefix = match.group("prefix")
    text = text.replace(f'xmlns:{prefix}="{default_namespace}"', f'xmlns="{default_namespace}"', 1)
    text = text.replace(f"<{prefix}:", "<")
    text = text.replace(f"</{prefix}:", "</")
    return text.encode("utf-8")


def _default_shell_override(part_name: str) -> ET.Element | None:
    if re.fullmatch(r"/word/header\d+\.xml", part_name):
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"
    elif re.fullmatch(r"/word/footer\d+\.xml", part_name):
        content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"
    else:
        return None
    return ET.Element(
        f"{{{CONTENT_TYPES_NS}}}Override",
        {"PartName": part_name, "ContentType": content_type},
    )


def _shell_related_parts(archive: ZipFile, part: str) -> set[str]:
    members = set(archive.namelist())
    related_parts: set[str] = set()
    rels_path = _part_relationships_path(part)
    if rels_path not in members:
        return related_parts
    related_parts.add(rels_path)
    rels_root = ET.fromstring(archive.read(rels_path))
    for rel in rels_root.findall(f"{{{PKG_REL_NS}}}Relationship"):
        if rel.get("TargetMode") == "External":
            continue
        target = str(rel.get("Target") or "")
        if not target:
            continue
        related = _resolve_docx_part(part, target)
        if related in members:
            related_parts.add(related)
    return related_parts


def _part_relationships_path(part: str) -> str:
    directory, filename = posixpath.split(part)
    return posixpath.join(directory, "_rels", f"{filename}.rels")


def _resolve_docx_part(base_part: str, target: str) -> str:
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join(posixpath.dirname(base_part), target))


def _document_relationship_target(part: str) -> str:
    return part.removeprefix("word/")


def _unique_relationship_id(existing_ids: set[str], preferred: str) -> str:
    if preferred not in existing_ids:
        return preferred
    index = 1
    while f"{preferred}_{index}" in existing_ids:
        index += 1
    return f"{preferred}_{index}"


def _augment_html_context_from_render_context(
    *,
    canonical_context: dict[str, Any],
    generation_render_context: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    augmented_context = deepcopy(canonical_context)
    summary = {
        "version": HTML_CONTEXT_AUGMENTATION_VERSION,
        "enabled": True,
        "source": "generation_payload.render_context",
        "experiences_seen": 0,
        "experiences_augmented": 0,
        "tasks_appended": 0,
        "fields_applied": 0,
    }
    experiences = augmented_context.get("experiences")
    if not isinstance(experiences, list):
        return augmented_context, summary

    for index, experience in enumerate(experiences, start=1):
        if not isinstance(experience, dict):
            continue
        summary["experiences_seen"] += 1
        existing_texts = _normalized_experience_texts(experience)
        tasks = _coerce_tasks(experience)
        added_to_experience = 0

        field_mappings = (
            ("context", ("contexte",)),
            ("summary", ("contexte",)),
            ("environment", ("env_tech", "environnement", "environment")),
            ("role", ("role",)),
            ("position", ("poste",)),
            ("company", ("entreprise",)),
            ("company_full", ("entreprise_full", "entreprise")),
            ("period", ("periode",)),
            ("period_full", ("periode_full", "periode")),
        )
        for target_field, source_fields in field_mappings:
            if target_field == "environment":
                value = ", ".join(
                    _render_context_values(
                        generation_render_context,
                        experience_index=index,
                        fields=source_fields,
                    )
                )
            else:
                value = _render_context_first(
                    generation_render_context,
                    experience_index=index,
                    fields=source_fields,
                )
            if not value:
                continue
            current_value = _clean_text(experience.get(target_field))
            if current_value:
                if target_field not in {"context", "summary"} or len(current_value) >= len(value):
                    continue
            experience[target_field] = value
            existing_texts.add(_normalize_text(value))
            added_to_experience += 1
            summary["fields_applied"] += 1

        for value in _render_context_values(
            generation_render_context,
            experience_index=index,
            fields=("tache", "point_cle", "axe", "mission"),
        ):
            normalized = _normalize_task_text(value)
            if normalized and normalized not in existing_texts:
                tasks.append(value)
                existing_texts.add(normalized)
                added_to_experience += 1
                summary["tasks_appended"] += 1

        if added_to_experience:
            summary["experiences_augmented"] += 1

    return augmented_context, summary


def _resolve_source_cv_docx(
    *,
    canonical_context: dict[str, Any],
    project: dict[str, Any],
) -> SourceCvDocxResolution:
    identity = _dict(canonical_context.get("identity"))
    source_filename = str(identity.get("source_filename") or "").strip()
    project_id = str(project.get("id") or _dict(canonical_context.get("project")).get("id") or "").strip()
    if not source_filename:
        return SourceCvDocxResolution(docx=None, reason="source_filename_missing")
    if not project_id:
        return SourceCvDocxResolution(docx=None, reason="source_project_id_missing")

    try:
        metadata = CVService.get_cv_metadata(project_id, source_filename)
    except Exception as exc:
        return SourceCvDocxResolution(
            docx=None,
            reason="source_metadata_lookup_failed",
            error=str(exc),
        )
    if not metadata or not metadata.get("file_path"):
        return SourceCvDocxResolution(docx=None, reason="source_file_path_missing")

    storage_path = str(metadata["file_path"])
    if Path(storage_path).suffix.casefold() != ".docx":
        return SourceCvDocxResolution(docx=None, reason="source_not_docx")

    try:
        payload = FileStorage.load_bytes(storage_path)
    except Exception as exc:
        return SourceCvDocxResolution(
            docx=None,
            reason="source_load_failed",
            error=str(exc),
        )
    if not payload:
        return SourceCvDocxResolution(docx=None, reason="source_empty")

    return SourceCvDocxResolution(
        docx=SourceCvDocx(
            storage_path=storage_path,
            filename=source_filename,
            content_hash=sha256(payload).hexdigest(),
            bytes=payload,
        ),
        reason="source_docx_resolved",
    )


def _resolve_source_cv_text(
    *,
    canonical_context: dict[str, Any],
    project: dict[str, Any],
) -> SourceCvTextResolution:
    identity = _dict(canonical_context.get("identity"))
    source_filename = str(identity.get("source_filename") or "").strip()
    project_id = str(project.get("id") or _dict(canonical_context.get("project")).get("id") or "").strip()
    if not source_filename:
        return SourceCvTextResolution(text="", storage_path=None, reason="source_filename_missing")
    if not project_id:
        return SourceCvTextResolution(text="", storage_path=None, reason="source_project_id_missing")

    try:
        metadata = CVService.get_cv_metadata(project_id, source_filename)
    except Exception as exc:
        return SourceCvTextResolution(text="", storage_path=None, reason="source_metadata_lookup_failed", error=str(exc))
    if not metadata or not metadata.get("file_path"):
        return SourceCvTextResolution(text="", storage_path=None, reason="source_file_path_missing")

    storage_path = str(metadata["file_path"])
    try:
        payload = FileStorage.load_bytes(storage_path)
    except Exception as exc:
        return SourceCvTextResolution(text="", storage_path=storage_path, reason="source_load_failed", error=str(exc))
    if not payload:
        return SourceCvTextResolution(text="", storage_path=storage_path, reason="source_empty")

    try:
        suffix = Path(storage_path).suffix.casefold()
        if suffix == ".docx":
            text = _source_docx_text(payload)
        else:
            with tempfile.NamedTemporaryFile(suffix=suffix or ".tmp", delete=True) as handle:
                handle.write(payload)
                handle.flush()
                text = extract_text_from_file(handle.name)
    except Exception as exc:
        return SourceCvTextResolution(
            text="",
            storage_path=storage_path,
            reason="source_text_extraction_failed",
            error=str(exc),
        )
    return SourceCvTextResolution(text=text, storage_path=storage_path, reason="source_text_resolved")


def _source_detection_result(
    *,
    eligible: bool,
    reasons: list[str],
    features: dict[str, Any],
) -> dict[str, Any]:
    return {
        "version": HTML_SOURCE_FAITHFUL_VERSION,
        "eligible": eligible,
        "reasons": reasons,
        "features": features,
    }


def _detect_absis_source_docx(docx_bytes: bytes) -> dict[str, Any]:
    try:
        with ZipFile(io.BytesIO(docx_bytes)) as archive:
            members = set(archive.namelist())
            if "word/document.xml" not in members:
                return _source_detection_result(
                    eligible=False,
                    reasons=["missing_word_document_xml"],
                    features={},
                )

            document_root = ET.fromstring(archive.read("word/document.xml"))
            style_ids: set[str] = set()
            if "word/styles.xml" in members:
                styles_root = ET.fromstring(archive.read("word/styles.xml"))
                style_ids = {
                    str(style.get(f"{{{WORD_NS}}}styleId") or "")
                    for style in styles_root.iter(f"{{{WORD_NS}}}style")
                    if style.get(f"{{{WORD_NS}}}styleId")
                }

            header_parts = sorted(name for name in members if re.fullmatch(r"word/header\d+\.xml", name))
            footer_parts = sorted(name for name in members if re.fullmatch(r"word/footer\d+\.xml", name))
            media_parts = sorted(name for name in members if name.startswith("word/media/"))
            critical_styles = sorted(style_ids.intersection(ABSIS_SOURCE_STYLE_IDS))
            rich_body_count = (
                _count_ooxml_local_name(document_root, "drawing")
                + _count_ooxml_local_name(document_root, "pict")
                + _count_ooxml_local_name(document_root, "anchor")
                + _count_ooxml_local_name(document_root, "txbxContent")
            )
            features: dict[str, Any] = {
                "paragraph_count": _count_text_paragraphs(document_root),
                "table_count": _count_ooxml_local_name(document_root, "tbl"),
                "drawing_count": _count_ooxml_local_name(document_root, "drawing"),
                "pict_count": _count_ooxml_local_name(document_root, "pict"),
                "anchor_count": _count_ooxml_local_name(document_root, "anchor"),
                "textbox_count": _count_ooxml_local_name(document_root, "txbxContent"),
                "numPr_count": _count_ooxml_local_name(document_root, "numPr"),
                "gridSpan_count": _count_ooxml_local_name(document_root, "gridSpan"),
                "vMerge_count": _count_ooxml_local_name(document_root, "vMerge"),
                "header_parts_count": len(header_parts),
                "footer_parts_count": len(footer_parts),
                "media_parts_count": len(media_parts),
                "critical_styles": critical_styles,
            }
            checks = {
                "has_absis_styles": len(critical_styles) >= 3,
                "has_absis_page_shell": bool(header_parts) and bool(footer_parts),
                "has_structured_tables": features["table_count"] >= 3,
                "has_substantial_content": features["paragraph_count"] >= 60,
                "has_rich_body_layout": rich_body_count > 0
                or features["gridSpan_count"] >= 3
                or features["vMerge_count"] >= 3,
            }
            features["checks"] = checks
            reasons = [name for name, passed in checks.items() if not passed]
            return _source_detection_result(
                eligible=not reasons,
                reasons=reasons,
                features=features,
            )
    except Exception as exc:
        return _source_detection_result(
            eligible=False,
            reasons=[f"docx_inspection_failed:{exc}"],
            features={},
        )


def _count_ooxml_local_name(root: ET.Element, local_name: str) -> int:
    return sum(1 for element in root.iter() if element.tag.rsplit("}", 1)[-1] == local_name)


def _count_text_paragraphs(root: ET.Element) -> int:
    count = 0
    for paragraph in root.iter(f"{{{WORD_NS}}}p"):
        text = "".join(node.text or "" for node in paragraph.iter(f"{{{WORD_NS}}}t"))
        if text.strip():
            count += 1
    return count


def _safe_find_unrendered_markers(docx_bytes: bytes) -> list[str]:
    try:
        return find_unrendered_markers(docx_bytes)
    except Exception:
        return ["source_marker_scan_failed"]


def _source_faithful_fallback_reasons(
    *,
    source_resolution: SourceCvDocxResolution,
    source_detection: dict[str, Any],
    source_markers: list[str],
) -> list[str]:
    reasons: list[str] = []
    if source_resolution.docx is None:
        reasons.append(source_resolution.reason)
    elif not source_detection.get("eligible"):
        reasons.append("source_detection_ineligible")
        reasons.extend(str(reason) for reason in _list(source_detection.get("reasons")))
    if source_markers:
        reasons.append("source_contains_unrendered_markers")
        if "source_marker_scan_failed" in source_markers:
            reasons.append("source_marker_scan_failed")
    return list(dict.fromkeys(reason for reason in reasons if reason))


def _extract_source_docx_context_hints(docx_bytes: bytes) -> dict[str, Any]:
    if not docx_bytes:
        return {
            "version": HTML_SOURCE_CONTEXT_HINTS_VERSION,
            "source": "source_docx",
            "experience_years_label": "",
        }

    try:
        text = _source_docx_text(docx_bytes)
    except Exception:
        text = ""
    return {
        "version": HTML_SOURCE_CONTEXT_HINTS_VERSION,
        "source": "source_docx",
        "experience_years_label": _extract_experience_years_label(text),
    }


def _source_docx_text(docx_bytes: bytes) -> str:
    texts: list[str] = []
    with ZipFile(io.BytesIO(docx_bytes)) as archive:
        for part in sorted(
            name
            for name in archive.namelist()
            if name.startswith("word/") and name.endswith(".xml")
        ):
            if not re.search(r"/(?:document|header\d+|footer\d+)\.xml$", part):
                continue
            try:
                root = ET.fromstring(archive.read(part))
            except ET.ParseError:
                continue
            for paragraph in root.iter(f"{{{WORD_NS}}}p"):
                text = "".join(node.text or "" for node in paragraph.iter(f"{{{WORD_NS}}}t"))
                if text.strip():
                    texts.append(text.strip())
    return "\n".join(texts)


def _extract_experience_years_label(text: str) -> str:
    match = re.search(
        r"\b\d{1,2}\s*(?:ans?|ann[ée]es?)\s+d[’']exp[ée]rience\b",
        text,
        flags=re.I,
    )
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(0)).strip()


def _apply_source_docx_context_hints(
    canonical_context: dict[str, Any],
    hints: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    enriched_context = deepcopy(canonical_context)
    summary = {
        "version": HTML_SOURCE_CONTEXT_HINTS_VERSION,
        "enabled": bool(hints),
        "source": hints.get("source") if isinstance(hints, dict) else "",
        "applied_fields": [],
    }
    if not isinstance(hints, dict):
        return enriched_context, summary

    experience_years_label = str(hints.get("experience_years_label") or "").strip()
    if experience_years_label:
        metrics = enriched_context.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
            enriched_context["metrics"] = metrics
        metrics["source_experience_years_label"] = experience_years_label
        metrics["total_experience_years_label"] = experience_years_label
        summary["applied_fields"].extend(
            [
                "metrics.source_experience_years_label",
                "metrics.total_experience_years_label",
            ]
        )

    return enriched_context, summary


def _augment_html_context_from_source_text(
    *,
    canonical_context: dict[str, Any],
    source_text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    augmented_context = deepcopy(canonical_context)
    summary: dict[str, Any] = {
        "version": "source_text_context_augmentation.v1",
        "enabled": bool(str(source_text or "").strip()),
        "technical_skills_added": 0,
        "languages_completed": 0,
        "education_added": 0,
        "experiences_augmented": 0,
        "tasks_appended": 0,
        "project_examples_appended": 0,
        "source_blocks_trimmed_by_guidance": 0,
    }
    if not summary["enabled"]:
        return augmented_context, summary

    skills = augmented_context.get("skills")
    if not isinstance(skills, dict):
        skills = {}
        augmented_context["skills"] = skills
    technical = _dedupe_strings(_list(skills.get("technical")))
    key_skills = _dedupe_strings(_list(skills.get("key")))
    for item in _source_text_tool_items(source_text):
        normalized = _normalize_skill_text(item)
        if normalized and normalized not in {_normalize_skill_text(value) for value in technical}:
            technical.append(item)
            summary["technical_skills_added"] += 1
        if normalized and normalized not in {_normalize_skill_text(value) for value in key_skills}:
            key_skills.append(item)
    skills["technical"] = technical
    skills["key"] = key_skills

    languages = [_dict(item) for item in _list(augmented_context.get("languages"))]
    language_index = {_normalize_text(item.get("name")): item for item in languages if _normalize_text(item.get("name"))}
    for source_language in _source_text_language_items(source_text):
        normalized = _normalize_text(source_language.get("name"))
        if not normalized:
            continue
        existing = language_index.get(normalized)
        if existing is None:
            languages.append(source_language)
            language_index[normalized] = source_language
            summary["languages_completed"] += 1
        elif source_language.get("level") and not _clean_text(existing.get("level")):
            existing["level"] = source_language["level"]
            summary["languages_completed"] += 1
    augmented_context["languages"] = languages

    education = [_dict(item) for item in _list(augmented_context.get("education"))]
    existing_education = {
        _normalize_text(" ".join([str(item.get("degree") or ""), str(item.get("institution") or "")]))
        for item in education
    }
    existing_education_institutions = {
        _normalize_text(item.get("institution"))
        for item in education
        if _normalize_text(item.get("institution"))
    }
    for source_education in _source_text_education_items(source_text):
        normalized = _normalize_text(
            " ".join([str(source_education.get("degree") or ""), str(source_education.get("institution") or "")])
        )
        normalized_institution = _normalize_text(source_education.get("institution"))
        if (
            normalized
            and normalized not in existing_education
            and normalized_institution not in existing_education_institutions
        ):
            education.append(source_education)
            existing_education.add(normalized)
            if normalized_institution:
                existing_education_institutions.add(normalized_institution)
            summary["education_added"] += 1
    augmented_context["education"] = education

    experiences = augmented_context.get("experiences")
    if isinstance(experiences, list):
        excluded_source_markers = _source_text_exclusion_markers_from_guidance(augmented_context)
        task_owner_index: dict[str, int] = {}
        for experience_index, experience in enumerate(experiences):
            if not isinstance(experience, dict):
                continue
            for task in _coerce_tasks(experience):
                normalized_task = _normalize_task_text(task)
                if normalized_task:
                    task_owner_index.setdefault(normalized_task, experience_index)

        source_blocks = _build_experience_source_blocks(
            source_text=source_text,
            canonical_payload=augmented_context,
        )
        source_project_example_lines = _source_text_project_example_lines(source_text)
        for block in source_blocks:
            block, trimmed = _trim_source_block_at_excluded_markers(
                block,
                excluded_source_markers=excluded_source_markers,
            )
            if trimmed:
                summary["source_blocks_trimmed_by_guidance"] += 1
            index = block.get("index")
            if not isinstance(index, int) or index < 0 or index >= len(experiences):
                continue
            experience = experiences[index]
            if not isinstance(experience, dict):
                continue
            appended = _append_source_block_to_experience(
                experience,
                block,
                experience_index=index,
                task_owner_index=task_owner_index,
                source_project_example_lines=source_project_example_lines,
            )
            if appended["tasks"] or appended["project_examples"]:
                summary["experiences_augmented"] += 1
                summary["tasks_appended"] += appended["tasks"]
                summary["project_examples_appended"] += appended["project_examples"]

    return augmented_context, summary


def _source_text_exclusion_markers_from_guidance(canonical_context: dict[str, Any]) -> set[str]:
    return _generation_guidance_exclusion_markers(canonical_context.get("generation_guidance"))


def _clean_generation_guidance_exclusion_target(value: Any) -> str:
    target = _clean_text(value)
    target = re.sub(
        r"\s+(?:du|de la|de ce|dans le|dans la|sur le|sur la)\s+"
        r"(?:rendu|cv|document|profil|template|mod[èe]le)\b.*$",
        "",
        target,
        flags=re.I,
    )
    target = re.sub(r"^(?:l['’]?\s*)?(?:exp[ée]rience|poste|mission)\s+", "", target, flags=re.I)
    target = re.sub(r"^(?:au|aux|chez|de|du|des|à|a)\s+", "", target, flags=re.I)
    return target.strip(" .,:;")


def _trim_source_block_at_excluded_markers(
    block: dict[str, Any],
    *,
    excluded_source_markers: set[str],
) -> tuple[dict[str, Any], bool]:
    if not excluded_source_markers:
        return block, False

    content_lines = [_clean_source_line(line) for line in _list(block.get("content_lines"))]
    cutoff_index: int | None = None
    for index, line in enumerate(content_lines):
        normalized_line = _normalize_guidance_matchable_text(line)
        normalized_line_tokens = set(normalized_line.split())
        if _is_excluded_experience_source_boundary(
            line,
            normalized_line=normalized_line,
            normalized_line_tokens=normalized_line_tokens,
            excluded_source_markers=excluded_source_markers,
        ):
            cutoff_index = index
            break
    if cutoff_index is None:
        return block, False

    trimmed_lines = [line for line in content_lines[:cutoff_index] if line]
    trimmed_block = dict(block)
    trimmed_block["content_lines"] = trimmed_lines
    trimmed_block["block_text"] = "\n".join(trimmed_lines)
    normalized_remaining = _normalize_text(trimmed_block["block_text"])
    for key in ("context_candidate", "environment_candidate"):
        candidate = _clean_text(trimmed_block.get(key))
        if candidate and _normalize_text(candidate) not in normalized_remaining:
            trimmed_block[key] = ""
    return trimmed_block, True


def _is_excluded_experience_source_boundary(
    line: str,
    *,
    normalized_line: str,
    normalized_line_tokens: set[str],
    excluded_source_markers: set[str],
) -> bool:
    marker_matched = any(
        marker
        and (
            marker in normalized_line
            or set(marker.split()).issubset(normalized_line_tokens)
        )
        for marker in excluded_source_markers
    )
    if not marker_matched:
        return False
    has_period_signal = bool(
        re.search(r"\b(?:19|20)\d{2}\b|\b\d{1,2}/\d{4}\b|\b\d{1,2}\s*[/-]\s*\d{1,2}\s*[/-]\s*\d{2,4}\b", line)
    )

    for marker in excluded_source_markers:
        marker_tokens = set(marker.split())
        if not marker_tokens or not marker_tokens.issubset(normalized_line_tokens):
            continue
        extra_tokens = {
            token
            for token in normalized_line_tokens - marker_tokens
            if token not in {"a", "au", "aux", "chez", "de", "des", "du", "la", "le", "les"}
        }
        if has_period_signal:
            return _normalized_source_line_starts_with_marker(
                normalized_line,
                marker_tokens=marker_tokens,
            )
        if len(extra_tokens) == 0:
            return True
    return False


def _normalized_source_line_starts_with_marker(
    normalized_line: str,
    *,
    marker_tokens: set[str],
) -> bool:
    line_tokens = [
        token
        for token in normalized_line.split()
        if token not in {"a", "au", "aux", "chez", "de", "des", "du", "la", "le", "les"}
    ]
    while line_tokens and re.fullmatch(r"\d{1,4}", line_tokens[0]):
        line_tokens.pop(0)
    marker_sequence = [token for token in normalized_line.split() if token in marker_tokens]
    if not marker_sequence:
        marker_sequence = list(marker_tokens)
    return line_tokens[: len(marker_sequence)] == marker_sequence


def _append_source_block_to_experience(
    experience: dict[str, Any],
    block: dict[str, Any],
    *,
    experience_index: int | None = None,
    task_owner_index: dict[str, int] | None = None,
    source_project_example_lines: set[str] | None = None,
) -> dict[str, int]:
    existing_texts = _normalized_experience_texts(experience)
    project_examples = _coerce_project_examples(experience)
    tasks = _coerce_tasks(experience)
    moved_project_examples = _move_source_project_examples_out_of_tasks(
        tasks=tasks,
        project_examples=project_examples,
        source_project_example_lines=source_project_example_lines or set(),
    )
    _remove_experience_metadata_tasks(
        tasks=tasks,
        experience=experience,
        block=block,
    )
    existing_task_texts = {
        _normalize_task_text(value)
        for value in tasks
        if _normalize_task_text(value)
    }
    existing_project_example_texts = {
        _normalize_task_text(value)
        for value in project_examples
        if _normalize_task_text(value)
    }
    if not _clean_text(experience.get("environment")) and _clean_text(block.get("environment_candidate")):
        experience["environment"] = _clean_text(block.get("environment_candidate"))
        existing_texts.add(_normalize_text(experience["environment"]))
    if not _clean_text(experience.get("context")) and _clean_text(block.get("context_candidate")):
        experience["context"] = _clean_text(block.get("context_candidate"))
        existing_texts.add(_normalize_text(experience["context"]))

    appended = {"tasks": 0, "project_examples": moved_project_examples}
    for line in _source_block_task_candidates(block):
        normalized = _normalize_task_text(line)
        if _looks_like_experience_metadata_line(line, experience=experience, block=block):
            continue
        if normalized and normalized in (source_project_example_lines or set()):
            if normalized not in existing_project_example_texts:
                project_examples.append(line)
                existing_project_example_texts.add(normalized)
                appended["project_examples"] += 1
            continue
        owner_index = (task_owner_index or {}).get(normalized)
        if owner_index is not None:
            continue
        if normalized and normalized not in existing_texts and normalized not in existing_task_texts:
            tasks.append(line)
            existing_texts.add(normalized)
            existing_task_texts.add(normalized)
            if task_owner_index is not None and experience_index is not None:
                task_owner_index.setdefault(normalized, experience_index)
            appended["tasks"] += 1
    return appended


def _move_source_project_examples_out_of_tasks(
    *,
    tasks: list[Any],
    project_examples: list[Any],
    source_project_example_lines: set[str],
) -> int:
    if not source_project_example_lines or not tasks:
        return 0
    existing_examples = {
        _normalize_task_text(value)
        for value in project_examples
        if _normalize_task_text(value)
    }
    kept_tasks: list[Any] = []
    moved = 0
    for task in tasks:
        normalized = _normalize_task_text(task)
        if normalized and normalized in source_project_example_lines:
            if normalized not in existing_examples:
                project_examples.append(task)
                existing_examples.add(normalized)
                moved += 1
            continue
        kept_tasks.append(task)
    tasks[:] = kept_tasks
    return moved


def _remove_experience_metadata_tasks(
    *,
    tasks: list[Any],
    experience: dict[str, Any],
    block: dict[str, Any],
) -> int:
    if not tasks:
        return 0
    kept_tasks: list[Any] = []
    removed = 0
    for task in tasks:
        if _looks_like_experience_metadata_line(task, experience=experience, block=block):
            removed += 1
            continue
        kept_tasks.append(task)
    tasks[:] = kept_tasks
    return removed


def _looks_like_experience_metadata_line(
    line: str,
    *,
    experience: dict[str, Any],
    block: dict[str, Any],
) -> bool:
    normalized = _normalize_task_text(line)
    if not normalized:
        return True
    metadata_values = [
        experience.get("role"),
        experience.get("position"),
        experience.get("context"),
        experience.get("summary"),
        experience.get("environment"),
        block.get("context_candidate"),
        block.get("environment_candidate"),
    ]
    for value in metadata_values:
        candidate = _normalize_task_text(value)
        if candidate and normalized == candidate:
            return True
    role = _normalize_task_text(_first(experience.get("role"), experience.get("position")))
    if role and normalized.startswith(role) and len(normalized) <= len(role) + 80:
        return True
    return False


def _coerce_project_examples(experience: dict[str, Any]) -> list[Any]:
    examples = experience.get("project_examples")
    if isinstance(examples, list):
        return examples
    example = _clean_text(examples)
    coerced: list[Any] = [example] if example else []
    experience["project_examples"] = coerced
    return coerced


def _source_text_project_example_lines(source_text: str) -> set[str]:
    lines = [_clean_source_line(line) for line in re.split(r"[\r\n]+", source_text or "")]
    examples: set[str] = set()
    collecting = False
    for line in lines:
        if not line:
            continue
        normalized = _normalize_text(line)
        if normalized.startswith("exemples de projets"):
            collecting = True
            continue
        if collecting and (
            normalized.startswith("environnement")
            or normalized == "missions"
            or normalized.startswith("contexte")
        ):
            collecting = False
            continue
        if collecting and not _is_source_line_noise(line):
            normalized_task = _normalize_task_text(line)
            if normalized_task:
                examples.add(normalized_task)
    return examples


def _source_block_task_candidates(block: dict[str, Any]) -> list[str]:
    candidates: list[str] = []
    for value in _list(block.get("content_lines")):
        clean = _clean_source_line(value)
        if not clean:
            continue
        if _is_source_line_noise(clean):
            continue
        candidates.append(clean)
    return _dedupe_strings(candidates)


def _source_text_tool_items(source_text: str) -> list[str]:
    items: list[str] = []
    for match in re.finditer(r"outils?\s+informatiques?\s*[:：]\s*(?P<value>[^\n\r]+)", source_text, flags=re.I):
        items.extend(_split_source_list(match.group("value")))
    return _dedupe_strings(items)


def _source_text_language_items(source_text: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for match in re.finditer(r"langues?\s*[:：]\s*(?P<value>[^\n\r]+)", source_text, flags=re.I):
        for item in _split_source_list(match.group("value")):
            lang_match = re.match(r"(?P<name>[^()]+?)(?:\s*\((?P<level>[^)]+)\))?$", item)
            if not lang_match:
                continue
            name = _clean_text(lang_match.group("name"))
            level = _clean_text(lang_match.group("level"))
            if name:
                items.append({"name": name, "level": level})
    return items


def _source_text_education_items(source_text: str) -> list[dict[str, str]]:
    section = _source_text_section(source_text, "formation", ("competences", "compétences", "experiences", "expériences"))
    if not section:
        return []
    lines = [_clean_source_line(line) for line in re.split(r"[\r\n]+", section)]
    lines = [line for line in lines if line]
    items: list[dict[str, str]] = []
    current_institution = ""
    for line in lines:
        if _is_probable_education_institution(line):
            current_institution = line
            continue
        if _is_education_date_or_location(line):
            continue
        if current_institution and _is_probable_education_degree(line):
            items.append({"degree": line, "institution": current_institution, "year": ""})
            current_institution = ""
    return items


def _source_text_section(source_text: str, start_label: str, end_labels: tuple[str, ...]) -> str:
    lines = re.split(r"[\r\n]+", source_text or "")
    start_index: int | None = None
    end_index = len(lines)
    for index, line in enumerate(lines):
        normalized = _normalize_text(line)
        if start_index is None and normalized == _normalize_text(start_label):
            start_index = index + 1
            continue
        if start_index is not None and normalized in {_normalize_text(label) for label in end_labels}:
            end_index = index
            break
    if start_index is None:
        return ""
    return "\n".join(lines[start_index:end_index])


def _split_source_list(value: str) -> list[str]:
    return [
        _clean_text(item)
        for item in re.split(r"\s*[;,]\s*|\s+;\s+", str(value or ""))
        if _clean_text(item)
    ]


def _clean_source_line(value: Any) -> str:
    clean = _clean_text(value)
    clean = re.sub(r"^[•✓▪●◦\-\uf0a7\uf0fc]+\s*", "", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" :;")
    return clean


def _is_source_line_noise(line: str) -> bool:
    normalized = _normalize_text(line)
    if not normalized:
        return True
    if normalized in {"missions", "mission", "projet contexte", "contexte descriptif"}:
        return True
    date_line = _normalize_source_date_line(line)
    month = (
        r"(?:janvier|janv|fevrier|février|fevr|févr|mars|avril|avr|mai|juin|juillet|juil|"
        r"aout|août|septembre|sept|octobre|oct|novembre|nov|decembre|décembre|dec|déc)"
    )
    month_year = rf"{month}\.?\s*\d{{4}}"
    if re.fullmatch(rf"{month_year}\s*(?:-|a|à)\s*{month_year}", date_line):
        return True
    if re.fullmatch(rf"{month_year}\s*(?:-|a|à)\s*(?:ce jour|poste actuel)", date_line):
        return True
    if re.fullmatch(r"\d{1,2}/\d{4}\s*(?:a|à|-)\s*(?:\d{1,2}/\d{4}|ce jour|poste actuel)", normalized):
        return True
    if re.fullmatch(r"\d{4}\s*(?:a|à|-)\s*\d{4}", normalized):
        return True
    if re.fullmatch(r"[\wÀ-ÖØ-öø-ÿ .'’/-]{2,50},\s*(?:france|maroc|belgique|suisse|luxembourg)", normalized):
        return True
    return False


def _normalize_source_date_line(line: str) -> str:
    clean = _clean_text(line).casefold()
    clean = clean.replace("–", "-").replace("—", "-")
    clean = re.sub(r"\s+", " ", clean)
    return clean.strip(" .")


def _is_education_date_or_location(line: str) -> bool:
    normalized = _normalize_text(line)
    if re.search(r"\b(?:septembre|juin|aout|août|juillet|amiens|meknes|maroc|france)\b", normalized):
        return True
    return bool(re.fullmatch(r"\d{4}(?:\s*[-–]\s*\d{4})?", normalized))


def _is_probable_education_institution(line: str) -> bool:
    normalized = _normalize_text(line)
    return any(
        keyword in normalized
        for keyword in (
            "universite",
            "université",
            "institut",
            "ecole",
            "école",
            "classes preparatoires",
            "classes préparatoires",
            "groupe scolaire",
            "iae",
        )
    )


def _is_probable_education_degree(line: str) -> bool:
    normalized = _normalize_text(line)
    return any(
        keyword in normalized
        for keyword in (
            "licence",
            "master",
            "baccalaureat",
            "baccalauréat",
            "branche",
            "diplome",
            "diplôme",
            "ingenieur",
            "ingénieur",
        )
    )


class CompanyCvHtmlRenderService:
    @staticmethod
    def render_company_cv_html_docx(
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

        source_resolution = _resolve_source_cv_docx(canonical_context=canonical_context, project=project)
        source_docx = source_resolution.docx
        source_detection = (
            _detect_absis_source_docx(source_docx.bytes)
            if source_docx is not None
            else _source_detection_result(
                eligible=False,
                reasons=[source_resolution.reason],
                features={},
            )
        )
        source_docx_hints = (
            _extract_source_docx_context_hints(source_docx.bytes)
            if source_docx is not None
            else {
                "version": HTML_SOURCE_CONTEXT_HINTS_VERSION,
                "source": "source_docx",
                "experience_years_label": "",
            }
        )
        source_text_resolution = _resolve_source_cv_text(canonical_context=canonical_context, project=project)
        source_markers = _safe_find_unrendered_markers(source_docx.bytes) if source_docx is not None else []
        source_fallback_reasons = _source_faithful_fallback_reasons(
            source_resolution=source_resolution,
            source_detection=source_detection,
            source_markers=source_markers,
        )
        source_fallback_reasons = list(
            dict.fromkeys(
                [
                    "html_renderer_absis_rebuild_no_source_copy",
                    *source_fallback_reasons,
                ]
            )
        )

        generation_trace: dict[str, Any] | None = None
        generation_render_context: dict[str, Any] | None = None
        if template.get("contract_version") and template.get("template_contract"):
            generation_payload = generate_company_cv_contract_payload(
                sheet_id=sheet_id,
                template=template,
                generation_guidance=generation_guidance,
            )
            canonical_context = generation_payload["canonical_context"]
            generation_render_context = _dict(generation_payload.get("render_context"))
            generation_trace = generation_payload["generation_trace"]

        context_augmentation = {"version": HTML_CONTEXT_AUGMENTATION_VERSION, "enabled": False}
        if generation_render_context:
            canonical_context, context_augmentation = _augment_html_context_from_render_context(
                canonical_context=canonical_context,
                generation_render_context=generation_render_context,
            )
        canonical_context, source_context_hints = _apply_source_docx_context_hints(
            canonical_context,
            source_docx_hints,
        )
        canonical_context, source_text_augmentation = _augment_html_context_from_source_text(
            canonical_context=canonical_context,
            source_text=source_text_resolution.text,
        )

        payload = build_company_cv_html_render_payload(
            canonical_context=canonical_context,
            template_record=template,
            template_bytes=template_bytes,
        )
        validation_warnings = payload.trace.get("validation", {}).get("warnings", [])
        if validation_warnings:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "HTML DOCX generation blocked because the generated template is not Word-safe: "
                    + ", ".join(str(item) for item in validation_warnings)
                ),
            )

        html_fingerprint = sha256(payload.html.encode("utf-8")).hexdigest()
        render_context = {
            "mode": HTML_RENDER_MODE,
            "renderer_version": HTML_RENDERER_VERSION,
            "interface_version": HTML_INTERFACE_VERSION,
            "html_fingerprint": html_fingerprint,
            "html_length": len(payload.html),
            "context_fingerprint": payload.trace.get("context", {}).get("fingerprint"),
            "binding_matrix_fingerprint": payload.trace.get("binding_matrix", {}).get("fingerprint"),
            "document_options": payload.document_options,
            "ooxml_normalization_version": HTML_OOXML_NORMALIZATION_VERSION,
            "template_shell_version": HTML_TEMPLATE_SHELL_VERSION,
            "ooxml_audit_version": HTML_OOXML_AUDIT_VERSION,
            "template_capture": payload.trace.get("html_spec", {}),
            "validation": payload.trace.get("validation", {}),
            "context_augmentation": context_augmentation,
            "source_context_hints": source_context_hints,
            "source_text_augmentation": source_text_augmentation,
            "source_text_resolution": {
                "reason": source_text_resolution.reason,
                "storage_path": source_text_resolution.storage_path,
                "error": source_text_resolution.error,
            },
            "source_faithful": {
                "version": HTML_SOURCE_FAITHFUL_VERSION,
                "enabled": False,
                "html_generation_forced": True,
                "source_copy_disabled": True,
                "source_cv_path": source_docx.storage_path if source_docx is not None else None,
                "source_hash": source_docx.content_hash if source_docx is not None else None,
                "source_resolution": source_resolution.reason,
                "source_resolution_error": source_resolution.error,
                "detection": source_detection,
                "context_hints": source_docx_hints,
                "source_markers": source_markers,
                "fallback_reasons": source_fallback_reasons,
            },
        }
        render_fingerprint = render_context_fingerprint(
            template_record=template,
            canonical_context=canonical_context,
            render_context=render_context,
            sheet_id=sheet_id,
            renderer_version=f"{HTML_RENDER_MODE}:{HTML_RENDERER_VERSION}",
        )

        identity = canonical_context.get("identity") or {}
        candidate_filename = identity.get("source_filename") or sheet["candidate_id"]
        candidate_safe = _slug(Path(candidate_filename).stem)
        template_safe = _slug(template.get("name") or template.get("original_filename") or "template")
        output_filename = f"{candidate_safe}_{template_safe}_{HTML_RENDER_MODE}.docx"
        base_storage_path = (
            f"enterprises/{enterprise_id}/projects/{project['id']}/generated_cvs_html_docx/"
            f"{candidate_safe}/{render_fingerprint}"
        )
        storage_path = f"{base_storage_path}.docx"
        trace_storage_path = f"{base_storage_path}.trace.json"

        if FileStorage.file_exists(storage_path):
            if not FileStorage.file_exists(trace_storage_path):
                FileStorage.save_json(
                    trace_storage_path,
                    _build_html_docx_trace_payload(
                        template=template,
                        canonical_context=canonical_context,
                        render_context=render_context,
                        render_fingerprint=render_fingerprint,
                        tenant_id=tenant_id,
                        enterprise_id=enterprise_id,
                        project_id=project["id"],
                        sheet_id=sheet_id,
                        payload=payload,
                        storage_path=storage_path,
                        trace_storage_path=trace_storage_path,
                        generation_trace=generation_trace,
                    ),
                )
            return _render_result(
                template=template,
                canonical_context=canonical_context,
                render_context=render_context,
                storage_path=storage_path,
                trace_storage_path=trace_storage_path,
                output_filename=output_filename,
                output_bytes=FileStorage.load_bytes(storage_path),
                tenant_id=tenant_id,
                enterprise_id=enterprise_id,
                project_id=project["id"],
                sheet_id=sheet_id,
                render_fingerprint=render_fingerprint,
            )

        try:
            output_bytes = render_html_payload_to_docx_bytes(payload=payload)
            output_bytes = _finalize_html_docx_bytes(output_bytes, template_bytes)
        except HtmlDocxStructuralError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Generated HTML DOCX is structurally unstable for Microsoft Word, generation blocked: "
                    f"{exc}"
                ),
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "HTML DOCX converter is unavailable. Ensure the backend image installs "
                    "tools/company_cv_html_renderer dependencies. "
                    f"Details: {exc}"
                ),
            ) from exc

        remaining_markers = find_unrendered_markers(output_bytes)
        if remaining_markers:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Rendered HTML DOCX still contains template markers, generation blocked: "
                    + ", ".join(remaining_markers[:10])
                ),
            )

        trace_payload = _build_html_docx_trace_payload(
            template=template,
            canonical_context=canonical_context,
            render_context=render_context,
            render_fingerprint=render_fingerprint,
            tenant_id=tenant_id,
            enterprise_id=enterprise_id,
            project_id=project["id"],
            sheet_id=sheet_id,
            payload=payload,
            storage_path=storage_path,
            trace_storage_path=trace_storage_path,
            generation_trace=generation_trace,
        )
        FileStorage.save_bytes(storage_path, output_bytes, content_type=DOCX_CONTENT_TYPE)
        FileStorage.save_json(trace_storage_path, trace_payload)

        return _render_result(
            template=template,
            canonical_context=canonical_context,
            render_context=render_context,
            storage_path=storage_path,
            trace_storage_path=trace_storage_path,
            output_filename=output_filename,
            output_bytes=output_bytes,
            tenant_id=tenant_id,
            enterprise_id=enterprise_id,
            project_id=project["id"],
            sheet_id=sheet_id,
            render_fingerprint=render_fingerprint,
        )


def _build_html_docx_trace_payload(
    *,
    template: dict[str, Any],
    canonical_context: dict[str, Any],
    render_context: dict[str, Any],
    render_fingerprint: str,
    tenant_id: str | None,
    enterprise_id: str,
    project_id: str,
    sheet_id: str,
    payload: CompanyCvHtmlRenderPayload,
    storage_path: str,
    trace_storage_path: str,
    generation_trace: dict[str, Any] | None,
) -> dict[str, Any]:
    trace_payload = build_render_trace(
        template_record=template,
        canonical_context=canonical_context,
        render_context=render_context,
        render_fingerprint=render_fingerprint,
        tenant_id=tenant_id,
        enterprise_id=enterprise_id,
        project_id=project_id,
        sheet_id=sheet_id,
    )
    trace_payload["renderer"] = {
        "mode": HTML_RENDER_MODE,
        "version": HTML_RENDERER_VERSION,
    }
    trace_payload["html_docx"] = {
        **payload.trace,
        "html": {
            "fingerprint": render_context["html_fingerprint"],
            "length": render_context["html_length"],
        },
        "storage_path": storage_path,
        "trace_storage_path": trace_storage_path,
    }
    if generation_trace is not None:
        trace_payload["generation"] = generation_trace
    return trace_payload


def _render_result(
    *,
    template: dict[str, Any],
    canonical_context: dict[str, Any],
    render_context: dict[str, Any],
    storage_path: str,
    trace_storage_path: str,
    output_filename: str,
    output_bytes: bytes,
    tenant_id: str | None,
    enterprise_id: str,
    project_id: str,
    sheet_id: str,
    render_fingerprint: str,
) -> dict[str, Any]:
    return {
        "renderer": {
            "mode": HTML_RENDER_MODE,
            "version": HTML_RENDERER_VERSION,
        },
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
        "project_id": project_id,
        "sheet_id": sheet_id,
        "render_fingerprint": render_fingerprint,
    }


def _extract_page_options(root: ET.Element) -> dict[str, Any]:
    sect = root.find(".//w:sectPr", NS)
    if sect is None:
        return {}

    page_size = sect.find("w:pgSz", NS)
    page_margin = sect.find("w:pgMar", NS)
    return {
        "orientation": page_size.get(f"{{{WORD_NS}}}orient", "portrait") if page_size is not None else "portrait",
        "pageSize": {
            "width": _int_value(page_size.get(f"{{{WORD_NS}}}w")) if page_size is not None else None,
            "height": _int_value(page_size.get(f"{{{WORD_NS}}}h")) if page_size is not None else None,
        },
        "margins": {
            "top": _int_value(page_margin.get(f"{{{WORD_NS}}}top")) if page_margin is not None else None,
            "right": _int_value(page_margin.get(f"{{{WORD_NS}}}right")) if page_margin is not None else None,
            "bottom": _int_value(page_margin.get(f"{{{WORD_NS}}}bottom")) if page_margin is not None else None,
            "left": _int_value(page_margin.get(f"{{{WORD_NS}}}left")) if page_margin is not None else None,
            "header": _int_value(page_margin.get(f"{{{WORD_NS}}}header")) if page_margin is not None else None,
            "footer": _int_value(page_margin.get(f"{{{WORD_NS}}}footer")) if page_margin is not None else None,
            "gutter": _int_value(page_margin.get(f"{{{WORD_NS}}}gutter")) if page_margin is not None else None,
        },
    }


def _extract_branding(archive: ZipFile, document_xml: str) -> dict[str, str]:
    if "word/styles.xml" in archive.namelist():
        styles_payload = archive.read("word/styles.xml")
        try:
            styles_root = ET.fromstring(styles_payload)
        except ET.ParseError:
            styles_root = None
        if styles_root is not None and _has_absis_template_styles(styles_root):
            return _extract_absis_branding_from_styles(styles_root)

    colors = []
    for color in re.findall(r'w:color w:val="([0-9A-Fa-f]{6})"', document_xml):
        normalized = color.upper()
        if normalized not in {"000000", "FFFFFF", "AUTO"} and normalized not in colors:
            colors.append(normalized)

    return {
        key: value
        for key, value in {
            "primary_color": colors[0] if colors else "",
            "secondary_color": colors[1] if len(colors) > 1 else "",
        }.items()
        if value
    }


def _extract_absis_branding_from_styles(styles_root: ET.Element) -> dict[str, str]:
    style_tokens = {
        style.get(f"{{{WORD_NS}}}styleId"): style
        for style in styles_root.findall("w:style", NS)
        if style.get(f"{{{WORD_NS}}}styleId")
    }

    def style_color(style_id: str, default: str) -> str:
        style = style_tokens.get(style_id)
        color = style.find("./w:rPr/w:color", NS) if style is not None else None
        value = color.get(f"{{{WORD_NS}}}val") if color is not None else ""
        return _hex_color(value, default)

    return {
        "font_family": HTML_DEFAULT_FONT_FAMILY,
        "primary_color": style_color("DISPOetEXPERIENCE", HTML_ABSIS_PRIMARY_COLOR),
        "secondary_color": style_color("Rle", HTML_ABSIS_ROLE_COLOR),
        "muted_color": style_color("Normal", HTML_ABSIS_MUTED_COLOR),
        "section_title_color": style_color("Titrestabeau", HTML_ABSIS_SECTION_TITLE_COLOR),
        "environment_color": style_color("Environnement", HTML_ABSIS_ENVIRONMENT_COLOR),
        "border_color": HTML_ABSIS_BORDER_COLOR,
        "sidebar_background": "FFFFFF",
    }


def _extract_shell_text(archive: ZipFile, root: ET.Element) -> dict[str, Any]:
    rel_targets = _relationship_targets(archive)
    sect = root.find(".//w:sectPr", NS)
    header_text = ""
    footer_text = ""
    if sect is not None:
        header_text = _first_related_part_text(archive, rel_targets, sect.findall("w:headerReference", NS))
        footer_text = _first_related_part_text(archive, rel_targets, sect.findall("w:footerReference", NS))
    return {
        "header_text": header_text,
        "footer_text": footer_text,
        "media_parts": sorted(name for name in archive.namelist() if name.startswith("word/media/")),
    }


def _relationship_targets(archive: ZipFile) -> dict[str, str]:
    if "word/_rels/document.xml.rels" not in archive.namelist():
        return {}
    root = ET.fromstring(archive.read("word/_rels/document.xml.rels"))
    targets: dict[str, str] = {}
    for rel in root:
        rel_id = rel.attrib.get("Id")
        target = rel.attrib.get("Target")
        if rel_id and target:
            targets[rel_id] = f"word/{target}" if not target.startswith("word/") else target
    return targets


def _first_related_part_text(
    archive: ZipFile,
    rel_targets: dict[str, str],
    references: list[ET.Element],
) -> str:
    for ref in references:
        rel_id = ref.get(f"{{{REL_NS}}}id")
        target = rel_targets.get(str(rel_id))
        if target and target in archive.namelist():
            return _word_text(archive.read(target))
    return ""


def _word_text(xml_bytes: bytes) -> str:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return ""
    return " ".join(
        text.strip()
        for text in (node.text or "" for node in root.iter(f"{{{WORD_NS}}}t"))
        if text.strip()
    )


def _html_section_contract() -> list[dict[str, Any]]:
    return [
        {"id": "identity", "source": "identity", "repeatable": False},
        {"id": "experience_summary", "source": "experiences", "repeatable": True, "max_first_page": 4},
        {"id": "skills", "source": "skills", "repeatable": True},
        {"id": "education", "source": "education", "repeatable": True},
        {"id": "certifications", "source": "certifications", "repeatable": True},
        {"id": "languages", "source": "languages", "repeatable": True},
        {"id": "extra_sections", "source": "extra_sections", "repeatable": True},
        {"id": "experiences", "source": "experiences", "repeatable": True, "unbounded": True},
    ]


def _render_absis_first_page(
    identity: dict[str, Any],
    canonical_context: dict[str, Any],
    metrics: dict[str, Any],
    skills: dict[str, Any],
    experiences: list[dict[str, Any]],
    education: list[dict[str, Any]],
    certifications: list[dict[str, Any]],
    languages: list[dict[str, Any]],
    extra_sections: list[dict[str, Any]],
    primary: str,
    secondary: str,
    muted: str,
    section_title: str,
    environment: str,
    border: str,
) -> str:
    full_name = _first(identity.get("full_name"), "Candidate")
    title = _first(canonical_context.get("title"), identity.get("title"), "")
    years_label = _display_experience_label(metrics)
    availability = _first(canonical_context.get("availability"), "")

    return "".join(
        [
            '<table role="presentation" data-section="absis-identity" '
            f'style="width:{HTML_MAIN_CONTENT_WIDTH};border-collapse:collapse;table-layout:fixed;margin:0 0 5pt 0;">'
            f'<colgroup><col style="width:{HTML_ABSIS_TITLE_WIDTH};"><col style="width:{HTML_ABSIS_META_WIDTH};"></colgroup>'
            "<tr>"
            f'<td{_slot_attrs("identity.full_name", "identity")} '
            f'style="vertical-align:top;padding:0 0 6pt 0;font-size:21.5pt;line-height:1.05;'
            f'font-weight:bold;color:#{primary};">{escape(full_name)}</td>'
            f'<td{_slot_attrs("metrics.total_experience_years_label", "identity")} '
            f'style="vertical-align:top;text-align:right;padding:6pt 0 0 0;font-size:9.4pt;line-height:1.1;'
            f'font-weight:bold;font-style:italic;color:#{primary};">{escape(years_label)}</td>'
            "</tr>"
            "<tr>"
            f'<td{_slot_attrs("title", "identity")} '
            f'style="vertical-align:bottom;padding:0 6pt 3pt 0;border-bottom:0.8pt solid #{secondary};'
            f'font-size:13.2pt;line-height:1.05;font-weight:bold;color:#{secondary};">{escape(title)}</td>'
            f'<td{_slot_attrs("availability", "identity")} '
            f'style="vertical-align:bottom;text-align:right;padding:0 0 4pt 3pt;font-size:9.4pt;'
            f'font-weight:bold;font-style:italic;color:#{primary};">'
            f'{escape("Disponibilité : " + availability) if availability else ""}</td>'
            "</tr>"
            "</table>",
            _render_absis_teaser(experiences, primary, muted, border),
            _render_absis_skills_tables(skills, title, primary, secondary, muted, section_title, border),
            _render_absis_support_grid(
                education,
                certifications,
                languages,
                extra_sections,
                primary,
                section_title,
                muted,
                environment,
                border,
            ),
        ]
    )


def _render_absis_teaser(
    experiences: list[dict[str, Any]],
    primary: str,
    muted: str,
    border: str,
) -> str:
    if not experiences:
        return ""

    rows: list[str] = []
    for experience in experiences[:4]:
        company = _first(experience.get("company_full"), experience.get("company"), "")
        role = _first(experience.get("role"), experience.get("position"), "")
        period = _compact_period_label(_first(experience.get("period_full"), experience.get("period"), ""))
        detail = " - ".join(item for item in [role, company] if item)
        rows.append(
            "<tr>"
            f'<td{_slot_attrs("experiences[].period_full", "experience_summary")} '
            f'style="width:{HTML_ABSIS_TEASER_PERIOD_WIDTH};vertical-align:top;padding:1pt 5pt 1pt 4pt;'
            f'border:none;border-left:2pt solid #{primary};'
            f'font-size:8.8pt;font-weight:bold;font-style:italic;color:#{primary};">'
            f"{escape(period)}</td>"
            f'<td{_slot_attrs("experiences[].role", "experience_summary")} '
            f'style="width:{HTML_ABSIS_TEASER_DETAIL_WIDTH};vertical-align:top;padding:1pt 4pt 1pt 5pt;'
            f'border:none;font-size:8.5pt;font-weight:bold;font-style:italic;color:#{muted};">'
            f"{escape(detail)}</td>"
            "</tr>"
        )

    return (
        '<table role="presentation" data-section="experience-summary" '
        f'{_data_attrs({"data-brain-repeat": "experiences", "data-brain-item": "experience_summary"})} '
        'style="width:5.98in;border-collapse:collapse;table-layout:fixed;margin:0 0 7pt 0;">'
        f'<colgroup><col style="width:{HTML_ABSIS_TEASER_PERIOD_WIDTH};">'
        f'<col style="width:{HTML_ABSIS_TEASER_DETAIL_WIDTH};"></colgroup>'
        + "".join(rows)
        + "</table>"
    )


def _render_absis_skills_tables(
    skills: dict[str, Any],
    title: str,
    primary: str,
    secondary: str,
    muted: str,
    section_title: str,
    border: str,
) -> str:
    key_skills = _select_absis_primary_skills(skills, title)[:20]
    key_seen = {_normalize_skill_text(item) for item in key_skills}
    domain_skills = _dedupe_strings(_list(skills.get("domain")) or _list(skills.get("soft")))
    domain_skills = [item for item in domain_skills if _normalize_skill_text(item) not in key_seen]
    technical_rows = _technical_skill_rows(skills)

    html: list[str] = []
    if key_skills:
        html.append(
            _absis_section_table(
                title="Compétences",
                body=_compact_phrase_list(key_skills, muted, attrs=_data_attrs({"data-brain-repeat": "skills.key"})),
                primary=primary,
                secondary=secondary,
                section_title=section_title,
                border=border,
                section="skills-key",
            )
        )
    if domain_skills:
        html.append(
            _absis_section_table(
                title="Compétences métiers",
                body=_compact_phrase_list(domain_skills, muted, attrs=_data_attrs({"data-brain-repeat": "skills.domain"})),
                primary=primary,
                secondary=secondary,
                section_title=section_title,
                border=border,
                section="skills-domain",
            )
        )
    if technical_rows:
        body = [
            '<table role="presentation" data-section="technical-skills" '
            f'{_data_attrs({"data-brain-repeat": "skills.categories"})} '
            f'style="width:100%;border-collapse:collapse;table-layout:fixed;margin:0;">'
            '<colgroup><col style="width:1.70in;"><col style="width:4.90in;"></colgroup>'
        ]
        for label, values in technical_rows:
            body.append(
                "<tr>"
                f'<td style="vertical-align:top;padding:2pt 4pt 2pt 0;border:none;'
                f'font-size:8.6pt;font-weight:bold;color:#{section_title};">{escape(label)}</td>'
                f'<td style="vertical-align:top;padding:2pt 0 2pt 4pt;border:none;'
                f'font-size:8.6pt;color:#{muted};">{escape(", ".join(values))}</td>'
                "</tr>"
            )
        body.append("</table>")
        html.append(
            _absis_section_table(
                title="Compétences techniques",
                body="".join(body),
                primary=primary,
                secondary=secondary,
                section_title=section_title,
                border=border,
                section="skills-technical",
            )
        )
    return "".join(html)


def _select_absis_primary_skills(skills: dict[str, Any], title: str) -> list[str]:
    key_skills = _dedupe_strings(_list(skills.get("key")))
    domain_skills = _dedupe_strings(_list(skills.get("domain")) or _list(skills.get("soft")))
    technical_skills = _dedupe_strings(_list(skills.get("technical")))

    if _title_prefers_business_architecture_skills(title) and domain_skills:
        selected = list(domain_skills)
        selected.extend(
            item
            for item in key_skills
            if _looks_like_business_architecture_skill(item)
            and _normalize_skill_text(item) not in {_normalize_skill_text(value) for value in selected}
        )
        return _dedupe_strings(selected)

    if key_skills:
        return key_skills
    if domain_skills:
        return domain_skills
    return technical_skills


def _title_prefers_business_architecture_skills(title: str) -> bool:
    normalized = _normalize_text(title)
    return any(
        token in normalized
        for token in (
            "architecte",
            "architecture",
            "fonctionnel",
            "urbanisation",
            "pmo",
            "business analyst",
            "amoa",
        )
    )


def _looks_like_business_architecture_skill(skill: str) -> bool:
    normalized = _normalize_text(skill)
    return any(
        token in normalized
        for token in (
            "architecture",
            "urbanisation",
            "gouvernance",
            "cartographie",
            "amoa",
            "pmo",
            "bpm",
            "bpr",
            "processus",
            "metier",
            "métier",
            "fonctionnel",
            "pilotage",
            "gestion de projet",
            "coordination",
            "rédaction",
            "redaction",
            "leadership",
        )
    )


def _render_absis_support_grid(
    education: list[dict[str, Any]],
    certifications: list[dict[str, Any]],
    languages: list[dict[str, Any]],
    extra_sections: list[dict[str, Any]],
    primary: str,
    section_title: str,
    muted: str,
    environment: str,
    border: str,
) -> str:
    left_parts: list[str] = []
    education_lines = _education_lines(education)
    certification_lines = _certification_lines(certifications)
    if education_lines or certification_lines:
        left_parts.append(_inline_heading("Formation/Certification", section_title))
        left_parts.append(_line_list(education_lines, muted))
        if certification_lines:
            left_parts.append(_inline_heading("Certifications", section_title))
            left_parts.append(_line_list(certification_lines, muted))

    right_parts: list[str] = []
    language_lines = _language_lines(languages)
    if language_lines:
        right_parts.append(_inline_heading("Langues", section_title))
        right_parts.append(_line_list(language_lines, muted))
    right_parts.append(_render_extra_sections(extra_sections, section_title, muted))

    if not left_parts and not right_parts:
        return ""
    return (
        '<table role="presentation" data-section="education-language-grid" '
        f'style="width:{HTML_MAIN_CONTENT_WIDTH};border-collapse:collapse;table-layout:fixed;margin:5pt 0 2pt 0;">'
        '<colgroup><col style="width:3.40in;"><col style="width:3.38in;"></colgroup>'
        "<tr>"
        f'<td style="vertical-align:top;padding:3pt 12pt 0 0;border-top:0.7pt solid #{border};">'
        + "".join(left_parts)
        + "</td>"
        f'<td style="vertical-align:top;padding:3pt 0 0 12pt;border-top:0.7pt solid #{border};">'
        + "".join(right_parts)
        + "</td>"
        "</tr></table>"
    )


def _absis_section_table(
    *,
    title: str,
    body: str,
    primary: str,
    secondary: str,
    section_title: str,
    border: str,
    section: str,
) -> str:
    return (
        f'<table role="presentation" data-section="{escape(section, quote=True)}" '
        f'style="width:{HTML_MAIN_CONTENT_WIDTH};border-collapse:collapse;table-layout:fixed;margin:0 0 5pt 0;">'
        '<colgroup><col style="width:6.78in;"></colgroup>'
        "<tr>"
        f'<td style="width:6.78in;vertical-align:top;padding:0 0 0 0;">'
        f'<p style="margin:0 0 3pt 0;padding:0 0 2pt 0;border-bottom:0.8pt solid #{border};'
        f'font-size:10.2pt;font-weight:bold;text-decoration:underline;color:#{section_title};">{escape(title)}</p>'
        f"{body}</td>"
        "</tr></table>"
    )


def _render_extra_sections(extra_sections: list[dict[str, Any]], primary: str, muted: str) -> str:
    html: list[str] = []
    for section in extra_sections:
        title = str(section.get("title") or "").strip()
        items = _dedupe_strings(_list(section.get("items")))
        if not title or not items:
            continue
        html.append(
            _inline_heading(
                title,
                primary,
                attrs=_data_attrs({"data-section": "extra-section", "data-brain-repeat": "extra_sections"}),
            )
        )
        html.append(_line_list(items, muted))
    return "".join(html)


def _technical_skill_rows(skills: dict[str, Any]) -> list[tuple[str, list[str]]]:
    categories = _dict(skills.get("categories"))
    technical = _dedupe_strings(_list(skills.get("technical")))
    labels = [
        ("data_bi", "Data / BI"),
        ("dev", "Développement"),
        ("cloud", "Cloud & Architecture"),
        ("gestion", "Gestion de projet"),
        ("monitoring", "Monitoring & Production"),
        ("api", "API & Services"),
        ("paiements", "Paiements & Normes bancaires"),
    ]
    rows: list[tuple[str, list[str]]] = []
    seen: set[str] = set()
    for key, label in labels:
        values = _dedupe_strings(_list(categories.get(key)))
        if values:
            rows.append((label, values))
            seen.update(_normalize_text(value) for value in values)
    uncategorized = [value for value in technical if _normalize_text(value) not in seen]
    if uncategorized:
        rows.append(("Outils / Techniques", uncategorized))
    if not rows and technical:
        rows.append(("Outils / Techniques", technical))
    return rows


def _should_force_detail_page_break(skills: dict[str, Any]) -> bool:
    first_page_load = (
        min(len(_dedupe_strings(_list(skills.get("key")))), 10)
        + len(_dedupe_strings(_list(skills.get("domain")) or _list(skills.get("soft"))))
        + len(_dedupe_strings(_list(skills.get("technical"))))
    )
    return first_page_load <= 55


def _display_experience_label(metrics: dict[str, Any]) -> str:
    label = _first(metrics.get("source_experience_years_label"), metrics.get("total_experience_years_label"), "")
    if not label:
        return ""
    clean = label.strip()
    if re.search(r"exp[ée]rience", clean, flags=re.I):
        return clean
    match = re.fullmatch(r"(\d+(?:[,.]\d+)?)\s*(?:ans?|ann[ée]es?)?", clean, flags=re.I)
    if match:
        years = int(round(float(match.group(1).replace(",", "."))))
        unit = "année" if years == 1 else "années"
        return f"{years} {unit} d’expérience"
    return clean


def _compact_period_label(period: str) -> str:
    clean = str(period or "").strip()
    if not clean:
        return ""
    clean = re.sub(r"\s*\([^)]*\)\s*$", "", clean)
    clean = clean.replace("Poste actuel", "Aujourd’hui")
    clean = clean.replace("poste actuel", "Aujourd’hui")
    years = re.findall(r"\b(?:19|20)\d{2}\b", clean)
    if years:
        start_year = years[0]
        end_year = "Aujourd’hui" if "Aujourd’hui" in clean else years[-1]
        return start_year if end_year == start_year and len(years) == 1 else f"{start_year} - {end_year}"
    return clean


def _clean_absis_period_label(period: str) -> str:
    clean = str(period or "").strip()
    if not clean:
        return ""
    return re.sub(r"\s*\([^)]*(?:ans?|ann[ée]es?|mois|months?|years?)[^)]*\)\s*$", "", clean, flags=re.I).strip()


def _render_identity(
    identity: dict[str, Any],
    canonical_context: dict[str, Any],
    metrics: dict[str, Any],
    primary: str,
    secondary: str,
) -> str:
    full_name = _first(identity.get("full_name"), "Candidate")
    title = _first(canonical_context.get("title"), identity.get("title"), "")
    years_label = _first(metrics.get("total_experience_years_label"), "")
    availability = _first(canonical_context.get("availability"), "")

    return "".join(
        [
            f'<p{_slot_attrs("identity.full_name", "identity")} '
            f'style="margin:0 0 2pt 0;font-size:15pt;font-weight:bold;color:#{primary};">{escape(full_name)}</p>',
            f'<p{_slot_attrs("title", "identity")} '
            f'style="margin:0 0 3pt 0;font-size:8.5pt;font-weight:bold;color:#{secondary};">{escape(title)}</p>',
            _small_line(years_label, primary, bold=True, attrs=_slot_attrs("metrics.total_experience_years_label", "identity")),
            _small_line(
                f"Disponibilite : {availability}" if availability else "",
                primary,
                attrs=_slot_attrs("availability", "identity"),
            ),
            '<div style="height:2pt;"></div>',
        ]
    )


def _render_sidebar(
    skills: dict[str, Any],
    education: list[dict[str, Any]],
    certifications: list[dict[str, Any]],
    languages: list[dict[str, Any]],
    primary: str,
    secondary: str,
    muted: str,
    border: str,
) -> str:
    key_skills = [str(item) for item in _list(skills.get("key") or skills.get("technical")) if str(item).strip()]
    domain_skills = [str(item) for item in _list(skills.get("domain")) if str(item).strip()]
    html = [
        _section_title("Competences cles", primary, border),
        _chip_list(key_skills[:10], secondary),
    ]
    if domain_skills:
        html.extend([_section_title("Competences metier", primary, border), _paragraph(", ".join(domain_skills[:8]), muted)])
    html.extend(
        [
            _section_title("Formation", primary, border),
            _education_list(education, muted),
            _section_title("Certifications", primary, border),
            _certification_list(certifications, muted),
            _section_title("Langues", primary, border),
            _language_list(languages, muted),
        ]
    )
    return "".join(html)


def _render_summary(
    canonical_context: dict[str, Any],
    primary: str,
    muted: str,
    *,
    page_break_before: bool = False,
) -> str:
    summary = str(canonical_context.get("summary") or "").strip()
    if not summary:
        return ""
    break_style = "page-break-before: always;" if page_break_before else ""
    return (
        f'<p style="margin:4pt 0 2pt 0;padding-bottom:1pt;border-bottom:1pt solid #A9C9DA;'
        f'font-size:10.2pt;font-weight:bold;text-decoration:underline;color:#{primary};{break_style}">'
        "Synthèse</p>"
    ) + _paragraph(
        summary,
        muted,
        attrs=_slot_attrs("summary", "summary"),
    )


def _render_experiences(
    experiences: list[dict[str, Any]],
    primary: str,
    secondary: str,
    muted: str,
    section_title: str,
    environment_color: str,
    border: str,
) -> str:
    if not experiences:
        return ""
    html: list[str] = []
    for experience in experiences:
        company = _first(experience.get("company_full"), experience.get("company"), "")
        role = _first(experience.get("role"), experience.get("position"), "")
        period = _clean_absis_period_label(_first(experience.get("period_full"), experience.get("period"), ""))
        context = _first(experience.get("context"), experience.get("summary"), "")
        environment = _first(experience.get("environment"), "")
        tasks = _dedupe_strings(_list(experience.get("tasks")))
        project_examples = _dedupe_strings(_list(experience.get("project_examples")))

        html.append(
            '<div data-section="experience" '
            f'{_data_attrs({"data-brain-repeat": "experiences", "data-brain-item": "experience"})} '
            f'style="width:{HTML_MAIN_CONTENT_WIDTH};margin:0 0 32pt 0;page-break-inside:auto;">'
            f'<table role="presentation" style="width:{HTML_MAIN_CONTENT_WIDTH};border-collapse:collapse;'
            f'table-layout:fixed;margin:0 0 3pt 0;border:none;">'
            f'<colgroup><col style="width:{HTML_EXPERIENCE_DETAIL_WIDTH};">'
            f'<col style="width:{HTML_EXPERIENCE_PERIOD_WIDTH};"></colgroup><tr>'
            f'<td{_slot_attrs("experiences[].company_full", "experiences")} '
            f'style="vertical-align:bottom;padding:0 4pt 0 0;font-size:12.2pt;line-height:1.08;'
            f'font-weight:bold;color:#{secondary};">{escape(company)}</td>'
            f'<td{_slot_attrs("experiences[].period_full", "experiences")} '
            f'style="vertical-align:bottom;text-align:right;padding:0;font-size:10.6pt;line-height:1.08;'
            f'font-weight:bold;color:#{secondary};">{escape(period)}</td>'
            "</tr></table>"
            f'<p{_slot_attrs("experiences[].role", "experiences")} '
            f'style="margin:0 0 3pt 0;font-size:10.5pt;line-height:1.12;font-weight:bold;color:#{HTML_ABSIS_ROLE_COLOR};">'
            f"{escape(role)}</p>"
            f"{_label_value('Projet/Contexte', context, muted, attrs=_slot_attrs('experiences[].context', 'experiences'))}"
            f"{_inline_heading('Missions', section_title) if tasks else ''}"
            f"{_bullet_list(tasks, muted, attrs=_data_attrs({'data-brain-repeat': 'experiences[].tasks'}))}"
            f"{_inline_heading('Exemples de projets portés (liste non exhaustive)', section_title) if project_examples else ''}"
            f"{_bullet_list(project_examples, muted, attrs=_data_attrs({'data-brain-repeat': 'experiences[].project_examples'}))}"
            f"{_environment_line(environment, environment_color, attrs=_slot_attrs('experiences[].environment', 'experiences'))}"
            "</div>"
        )
    return "".join(html)


def _render_projects(projects: list[dict[str, Any]], primary: str, muted: str, border: str) -> str:
    if not projects:
        return ""
    html = [_section_title("Projets", primary, border)]
    for project in projects:
        name = str(project.get("name") or "").strip()
        description = str(project.get("description") or "").strip()
        if name:
            html.append(f'<p style="margin:0 0 2pt 0;font-weight:bold;color:#{primary};">{escape(name)}</p>')
        if description:
            html.append(_paragraph(description, muted))
    return "".join(html)


def _education_list(items: list[dict[str, Any]], muted: str) -> str:
    return _line_list(_education_lines(items), muted)


def _certification_list(items: list[dict[str, Any]], muted: str) -> str:
    return _line_list(_certification_lines(items), muted)


def _language_list(items: list[dict[str, Any]], muted: str) -> str:
    return _line_list(_language_lines(items), muted)


def _education_lines(items: list[dict[str, Any]]) -> list[str]:
    lines = []
    for item in items:
        line = " - ".join(
            value
            for value in [
                str(item.get("year") or "").strip(),
                str(item.get("degree") or "").strip(),
                str(item.get("institution") or "").strip(),
            ]
            if value
        )
        if line:
            lines.append(line)
    return lines


def _certification_lines(items: list[dict[str, Any]]) -> list[str]:
    lines = []
    for item in items:
        year = str(item.get("year") or "").strip()
        name = str(item.get("name") or "").strip()
        if name:
            lines.append(f"{year} - {name}" if year else name)
    return lines


def _language_lines(items: list[dict[str, Any]]) -> list[str]:
    lines = []
    for item in items:
        name = str(item.get("name") or "").strip()
        level = str(item.get("level") or "").strip()
        if name:
            lines.append(f"{name} : {level}" if level else name)
    return lines


def _section_title(title: str, color: str, border: str) -> str:
    return (
        f'<p style="margin:4pt 0 2pt 0;padding-bottom:1pt;border-bottom:1pt solid #{border};'
        f'font-size:10.2pt;font-weight:bold;text-decoration:underline;color:#{color};">{escape(title)}</p>'
    )


def _paragraph(text: str, color: str, *, attrs: str = "") -> str:
    if not str(text or "").strip():
        return ""
    return f'<p{attrs} style="margin:0 0 5pt 0;font-size:9.4pt;line-height:1.15;color:#{color};">{escape(str(text).strip())}</p>'


def _small_line(text: str, color: str, *, bold: bool = False, attrs: str = "") -> str:
    if not str(text or "").strip():
        return ""
    weight = "font-weight:bold;" if bold else ""
    return (
        f'<p{attrs} style="margin:0 0 3pt 0;font-size:8.8pt;line-height:1.12;{weight}color:#{color};">'
        f"{escape(str(text).strip())}</p>"
    )


def _label_value(label: str, value: str, color: str, *, attrs: str = "") -> str:
    if not str(value or "").strip():
        return ""
    return (
        f'<p{attrs} style="margin:0 0 4pt 0;font-size:9.2pt;line-height:1.15;color:#{color};">'
        f'<strong>{escape(label)} : </strong>{escape(str(value).strip())}</p>'
    )


def _environment_line(value: str, color: str, *, attrs: str = "") -> str:
    if not str(value or "").strip():
        return ""
    return (
        f'<p{attrs} style="margin:9pt 0 18pt 0;font-size:10pt;line-height:1.12;'
        f'font-style:italic;color:#{color};">Environnement : {escape(str(value).strip())}</p>'
    )


def _bullet_list(items: list[str], color: str, *, attrs: str = "") -> str:
    if not items:
        return ""
    return "".join(
        f'<p{attrs}{_slot_attrs("experiences[].tasks[]", "experiences")} '
        f'style="margin:0 0 2pt 14pt;font-size:9.1pt;line-height:1.14;color:#{color};">• {escape(item)}</p>'
        for item in items
    )


def _chip_list(items: list[str], color: str) -> str:
    if not items:
        return ""
    return "".join(
        f'<p style="margin:0 0 2pt 0;font-size:9.1pt;color:#{color};font-weight:bold;">{escape(item)}</p>'
        for item in items
    )


def _line_list(lines: list[str], color: str) -> str:
    if not lines:
        return ""
    return "".join(
        f'<p style="margin:0 0 2pt 0;font-size:8.8pt;line-height:1.13;color:#{color};">{escape(line)}</p>'
        for line in lines
    )


def _compact_phrase_list(items: list[str], color: str, *, attrs: str = "") -> str:
    clean_items = [str(item).strip() for item in items if str(item).strip()]
    if not clean_items:
        return ""
    rows: list[str] = []
    current = ""
    for item in clean_items:
        candidate = item if not current else f"{current}; {item}"
        if len(candidate) > 260 and current:
            rows.append(current)
            current = item
        else:
            current = candidate
    if current:
        rows.append(current)
    return "".join(
        f'<p{attrs} style="margin:0 0 2pt 0;font-size:8.2pt;line-height:1.08;color:#{color};">'
        f'{escape(row)}</p>'
        for row in rows
    )


def _inline_heading(title: str, color: str, *, attrs: str = "") -> str:
    if not str(title or "").strip():
        return ""
    return (
        f'<p{attrs} style="margin:2pt 0 2pt 0;font-size:9.6pt;line-height:1.1;font-weight:bold;'
        f'text-decoration:underline;color:#{color};">{escape(str(title).strip())}</p>'
    )


def _render_header_footer_html(text: str, html_spec: dict[str, Any]) -> str:
    text = str(text or "").strip()
    if not text:
        return ""
    branding = html_spec.get("branding") or {}
    muted = _hex_color(branding.get("muted_color"), "6F6F6F")
    font_family = _safe_font_family(str(branding.get("font_family") or HTML_DEFAULT_FONT_FAMILY))
    return f'<p style="font-family:{font_family};font-size:8pt;color:#{muted};margin:0;">{escape(text)}</p>'


def _document_options_from_spec(html_spec: dict[str, Any]) -> dict[str, Any]:
    page = html_spec.get("page") or {}
    return {
        "title": str(html_spec.get("template_name") or "Company CV"),
        "creator": "BrainRH",
        "orientation": page.get("orientation") or "portrait",
        "font": HTML_DEFAULT_FONT_FAMILY,
        "fontSize": HTML_DEFAULT_FONT_SIZE_HALF_POINTS,
        "complexScriptFontSize": HTML_DEFAULT_FONT_SIZE_HALF_POINTS,
        "lang": HTML_DEFAULT_LANG,
        "table": {
            "row": {"cantSplit": False},
            "addSpacingAfter": False,
            "borderOptions": {"size": 0, "stroke": "nil", "color": "FFFFFF"},
        },
    }


def _default_converter_script_path() -> Path:
    return Path(__file__).resolve().parents[2] / "tools" / "company_cv_html_renderer" / "html_to_docx.mjs"


def _build_html_binding_matrix(
    *,
    canonical_context: dict[str, Any],
    template_record: dict[str, Any] | None,
) -> dict[str, Any]:
    template_record = template_record or {}
    entries = _base_html_binding_entries()
    template_entries = _template_slot_binding_entries(template_record)
    entries.extend(template_entries)

    covered_template_slots = [
        entry for entry in template_entries if bool(entry.get("covered_by_html"))
    ]
    required_uncovered = [
        str(entry.get("placeholder") or entry.get("slot_id") or entry.get("contract_path") or "")
        for entry in template_entries
        if entry.get("required") and not entry.get("covered_by_html")
    ]
    matrix = {
        "version": HTML_BINDING_MATRIX_VERSION,
        "interface_version": HTML_INTERFACE_VERSION,
        "source": "template_contract_plus_html_interface",
        "template": {
            "id": template_record.get("id"),
            "name": template_record.get("name"),
            "content_hash": template_record.get("content_hash"),
            "contract_version": template_record.get("contract_version"),
        },
        "entries": entries,
        "coverage_summary": {
            "html_slots": len([entry for entry in entries if entry.get("kind") == "html_slot"]),
            "template_slots": len(template_entries),
            "covered_template_slots": len(covered_template_slots),
            "required_uncovered_placeholders": [item for item in required_uncovered if item],
            "sections": _binding_section_counts(entries),
        },
        "data_summary": _binding_data_summary(canonical_context),
    }
    matrix["fingerprint"] = _stable_fingerprint(matrix)
    return matrix


def _base_html_binding_entries() -> list[dict[str, Any]]:
    specs = [
        ("identity.full_name", "identity", True, False, False),
        ("title", "identity", True, False, False),
        ("metrics.source_experience_years_label", "identity", False, False, False),
        ("metrics.total_experience_years_label", "identity", False, False, False),
        ("availability", "identity", False, False, False),
        ("summary", "summary", False, False, False),
        ("skills.key[]", "skills", False, True, True),
        ("skills.technical[]", "skills", False, True, True),
        ("skills.categories", "skills", False, True, True),
        ("skills.domain[]", "skills", False, True, True),
        ("education[].year", "education", False, True, True),
        ("education[].degree", "education", False, True, True),
        ("education[].institution", "education", False, True, True),
        ("certifications[].year", "certifications", False, True, True),
        ("certifications[].name", "certifications", False, True, True),
        ("languages[].name", "languages", False, True, True),
        ("languages[].level", "languages", False, True, True),
        ("experiences[].period_full", "experiences", False, True, True),
        ("experiences[].company_full", "experiences", False, True, True),
        ("experiences[].role", "experiences", False, True, True),
        ("experiences[].context", "experiences", False, True, True),
        ("experiences[].tasks[]", "experiences", False, True, True),
        ("experiences[].environment", "experiences", False, True, True),
        ("extra_sections[].title", "extra_sections", False, True, True),
        ("extra_sections[].items[]", "extra_sections", False, True, True),
    ]
    return [
        {
            "kind": "html_slot",
            "slot_id": slot,
            "placeholder": None,
            "source_path": slot,
            "contract_path": slot,
            "html_section": section,
            "html_slot": slot,
            "required": required,
            "repeatable": repeatable,
            "unbounded": unbounded,
            "covered_by_html": True,
        }
        for slot, section, required, repeatable, unbounded in specs
    ]


def _template_slot_binding_entries(template_record: dict[str, Any]) -> list[dict[str, Any]]:
    slot_definitions = _list(template_record.get("slot_definitions"))
    group_definitions = _dict(template_record.get("group_definitions"))
    entries: list[dict[str, Any]] = []
    for index, slot in enumerate(slot_definitions):
        if not isinstance(slot, dict):
            continue
        source_path = str(slot.get("source_path") or "")
        contract_path = str(slot.get("contract_path") or source_path)
        group = str(slot.get("group") or "")
        html_section = _html_section_for_binding_path(contract_path or source_path, group=group)
        group_definition = _dict(group_definitions.get(group))
        entries.append(
            {
                "kind": "template_slot",
                "slot_id": str(slot.get("slot_id") or slot.get("placeholder") or f"slot_{index + 1}"),
                "placeholder": str(slot.get("placeholder") or ""),
                "source_path": source_path,
                "contract_path": contract_path,
                "transform": str(slot.get("transform") or "identity"),
                "html_section": html_section,
                "html_slot": _canonical_binding_path(contract_path or source_path),
                "required": bool(slot.get("required")),
                "repeatable": bool(group or "[]" in contract_path or "[]" in source_path),
                "unbounded": bool(group_definition.get("unbounded")) or html_section in {
                    "experiences",
                    "education",
                    "certifications",
                    "languages",
                    "projects",
                },
                "covered_by_html": html_section != "unsupported",
            }
        )
    return entries


def _html_section_for_binding_path(path: str, *, group: str = "") -> str:
    group_text = group.strip().casefold()
    if group_text in {"experience", "experiences", "experience_detail_list", "experience_teaser_list"}:
        return "experiences"
    if group_text in {"education", "formation", "formations"}:
        return "education"
    if group_text in {"certification", "certifications"}:
        return "certifications"
    if group_text in {"language", "languages", "langue", "langues"}:
        return "languages"
    if group_text in {"project", "projects", "projet", "projets"}:
        return "projects"

    normalized = _canonical_binding_path(path).casefold()
    if normalized.startswith("identity.") or normalized in {
        "title",
        "availability",
        "metrics.total_experience_years_label",
        "metrics.source_experience_years_label",
    }:
        return "identity"
    if normalized == "summary" or normalized.startswith("summary."):
        return "summary"
    if normalized.startswith("skills."):
        return "skills"
    if normalized.startswith("education[]."):
        return "education"
    if normalized.startswith("certifications[]."):
        return "certifications"
    if normalized.startswith("languages[]."):
        return "languages"
    if normalized.startswith("experiences[]."):
        return "experiences"
    if normalized.startswith("projects[]."):
        return "projects"
    if normalized.startswith("extra_sections[]."):
        return "extra_sections"
    return "unsupported"


def _canonical_binding_path(path: str) -> str:
    clean = str(path or "").strip()
    clean = re.sub(r"\[\d+\]", "[]", clean)
    clean = re.sub(r"\.(\d+)(?=\.|$)", "[]", clean)
    clean = clean.replace("experience_detail_list[].", "experiences[].")
    clean = clean.replace("experience_teaser_list[].", "experiences[].")
    clean = clean.replace("formation_list[].", "education[].")
    clean = clean.replace("certification_list[].", "certifications[].")
    clean = clean.replace("language_list[].", "languages[].")
    clean = clean.replace("project_list[].", "projects[].")
    clean = clean.replace("extra_section_list[].", "extra_sections[].")
    return clean


def _binding_section_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        section = str(entry.get("html_section") or "unsupported")
        counts[section] = counts.get(section, 0) + 1
    return dict(sorted(counts.items()))


def _binding_data_summary(canonical_context: dict[str, Any]) -> dict[str, int]:
    skills = _dict(canonical_context.get("skills"))
    return {
        "experiences": len(_list(canonical_context.get("experiences"))),
        "education": len(_list(canonical_context.get("education"))),
        "certifications": len(_list(canonical_context.get("certifications"))),
        "languages": len(_list(canonical_context.get("languages"))),
        "projects": len(_list(canonical_context.get("projects"))),
        "extra_sections": len(_list(canonical_context.get("extra_sections"))),
        "skills_key": len(_list(skills.get("key") or skills.get("technical"))),
        "skills_technical": len(_list(skills.get("technical"))),
        "skills_domain": len(_list(skills.get("domain"))),
    }


def _stable_fingerprint(payload: dict[str, Any]) -> str:
    clean_payload = deepcopy(payload)
    clean_payload.pop("fingerprint", None)
    return sha256(json.dumps(clean_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _html_metadata_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _slot_attrs(slot: str, section: str) -> str:
    return _data_attrs(
        {
            "data-brain-slot": slot,
            "data-brain-section": section,
        }
    )


def _data_attrs(attrs: dict[str, Any]) -> str:
    return "".join(
        f' {key}="{escape(str(value), quote=True)}"'
        for key, value in attrs.items()
        if value is not None and str(value) != ""
    )


def _normalized_experience_texts(experience: dict[str, Any]) -> set[str]:
    texts = {
        _normalize_text(experience.get("role")),
        _normalize_text(experience.get("position")),
        _normalize_text(experience.get("company")),
        _normalize_text(experience.get("company_full")),
        _normalize_text(experience.get("location")),
        _normalize_text(experience.get("start_date")),
        _normalize_text(experience.get("end_date")),
        _normalize_text(experience.get("duration")),
        _normalize_text(experience.get("period")),
        _normalize_text(experience.get("period_full")),
        _normalize_text(experience.get("context")),
        _normalize_text(experience.get("summary")),
        _normalize_text(experience.get("environment")),
    }
    texts.update(_normalize_text(item) for item in _list(experience.get("tasks")))
    texts.update(_normalize_task_text(item) for item in _list(experience.get("tasks")))
    texts.update(_normalize_text(item) for item in _list(experience.get("project_examples")))
    texts.update(_normalize_task_text(item) for item in _list(experience.get("project_examples")))
    return {text for text in texts if text}


def _coerce_tasks(experience: dict[str, Any]) -> list[Any]:
    tasks = experience.get("tasks")
    if isinstance(tasks, list):
        return tasks
    task = _clean_text(tasks)
    coerced: list[Any] = [task] if task else []
    experience["tasks"] = coerced
    return coerced


def _render_context_values(
    render_context: dict[str, Any],
    *,
    experience_index: int,
    fields: tuple[str, ...],
) -> list[str]:
    matches: list[tuple[int, int, str, str]] = []
    field_order = {field: index for index, field in enumerate(fields)}
    for key, value in render_context.items():
        key_text = str(key)
        for field in fields:
            match = re.fullmatch(rf"exp{experience_index}_{re.escape(field)}(?:_?(\d+))?", key_text)
            if not match:
                continue
            clean_value = _clean_text(value)
            if clean_value:
                suffix = int(match.group(1) or "0")
                matches.append((field_order[field], suffix, key_text, clean_value))

    values: list[str] = []
    seen: set[str] = set()
    for _field_order, _suffix, _key, value in sorted(matches):
        normalized = _normalize_text(value)
        if normalized and normalized not in seen:
            values.append(value)
            seen.add(normalized)
    return values


def _render_context_first(
    render_context: dict[str, Any],
    *,
    experience_index: int,
    fields: tuple[str, ...],
) -> str:
    values = _render_context_values(
        render_context,
        experience_index=experience_index,
        fields=fields,
    )
    return values[0] if values else ""


def _dedupe_strings(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _clean_text(value)
        normalized = clean.casefold()
        if clean and normalized not in seen:
            result.append(clean)
            seen.add(normalized)
    return result


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _first(*values: Any) -> str:
    for value in values:
        text = _clean_text(value)
        if text:
            return text
    return ""


def _hex_color(value: Any, fallback: str) -> str:
    clean = str(value or "").strip().lstrip("#").upper()
    return clean if re.fullmatch(r"[0-9A-F]{6}", clean) else fallback


def _safe_font_family(value: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9 ,._-]+", "", value).strip()
    return clean or "Calibri"


def _clean_text(value: Any) -> str:
    text = unescape(str(value or "").replace("\xa0", " "))
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*=>\s*", "", text)
    text = re.sub(r"</?(?:u|strong|b|em|i|span|p|br)\b[^>]*>", " ", text, flags=re.I)
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"(?<!\w)\*(?=\S)|(?<=\S)\*(?!\w)", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _normalize_text(value: Any) -> str:
    return _clean_text(value).casefold()


def _normalize_skill_text(value: Any) -> str:
    return re.sub(r"[^0-9a-z]+", "", _normalize_text(value), flags=re.I)


def _normalize_task_text(value: Any) -> str:
    return re.sub(r"\W+", "", _normalize_text(value), flags=re.I)


def _slug(value: str) -> str:
    clean = "".join(character if character.isalnum() or character in {"_", "-"} else "_" for character in value.strip())
    return clean.strip("_") or "candidate"


def _int_value(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
