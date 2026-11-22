from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status

from brainrh.database import get_session
from brainrh.schemas.company_cv import (
    CompanyCvCertification,
    CompanyCvContext,
    CompanyCvEducation,
    CompanyCvEnterpriseInfo,
    CompanyCvExperience,
    CompanyCvExtraSection,
    CompanyCvIdentity,
    CompanyCvInterviewSheetInfo,
    CompanyCvLanguage,
    CompanyCvMetrics,
    CompanyCvProject,
    CompanyCvProjectInfo,
    CompanyCvSkills,
)
from brainrh.services.application_service import ApplicationService
from brainrh.services.cv_service import CVService
from brainrh.services.enterprise_service import EnterpriseService
from brainrh.services.interview_sheet_service import InterviewSheetService
from brainrh.services.project_service import ProjectService
from lib.scoring_sections import years_between


SKILL_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "api": ("api", "rest", "soap", "graphql", "microservice"),
    "cloud": ("aws", "azure", "gcp", "terraform", "docker", "kubernetes", "cloud"),
    "data_bi": (
        "data",
        "bi",
        "etl",
        "airflow",
        "spark",
        "hadoop",
        "hive",
        "cassandra",
        "sql",
        "power bi",
        "tableau",
        "analytics",
    ),
    "dev": ("java", "j2ee", "python", "javascript", "typescript", "git", "junit", "jsf"),
    "gestion": ("jira", "confluence", "ms project", "agile", "scrum", "management", "pilotage"),
    "monitoring": ("monitoring", "observability", "grafana", "prometheus", "splunk", "kibana"),
    "paiements": ("payment", "paiement", "iban", "cashback", "swift", "visa", "mastercard"),
}
GENERATION_GUIDANCE_MAX_LENGTH = 4000


def _is_placeholder_email(value: Any) -> bool:
    if value is None:
        return False
    normalized = str(value).strip().lower()
    return normalized.startswith("dummy_") and normalized.endswith("@example.com")


