from __future__ import annotations

from pathlib import Path
from typing import Any

from docx import Document as WordDocument
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor


def build_code_driven_render_snapshot(
    *,
    canonical_context: dict[str, Any],
    layout_spec: dict[str, Any],
) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "mode": "code_driven",
        "nom": _identity_value(canonical_context, "full_name"),
        "titre": str(canonical_context.get("title") or _identity_value(canonical_context, "title") or ""),
        "disponibilite": str(canonical_context.get("availability") or ""),
        "annees_exp": _metrics_years(canonical_context),
    }

    experiences = _experience_items(canonical_context)
    for index, experience in enumerate(experiences[:3], start=1):
        snapshot[f"exp{index}_periode"] = _compact_period_label(str(experience.get("period_full") or experience.get("period") or ""))
        snapshot[f"exp{index}_poste"] = _suffix_if_present(str(experience.get("role") or experience.get("position") or ""), " – ")
        snapshot[f"exp{index}_entreprise"] = str(experience.get("company_full") or experience.get("company") or "")

    education_items = _list_items(canonical_context.get("education"))
    education = education_items[0] if education_items else None
    if education:
        degree = str(education.get("degree") or "")
        institution = str(education.get("institution") or "")
        snapshot["formation_annee"] = str(education.get("year") or "")
        snapshot["formation_diplome"] = _suffix_if_present(degree, " – ") if institution else degree
        snapshot["formation_etablissement"] = institution

    languages = _list_items(canonical_context.get("languages"))
    if languages:
        snapshot["langue_1"] = str(languages[0].get("name") or "")
        snapshot["langue_1_niveau"] = str(languages[0].get("level") or "")

    return snapshot


def render_code_driven_docx(
    *,
    template_path: Path,
    output_path: Path,
    canonical_context: dict[str, Any],
    layout_spec: dict[str, Any],
) -> None:
    document = WordDocument(str(template_path))
    _clear_document_body(document)
    palette = _style_palette(layout_spec)
    sections = (layout_spec or {}).get("sections") or {}

    _add_identity_block(document, canonical_context, palette)
    _add_first_page_compact_sections(document, canonical_context, sections, palette)
    _add_experience_body(document, canonical_context, sections, palette)
    _add_collection_body(document, canonical_context, sections, palette)
    document.save(str(output_path))


def _clear_document_body(document: WordDocument) -> None:
    body = document._element.body
    sect_pr = None
    for child in list(body):
        if child.tag.endswith("}sectPr"):
            sect_pr = child
        body.remove(child)
    if sect_pr is not None:
        body.append(sect_pr)


def _style_palette(layout_spec: dict[str, Any]) -> dict[str, Any]:
    branding = (layout_spec or {}).get("branding") or {}
    return {
        "font_family": str(branding.get("font_family") or "Aptos"),
        "primary_color": _color_value(branding.get("primary_color"), fallback="004161"),
        "secondary_color": _color_value(branding.get("secondary_color"), fallback="3DAAD6"),
        "muted_color": _color_value("6B7280", fallback="6B7280"),
    }


def _add_identity_block(document: WordDocument, canonical_context: dict[str, Any], palette: dict[str, Any]) -> None:
    identity = canonical_context.get("identity") or {}
    full_name = str(identity.get("full_name") or "")
    title = str(canonical_context.get("title") or identity.get("title") or "")
    availability = str(canonical_context.get("availability") or "")
    years = _metrics_years(canonical_context)

    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(2)
    run = paragraph.add_run(full_name)
    _apply_run_style(run, palette, font_size=28, bold=True, color_key="primary_color")

    title_paragraph = document.add_paragraph()
    title_paragraph.paragraph_format.space_after = Pt(8)
    title_run = title_paragraph.add_run(title)
    _apply_run_style(title_run, palette, font_size=19, bold=True, color_key="secondary_color")

    meta_paragraph = document.add_paragraph()
    meta_paragraph.paragraph_format.space_after = Pt(6)
    if years:
        years_run = meta_paragraph.add_run(f"{years} années d’expérience")
        _apply_run_style(years_run, palette, font_size=11, bold=True, color_key="primary_color")
    if availability:
        availability_run = meta_paragraph.add_run(f"    Disponibilité : {availability}")
        _apply_run_style(availability_run, palette, font_size=11, bold=True, italic=True, color_key="primary_color")