def build_company_cv_context(
    sheet_id: str,
    *,
    generation_guidance: str | None = None,
) -> tuple[CompanyCvContext, dict[str, Any], dict[str, Any], dict[str, Any]]:
    sheet = InterviewSheetService.get(sheet_id)
    if not sheet:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Interview sheet {sheet_id} not found.",
        )

    project = ProjectService.get_project(sheet["job_id"])
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {sheet['job_id']} not found.",
        )

    enterprise_id = project.get("enterprise_id")
    if not enterprise_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Project {sheet['job_id']} has no enterprise_id.",
        )

    enterprise = EnterpriseService.get_enterprise(enterprise_id)
    if not enterprise:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Enterprise {enterprise_id} not found.",
        )

    with get_session() as session:
        candidate_record = ApplicationService.find_project_candidate(
            session,
            sheet["job_id"],
            sheet["candidate_id"],
        )

    cv_data = candidate_record.get("cv_data") if isinstance(candidate_record, dict) else None
    if not cv_data:
        fallback = CVService.get_cv(sheet["job_id"], sheet["candidate_id"])
        cv_data = fallback.get("data") if fallback else None
        if not candidate_record and fallback:
            candidate_record = fallback.get("metadata") or {}

    if not isinstance(cv_data, dict):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Parsed CV data not found for candidate {sheet['candidate_id']}.",
        )

    sheet_data = sheet.get("data", {}) if isinstance(sheet.get("data"), dict) else {}
    identity = _candidate_identity(cv_data, candidate_record or {}, sheet)
    experiences = _experience_items(cv_data)
    education = _education_items(cv_data)
    certifications = _certification_items(cv_data)
    languages = _language_items(cv_data)
    projects = _project_items(cv_data)
    extra_sections = _extra_sections(cv_data)
    technical_skills = _dedupe_preserve_order(
        _string_list(cv_data.get("competences_techniques")) + _tool_skill_items(cv_data)
    )
    soft_skills = _string_list(cv_data.get("competences_transversales"))
    domain_skills = _dedupe_preserve_order(
        _string_list(cv_data.get("competences_metiers"))
        + _string_list(cv_data.get("domaines_intervention"))
        + list(soft_skills)
    )
    categorized_skills = _categorize_skills(technical_skills + soft_skills)
    key_skills = _dedupe_preserve_order(technical_skills + domain_skills)

    stable_generated_at = sheet.get("updated_at") or sheet.get("created_at") or datetime.now(timezone.utc).isoformat()
    stable_generated_date = datetime.fromisoformat(stable_generated_at.replace("Z", "+00:00")).strftime("%d %b %Y")

    total_experience_years = round(
        sum(years_between(item.start_date, item.end_date) for item in experiences),
        1,
    )
    source_experience_years_label = _source_experience_years_label(cv_data)
    display_experience_years_label = source_experience_years_label or _format_years_label(total_experience_years)

    context = CompanyCvContext(
        generation_guidance=_generation_guidance_value(generation_guidance),
        identity=identity,
        title=identity.title,
        summary=_first_non_empty(
            cv_data.get("resume_professionnel"),
            sheet_data.get("resume"),
        ),
        availability=_availability_value(cv_data, sheet_data),
        experiences=experiences,
        education=education,
        certifications=certifications,
        languages=languages,
        skills=CompanyCvSkills(
            technical=technical_skills,
            soft=soft_skills,
            domain=domain_skills,
            key=key_skills,
            categories=categorized_skills,
        ),
        projects=projects,
        extra_sections=extra_sections,
        enterprise=CompanyCvEnterpriseInfo(
            id=enterprise_id,
            name=str(enterprise.get("nom") or ""),
            sector=str(enterprise.get("secteur") or ""),
            notes=str(enterprise.get("notes") or ""),
        ),
        project=CompanyCvProjectInfo(
            id=str(project.get("id") or ""),
            name=str(project.get("nom") or ""),
            department=str(project.get("service_demandeur") or ""),
            manager=str(project.get("responsable_offre") or ""),
            manager_contact=str(project.get("contact_responsable") or ""),
            notes=str(project.get("notes") or ""),
        ),
        interview_sheet=CompanyCvInterviewSheetInfo(
            id=str(sheet.get("id") or ""),
            status=str(sheet.get("status") or ""),
            summary=str(sheet_data.get("resume") or ""),
            strengths=[
                str(item.get("point") or "").strip()
                for item in _as_list(sheet_data.get("strengths"))
                if isinstance(item, dict) and str(item.get("point") or "").strip()
            ],
            concerns=[
                str(item.get("point") or item.get("question") or "").strip()
                for item in _as_list(sheet_data.get("concerns"))
                if isinstance(item, dict) and str(item.get("point") or item.get("question") or "").strip()
            ],
            verdict=str(sheet_data.get("verdict") or ""),
            verdict_detail=str(sheet_data.get("verdict_detail") or ""),
        ),
        metrics=CompanyCvMetrics(
            total_experience_years=total_experience_years,
            total_experience_years_label=display_experience_years_label,
            source_experience_years_label=source_experience_years_label,
        ),
        generated_at=stable_generated_at,
        generated_date=stable_generated_date,
    )
    return context, sheet, project, enterprise


def _generation_guidance_value(value: str | None) -> str:
    normalized = " ".join(str(value or "").replace("\xa0", " ").split())
    if len(normalized) <= GENERATION_GUIDANCE_MAX_LENGTH:
        return normalized
    return normalized[:GENERATION_GUIDANCE_MAX_LENGTH].rsplit(" ", 1)[0].strip()


def _candidate_identity(cv_data: dict[str, Any], candidate_record: dict[str, Any], sheet: dict[str, Any]) -> CompanyCvIdentity:
    identite = cv_data.get("identite") if isinstance(cv_data.get("identite"), dict) else {}
    legacy_identite = (
        cv_data.get("informations_personnelles")
        if isinstance(cv_data.get("informations_personnelles"), dict)
        else {}
    )
    sheet_identite = sheet.get("data", {}).get("identite", {}) if isinstance(sheet.get("data"), dict) else {}

    candidate_email = candidate_record.get("email")
    if _is_placeholder_email(candidate_email):
        candidate_email = ""

    first_name = _first_non_empty(
        identite.get("prenom"),
        legacy_identite.get("prenom"),
        candidate_record.get("first_name"),
    )
    last_name = _first_non_empty(
        identite.get("nom"),
        legacy_identite.get("nom"),
        candidate_record.get("last_name"),
    )
    full_name = _first_non_empty(
        identite.get("nom_complet"),
        legacy_identite.get("nom_complet"),
        sheet_identite.get("nom_complet"),
        " ".join(part for part in [first_name, last_name] if part).strip(),
    )

    return CompanyCvIdentity(
        full_name=full_name,
        first_name=first_name,
        last_name=last_name,
        email=_first_non_empty(
            identite.get("email"),
            legacy_identite.get("email"),
            sheet_identite.get("email"),
            candidate_email,
        ),
        phone=_first_non_empty(
            identite.get("telephone"),
            legacy_identite.get("telephone"),
            candidate_record.get("phone"),
        ),
        location=_first_non_empty(identite.get("adresse"), legacy_identite.get("adresse")),
        linkedin=_first_non_empty(
            identite.get("linkedin"),
            identite.get("linkedIn"),
            legacy_identite.get("linkedin"),
            cv_data.get("linkedin"),
        ),
        title=_first_non_empty(cv_data.get("titre"), legacy_identite.get("titre")),
        source_filename=_first_non_empty(
            candidate_record.get("filename"),
            cv_data.get("cv"),
            sheet.get("candidate_id"),
        ),
        source_display_name=_first_non_empty(
            identite.get("nom_complet"),
            legacy_identite.get("nom_complet"),
            candidate_record.get("filename"),
            sheet.get("candidate_id"),
        ),
    )


def _experience_items(cv_data: dict[str, Any]) -> list[CompanyCvExperience]:
    experiences = _as_list(
        cv_data.get("experiences_professionnelles")
        or cv_data.get("experience")
    )

    normalized: list[CompanyCvExperience] = []
    for item in experiences:
        if not isinstance(item, dict):
            text = str(item).strip()
            normalized.append(
                CompanyCvExperience(
                    summary=text,
                    context=text,
                )
            )
            continue

        start_date = _first_non_empty(item.get("date_debut"), item.get("start_date"))
        end_date = _first_non_empty(item.get("date_fin"), item.get("end_date"))
        duration = _first_non_empty(item.get("duree"), item.get("durée"), item.get("duration"))
        summary = _first_non_empty(item.get("description"), item.get("summary"), item.get("texte"))
        tasks = _normalize_tasks(item.get("missions"), summary)
        context = _first_non_empty(item.get("contexte"), item.get("context"), summary, tasks[0] if tasks else "")
        environment = _first_non_empty(
            item.get("environnement_technique"),
            item.get("environment"),
            item.get("stack"),
            ", ".join(_string_list(item.get("technologies"))),
        )
        period = _first_non_empty(duration, _format_period(start_date, end_date))
        period_full = _format_period_full(start_date, end_date, duration)
        highlights = tasks[:3]
        key_points = tasks[:1]

        position = _first_non_empty(item.get("poste"), item.get("position"), item.get("role"))
        normalized.append(
            CompanyCvExperience(
                position=position,
                role=_first_non_empty(item.get("role"), position),
                company=_first_non_empty(item.get("entreprise"), item.get("company")),
                company_full=_first_non_empty(item.get("entreprise_full"), item.get("entreprise"), item.get("company")),
                location=_first_non_empty(item.get("lieu"), item.get("location")),
                start_date=start_date,
                end_date=end_date,
                duration=duration,
                period=period,
                period_full=period_full,
                summary=summary,
                context=context,
                environment=environment,
                tasks=tasks,
                highlights=highlights,
                key_points=key_points,
            )
        )
    return normalized


def _education_items(cv_data: dict[str, Any]) -> list[CompanyCvEducation]:
    items = []
    for item in _as_list(cv_data.get("formations")):
        if isinstance(item, dict):
            year = _first_non_empty(item.get("annee_obtention"), item.get("annee"), item.get("date_fin"), item.get("end_date"))
            items.append(
                CompanyCvEducation(
                    degree=_first_non_empty(item.get("diplome"), item.get("degree"), item.get("titre")),
                    institution=_first_non_empty(item.get("etablissement"), item.get("institution"), item.get("ecole")),
                    field=_first_non_empty(item.get("domaine"), item.get("field"), item.get("specialite")),
                    start_date=_first_non_empty(item.get("date_debut"), item.get("start_date")),
                    end_date=_first_non_empty(item.get("date_fin"), item.get("end_date")),
                    year=year,
                    description=_first_non_empty(item.get("description")),
                )
            )
        else:
            items.append(CompanyCvEducation(degree=str(item).strip()))
    return items