def _add_first_page_compact_sections(
    document: WordDocument,
    canonical_context: dict[str, Any],
    sections: dict[str, Any],
    palette: dict[str, Any],
) -> None:
    experiences = _experience_items(canonical_context)
    teaser = sections.get("cv.first_page_teaser_experiences")
    if teaser:
        _add_section_heading(document, "Expériences clés", palette)
        teaser_table = document.add_table(rows=0, cols=2)
        _set_table_style_if_exists(teaser_table, "Table Grid")
        max_items = int(teaser.get("max_items") or 3)
        for experience in experiences[:max_items]:
            row = teaser_table.add_row().cells
            period = _compact_period_label(str(experience.get("period_full") or experience.get("period") or ""))
            role = str(experience.get("role") or experience.get("position") or "")
            company = str(experience.get("company_full") or experience.get("company") or "")
            row[0].text = period
            row[1].text = role + (f" – {company}" if company else "")
        document.add_paragraph()

    if sections.get("cv.key_skills_list"):
        _add_section_heading(document, "Compétences Clés", palette)
        skills = _list_items((canonical_context.get("skills") or {}).get("key"))
        _add_bullet_list(document, [str(item) for item in skills[:10]], palette)

    if sections.get("cv.domain_skills_block"):
        values = _list_items((canonical_context.get("skills") or {}).get("domain"))
        values = [str(value) for value in values if str(value).strip()]
        if values:
            _add_section_heading(document, "Compétences Métiers", palette)
            _add_body_paragraph(document, ", ".join(values[:8]), palette)

    if sections.get("cv.technical_skills_block"):
        categories = ((canonical_context.get("skills") or {}).get("categories") or {})
        non_empty_categories = [
            ("Data / BI", _list_items(categories.get("data_bi"))),
            ("Développement", _list_items(categories.get("dev"))),
            ("Cloud", _list_items(categories.get("cloud"))),
            ("Gestion", _list_items(categories.get("gestion"))),
            ("Monitoring", _list_items(categories.get("monitoring"))),
            ("API", _list_items(categories.get("api"))),
            ("Paiements", _list_items(categories.get("paiements"))),
        ]
        non_empty_categories = [(label, [str(v) for v in values if str(v).strip()]) for label, values in non_empty_categories]
        non_empty_categories = [(label, values) for label, values in non_empty_categories if values]
        if non_empty_categories:
            _add_section_heading(document, "Compétences Techniques", palette)
            for label, values in non_empty_categories:
                paragraph = document.add_paragraph()
                label_run = paragraph.add_run(f"{label} : ")
                _apply_run_style(label_run, palette, font_size=10.5, bold=True, color_key="primary_color")
                value_run = paragraph.add_run(", ".join(values))
                _apply_run_style(value_run, palette, font_size=10.5, color_key="muted_color")

    has_education = sections.get("cv.education_list")
    has_certifications = sections.get("cv.certification_list")
    has_languages = sections.get("cv.language_list")
    if has_education or has_certifications or has_languages:
        info_table = document.add_table(rows=1, cols=2)
        left_cell, right_cell = info_table.rows[0].cells
        left_cell.text = ""
        right_cell.text = ""

        if has_education or has_certifications:
            _append_cell_heading(left_cell, "Formation/Certification", palette)
            for education in _list_items(canonical_context.get("education")):
                year = str(education.get("year") or "")
                degree = str(education.get("degree") or "")
                institution = str(education.get("institution") or "")
                line = " ".join(value for value in [year, "–" if year and (degree or institution) else "", degree, "–" if degree and institution else "", institution] if value)
                _append_cell_paragraph(left_cell, line, palette)
            certifications = _list_items(canonical_context.get("certifications"))
            if certifications:
                _append_cell_heading(left_cell, "Certifications", palette, font_size=11)
                for certification in certifications:
                    year = str(certification.get("year") or "")
                    name = str(certification.get("name") or "")
                    line = f"{year} – {name}" if year else name
                    _append_cell_paragraph(left_cell, line, palette)

        if has_languages:
            _append_cell_heading(right_cell, "Langues", palette)
            for language in _list_items(canonical_context.get("languages")):
                name = str(language.get("name") or "")
                level = str(language.get("level") or "")
                line = f"{name} : {level}" if level else name
                _append_cell_paragraph(right_cell, line, palette)


def _add_experience_body(
    document: WordDocument,
    canonical_context: dict[str, Any],
    sections: dict[str, Any],
    palette: dict[str, Any],
) -> None:
    if "cv.experience_detail_list" not in sections:
        return
    for experience in _experience_items(canonical_context):
        company = str(experience.get("company_full") or experience.get("company") or "")
        period = str(experience.get("period_full") or experience.get("period") or "")
        role = str(experience.get("role") or experience.get("position") or "")
        context = str(experience.get("context") or experience.get("summary") or "")
        tasks = [str(item) for item in _list_items(experience.get("tasks")) if str(item).strip()]

        if company or period:
            heading = document.add_paragraph()
            company_run = heading.add_run(company)
            _apply_run_style(company_run, palette, font_size=18, bold=True, color_key="secondary_color")
            if period:
                period_run = heading.add_run(f"    {period}")
                _apply_run_style(period_run, palette, font_size=17, bold=True, color_key="secondary_color")

        if role:
            role_paragraph = document.add_paragraph()
            role_run = role_paragraph.add_run(role)
            _apply_run_style(role_run, palette, font_size=13, bold=True, color_key="primary_color")

        if context:
            context_paragraph = document.add_paragraph()
            label_run = context_paragraph.add_run("Projet/Contexte : ")
            _apply_run_style(label_run, palette, font_size=11, bold=True, color_key="primary_color")
            value_run = context_paragraph.add_run(context)
            _apply_run_style(value_run, palette, font_size=11, color_key="muted_color")

        if tasks:
            _add_bullet_list(document, tasks, palette)


def _add_collection_body(
    document: WordDocument,
    canonical_context: dict[str, Any],
    sections: dict[str, Any],
    palette: dict[str, Any],
) -> None:
    if "cv.project_list" in sections:
        projects = _list_items(canonical_context.get("projects"))
        if projects:
            _add_section_heading(document, "Projets", palette)
            for project in projects:
                name = str(project.get("name") or "")
                description = str(project.get("description") or "")
                if name:
                    heading = document.add_paragraph()
                    run = heading.add_run(name)
                    _apply_run_style(run, palette, font_size=13, bold=True, color_key="primary_color")
                if description:
                    _add_body_paragraph(document, description, palette)


def _add_section_heading(document: WordDocument, title: str, palette: dict[str, Any]) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(8)
    paragraph.paragraph_format.space_after = Pt(3)
    run = paragraph.add_run(title)
    _apply_run_style(run, palette, font_size=15, bold=True, color_key="primary_color")


def _add_body_paragraph(document: WordDocument, text: str, palette: dict[str, Any]) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_after = Pt(2)
    run = paragraph.add_run(text)
    _apply_run_style(run, palette, font_size=10.5, color_key="muted_color")


def _add_bullet_list(document: WordDocument, items: list[str], palette: dict[str, Any]) -> None:
    for item in items:
        paragraph = document.add_paragraph(style=_paragraph_style_if_exists(document, "List Bullet"))
        paragraph.paragraph_format.space_after = Pt(0.5)
        run = paragraph.add_run(item if paragraph.style and getattr(paragraph.style, "name", "") == "List Bullet" else f"• {item}")
        _apply_run_style(run, palette, font_size=10.5, color_key="muted_color")


def _append_cell_heading(cell, title: str, palette: dict[str, Any], *, font_size: int = 12) -> None:
    paragraph = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
    if paragraph.text:
        paragraph = cell.add_paragraph()
    run = paragraph.add_run(title)
    _apply_run_style(run, palette, font_size=font_size, bold=True, color_key="primary_color")


def _append_cell_paragraph(cell, text: str, palette: dict[str, Any]) -> None:
    if not text.strip():
        return
    paragraph = cell.add_paragraph()
    run = paragraph.add_run(text)
    _apply_run_style(run, palette, font_size=10.5, color_key="muted_color")


def _apply_run_style(
    run,
    palette: dict[str, Any],
    *,
    font_size: float,
    bold: bool = False,
    italic: bool = False,
    color_key: str = "primary_color",
) -> None:
    font = run.font
    font.name = str(palette.get("font_family") or "Aptos")
    font.size = Pt(font_size)
    font.bold = bold
    font.italic = italic
    font.color.rgb = _rgb_color(str(palette.get(color_key) or "004161"))


def _rgb_color(hex_value: str) -> RGBColor:
    clean = str(hex_value or "004161").strip().lstrip("#")
    if len(clean) != 6:
        clean = "004161"
    return RGBColor(int(clean[0:2], 16), int(clean[2:4], 16), int(clean[4:6], 16))


def _color_value(value: Any, *, fallback: str) -> str:
    clean = str(value or "").strip().lstrip("#")
    return clean if len(clean) == 6 else fallback


def _experience_items(canonical_context: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in _list_items(canonical_context.get("experiences")) if isinstance(item, dict)]


def _metrics_years(canonical_context: dict[str, Any]) -> str:
    metrics = canonical_context.get("metrics") or {}
    value = metrics.get("total_experience_years")
    if isinstance(value, (int, float)) and value:
        return str(int(round(float(value))))
    return ""


def _identity_value(canonical_context: dict[str, Any], key: str) -> str:
    identity = canonical_context.get("identity") or {}
    return str(identity.get(key) or "")


def _list_items(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_list_item(value: Any) -> dict[str, Any] | None:
    items = _list_items(value)
    for item in items:
        if isinstance(item, dict):
            return item
    return None


def _compact_period_label(value: str) -> str:
    return str(value or "").replace("Poste actuel", "Actuel").strip()


def _suffix_if_present(value: str, suffix: str) -> str:
    value = str(value or "").strip()
    return f"{value}{suffix}" if value else ""


def _paragraph_style_if_exists(document: WordDocument, style_name: str) -> str | None:
    try:
        document.styles[style_name]
    except KeyError:
        return None
    return style_name


def _set_table_style_if_exists(table, style_name: str) -> None:
    try:
        table.style = style_name
    except KeyError:
        return