def _certification_items(cv_data: dict[str, Any]) -> list[CompanyCvCertification]:
    items = []
    for item in _as_list(cv_data.get("certifications")):
        if isinstance(item, dict):
            items.append(
                CompanyCvCertification(
                    name=_first_non_empty(item.get("name"), item.get("titre"), item.get("nom")),
                    issuer=_first_non_empty(item.get("issuer"), item.get("organisme")),
                    year=_first_non_empty(item.get("date"), item.get("annee")),
                    link=_first_non_empty(item.get("link"), item.get("lien"), item.get("url")),
                )
            )
        else:
            items.append(CompanyCvCertification(name=str(item).strip()))
    return items


def _language_items(cv_data: dict[str, Any]) -> list[CompanyCvLanguage]:
    items = []
    for item in _as_list(cv_data.get("langues")):
        if isinstance(item, dict):
            items.append(
                CompanyCvLanguage(
                    name=_first_non_empty(item.get("name"), item.get("langue")),
                    level=_first_non_empty(item.get("level"), item.get("niveau")),
                )
            )
        else:
            items.append(CompanyCvLanguage(name=str(item).strip()))
    return items


def _project_items(cv_data: dict[str, Any]) -> list[CompanyCvProject]:
    items = []
    for item in _as_list(cv_data.get("projets")):
        if isinstance(item, dict):
            items.append(
                CompanyCvProject(
                    name=_first_non_empty(item.get("name"), item.get("titre")),
                    description=_first_non_empty(item.get("description"), item.get("summary"), item.get("texte")),
                    role=_first_non_empty(item.get("role"), item.get("poste")),
                    technologies=_string_list(item.get("technologies")),
                )
            )
        else:
            items.append(CompanyCvProject(name=str(item).strip()))
    return items


def _availability_value(cv_data: dict[str, Any], sheet_data: dict[str, Any]) -> str:
    mobilite = cv_data.get("mobilite") if isinstance(cv_data.get("mobilite"), dict) else {}
    return _first_non_empty(
        cv_data.get("disponibilite"),
        cv_data.get("availability"),
        mobilite.get("disponibilite"),
        mobilite.get("disponibilite_geographique"),
        mobilite.get("availability"),
        sheet_data.get("availability"),
    )


def _tool_skill_items(cv_data: dict[str, Any]) -> list[str]:
    keys = {
        "outils",
        "outil",
        "outils_informatiques",
        "outil_informatique",
        "logiciels",
        "logiciel",
        "technologies",
        "environnements_techniques",
        "environnement_technique",
    }
    values: list[str] = []
    for key, value in _walk_key_values(cv_data):
        normalized_key = _normalize_key(key)
        if normalized_key in keys or (
            "outil" in normalized_key and "informatique" in normalized_key
        ):
            values.extend(_string_list(value))
    return _dedupe_preserve_order(values)


def _extra_sections(cv_data: dict[str, Any]) -> list[CompanyCvExtraSection]:
    section_keys = {
        "activites_extra_professionnelles": "Activités extra-professionnelles",
        "activites_extraprofessionnelles": "Activités extra-professionnelles",
        "activites": "Activités extra-professionnelles",
        "engagements": "Engagements",
        "loisirs": "Loisirs",
        "centres_interet": "Centres d'intérêt",
        "interets": "Centres d'intérêt",
    }
    sections: list[CompanyCvExtraSection] = []
    seen_titles: set[str] = set()

    for key, value in _walk_key_values(cv_data):
        normalized_key = _normalize_key(key)
        title = section_keys.get(normalized_key)
        if not title:
            continue
        items = _string_list(value)
        if not items:
            continue
        title_key = title.casefold()
        if title_key in seen_titles:
            for section in sections:
                if section.title.casefold() == title_key:
                    section.items = _dedupe_preserve_order(section.items + items)
                    break
            continue
        sections.append(CompanyCvExtraSection(title=title, items=_dedupe_preserve_order(items)))
        seen_titles.add(title_key)

    autres = cv_data.get("autres")
    if isinstance(autres, dict):
        for key, value in autres.items():
            normalized_key = _normalize_key(str(key))
            title = section_keys.get(normalized_key)
            if title:
                items = _string_list(value)
            else:
                label = str(key).strip().replace("_", " ")
                title = label[:1].upper() + label[1:] if label else "Autres"
                items = _string_list(value)
            if items:
                sections.append(CompanyCvExtraSection(title=title, items=_dedupe_preserve_order(items)))

    deduped: list[CompanyCvExtraSection] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for section in sections:
        key = (section.title.casefold(), tuple(item.casefold() for item in section.items))
        if key not in seen:
            deduped.append(section)
            seen.add(key)
    return deduped


def _categorize_skills(skills: list[str]) -> dict[str, list[str]]:
    categorized: dict[str, list[str]] = {key: [] for key in SKILL_CATEGORY_KEYWORDS}
    for skill in _dedupe_preserve_order(skills):
        normalized_skill = skill.lower()
        for category, keywords in SKILL_CATEGORY_KEYWORDS.items():
            if any(keyword in normalized_skill for keyword in keywords):
                categorized[category].append(skill)
    return categorized


def _normalize_tasks(raw_tasks: Any, summary: str) -> list[str]:
    tasks = _string_list(raw_tasks)
    if tasks:
        return tasks
    if not summary:
        return []
    parts = re.split(r"[;\n]+|(?<=[.!?])\s+", summary)
    return [part.strip(" -") for part in parts if part.strip(" -")]


def _format_period(start_date: str, end_date: str) -> str:
    values = [value for value in [start_date.strip(), end_date.strip()] if value] if start_date or end_date else []
    return " - ".join(values)


def _format_period_full(start_date: str, end_date: str, duration: str) -> str:
    period = _format_period(start_date, end_date)
    if period and duration:
        return f"{period} ({duration})"
    return period or duration


def _format_years_label(total_experience_years: float) -> str:
    if total_experience_years <= 0:
        return ""
    rounded_years = int(round(total_experience_years))
    unit = "année" if rounded_years == 1 else "années"
    return f"{rounded_years} {unit} d’expérience"


def _source_experience_years_label(cv_data: dict[str, Any]) -> str:
    for key in (
        "annees_experience",
        "années_experience",
        "annees_exp",
        "experience_totale",
        "total_experience",
        "total_experience_years_label",
        "seniority",
    ):
        value = cv_data.get(key)
        label = _coerce_experience_years_label(value)
        if label:
            return label

    metrics = cv_data.get("metrics")
    if isinstance(metrics, dict):
        for key in ("total_experience_years_label", "source_experience_years_label", "annees_exp"):
            label = _coerce_experience_years_label(metrics.get(key))
            if label:
                return label
    return ""


def _coerce_experience_years_label(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, (int, float)):
        years = int(round(float(value)))
        unit = "année" if years == 1 else "années"
        return f"{years} {unit} d’expérience"
    text = str(value).strip()
    if not text:
        return ""
    if re.search(r"exp[ée]rience", text, flags=re.I) and re.search(r"\d", text):
        return text
    match = re.fullmatch(r"(\d+(?:[,.]\d+)?)\s*(?:ans?|ann[ée]es?)?", text, flags=re.I)
    if match:
        raw_years = match.group(1).replace(",", ".")
        years = int(round(float(raw_years)))
        unit = "année" if years == 1 else "années"
        return f"{years} {unit} d’expérience"
    return ""


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if value in (None, ""):
        return []
    return [value]


def _string_list(value: Any) -> list[str]:
    return [str(item).strip() for item in _as_list(value) if str(item).strip()]


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(value.strip())
    return normalized


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _walk_key_values(value: Any) -> list[tuple[str, Any]]:
    pairs: list[tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            pairs.append((str(key), item))
            if isinstance(item, dict):
                pairs.extend(_walk_key_values(item))
    return pairs


def _normalize_key(value: str) -> str:
    normalized = value.strip().casefold()
    normalized = (
        normalized.replace("é", "e")
        .replace("è", "e")
        .replace("ê", "e")
        .replace("à", "a")
        .replace("ç", "c")
        .replace("-", "_")
        .replace(" ", "_")
    )
    return re.sub(r"[^a-z0-9_]+", "", normalized)
