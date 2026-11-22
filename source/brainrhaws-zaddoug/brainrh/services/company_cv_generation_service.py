from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any

from openai import OpenAI
from fastapi import HTTPException, status

from brainrh.settings import is_company_cv_trace_enabled
from brainrh.services.company_cv_context_builder import build_company_cv_context
from brainrh.services.company_cv_mapping_service import COMPANY_CV_MAPPER_VERSION, build_render_context
from brainrh.services.company_cv_template_service import CompanyCvTemplateService
from brainrh.services.cv_service import CVService
from brainrh.services.file_storage import FileStorage
from brainrh.services.llm_settings_service import get_chat_client_for_process
from lib.cv_parsing import extract_text_from_file


CV_GENERATION_ROOTS = {
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
}
EXPERIENCE_BLOCK_LABEL_PATTERN = re.compile(
    r"^(?:projet/contexte|contexte|missions?|architecture métier et fonctionnelle|architecture data|architecture applicative et solution|outils et frameworks utilisés|environnement(?: technique)?)\s*[:：-]?\s*",
    flags=re.I,
)
EXPERIENCE_DETAIL_MARKER_PATTERN = re.compile(
    r"^(?:projet/contexte|contexte|missions?|réalisations?|responsabilités?|activités?|projets?|exemples de projets|architecture métier et fonctionnelle|architecture data|architecture applicative et solution|outils et frameworks utilisés|environnement(?: technique)?)\s*[:：-]?\s*",
    flags=re.I,
)
EXPERIENCE_BULLET_PREFIX_PATTERN = re.compile(r"^[•✓▪●◦\-\u2022]+\s*")
GLOBAL_CV_SECTION_HEADING_PATTERN = re.compile(
    r"^(?:disponibilit[eé]\b|comp[eé]tences(?:\s+(?:m[eé]tiers|techniques))?\b|formations?(?:\s*/\s*certifications?)?\b|certifications?\b|langues?\b)\s*(?::.*)?$",
    flags=re.I,
)
EXPERIENCE_FOOTER_NOISE_PATTERN = re.compile(
    r"(?:\bcedex\b|\brcs\b|\bsiret\b|\bsas\s+au\s+capital\b|\bsa\s+au\s+capital\b|\bsi[eè]ge\s+social\b)",
    flags=re.I,
)
EXPERIENCE_PROJECT_EXAMPLE_PATTERN = re.compile(
    r"\bpaiement\s+instantan[ée]\b|\bfraude\b|\blcb\b|\bccp\b|\bdatahub\b|\bsrb\b|\bsas\s+viya\b|\breporting\b",
    flags=re.I,
)
EXPERIENCE_PILOTAGE_LINE_PATTERN = re.compile(r"\bpilotage\b", flags=re.I)
EXPERIENCE_PILOTAGE_GOVERNANCE_PATTERN = re.compile(
    r"\bpilotage\b|\bcomit[ée]\s+de\s+direction\b|\bgouvernance\b",
    flags=re.I,
)
EXPERIENCE_REPRESENTATIVE_LINE_PATTERNS = (
    (re.compile(r"\bstrat[ée]gie\s+data\b", flags=re.I), 100),
    (re.compile(r"\bcadre\s+de\s+r[ée]f[ée]rence\b", flags=re.I), 95),
    (re.compile(r"\bdocuments?\s+d[’']architecture\b|\bdossiers?\s+d[’']architecture\b", flags=re.I), 90),
    (EXPERIENCE_PILOTAGE_GOVERNANCE_PATTERN, 85),
    (re.compile(r"\barchitectures?\s+(?:fonctionnelles?|applicatives?|si)\b", flags=re.I), 80),
    (re.compile(r"\bdata\s*centric\b|\bsdsi\b", flags=re.I), 75),
    (EXPERIENCE_PROJECT_EXAMPLE_PATTERN, 70),
)
EXPERIENCE_LABEL_ONLY_PATTERN = re.compile(
    r"^(?:exemples?\s+de\s+projets?.*|certifications?)\s*[:：]?\s*$",
    flags=re.I,
)
CONTRACT_VERSION = "company_cv_template_contract.v1"
SEMANTIC_BLOCK_VERSION = "company_cv_semantic_blocks.v1"
FILENAME_LIKE_PATTERN = re.compile(r".+\.(?:json|pdf|docx?)$", re.IGNORECASE)
GENERIC_LOCATION_VALUES = {
    "city , state",
    "city, state",
    "city state",
    "city ,state",
}
LANGUAGE_LEVEL_PATTERN = re.compile(
    r"\b("
    r"Bilingual|Bilingue|"
    r"Fluent|Courant|"
    r"Native|Natif(?:ve)?|"
    r"Professional|Professionnel(?:le)?|"
    r"Intermediate|Interm[ée]diaire|"
    r"Basic|Notions?"
    r")\b",
    flags=re.I,
)
DIRECT_PLACEHOLDER_OVERRIDE_PATTERNS = (
    re.compile(r"^exp\d+_contexte$"),
    re.compile(r"^exp\d+_entreprise_full$"),
    re.compile(r"^exp\d+_role$"),
    re.compile(r"^exp\d+_periode_full$"),
    re.compile(r"^exp\d+_tache\d+$"),
    re.compile(r"^exp\d+_axe\d+$"),
    re.compile(r"^exp\d+_point_cle$"),
    re.compile(r"^exp\d+_env_tech(?:_\d+)?$"),
    re.compile(r"^competence_cle_\d+$"),
    re.compile(r"^tech_[a-z_]+(?:_\d+)?$"),
    re.compile(r"^langue_\d+$"),
    re.compile(r"^langue_\d+_niveau$"),
    re.compile(r"^formation_(annee|diplome|etablissement)$"),
    re.compile(r"^competences_metiers$"),
    re.compile(r"^annees_exp$"),
)
CANONICAL_BACKFILL_BLOCKLIST = {
    "identity.full_name",
    "experiences[].context",
    "experiences[].highlights[]",
    "experiences[].key_points[]",
}
GUIDANCE_EXPERIENCE_FILTER_VERSION = "generation_guidance_experience_filter.v1"
GUIDANCE_EXCLUSION_STOPWORDS = {
    "a",
    "au",
    "aux",
    "avec",
    "ce",
    "chez",
    "cv",
    "d",
    "dans",
    "de",
    "des",
    "document",
    "du",
    "en",
    "et",
    "experience",
    "l",
    "la",
    "le",
    "les",
    "mission",
    "modele",
    "poste",
    "profil",
    "rendu",
    "sur",
    "template",
    "un",
    "une",
}


def generate_company_cv_contract_payload(
    *,
    sheet_id: str,
    template: dict[str, Any],
    generation_guidance: str | None = None,
) -> dict[str, Any]:
    contract_version = template.get("contract_version")
    template_contract = template.get("template_contract")
    group_definitions = template.get("group_definitions") or {}
    slot_definitions = template.get("slot_definitions") or []

    if contract_version != CONTRACT_VERSION or not isinstance(template_contract, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The active template does not expose a supported generation contract.",
        )

    canonical_context, sheet, project, enterprise = build_company_cv_context(
        sheet_id,
        generation_guidance=generation_guidance,
    )
    canonical_payload = canonical_context.model_dump(mode="json")
    normalized_generation_guidance = str(canonical_payload.get("generation_guidance") or "").strip()
    source_text, source_path = _extract_source_cv_text(canonical_payload)
    raw_experience_source_blocks = _build_experience_source_blocks(
        source_text=source_text,
        canonical_payload=canonical_payload,
    )
    canonical_payload, canonical_guidance_filter = _filter_experiences_removed_by_guidance(
        canonical_payload,
        generation_guidance=normalized_generation_guidance,
    )
    helper_json = _load_parsed_json_helper(
        project_id=str(project["id"]),
        source_filename=str(canonical_payload.get("identity", {}).get("source_filename") or ""),
    )
    llm_contract = _filter_contract_roots(template_contract, CV_GENERATION_ROOTS)
    template_guidance = _extract_template_generation_guidance(
        template=template,
        slot_definitions=slot_definitions,
    )
    semantic_template_profile = _build_semantic_template_profile(
        template_contract=llm_contract,
        group_definitions=group_definitions,
        template_guidance=template_guidance,
    )
    experience_source_blocks = _filter_experience_source_blocks_removed_by_guidance(
        raw_experience_source_blocks,
        filter_summary=canonical_guidance_filter,
    )
    trace_enabled = is_company_cv_trace_enabled()

    generation_payload = _call_generation_llm(
        source_text=source_text,
        helper_json=helper_json,
        canonical_payload=canonical_payload,
        template_contract=llm_contract,
        group_definitions=group_definitions,
        slot_definitions=slot_definitions,
        template_text_outline=template_guidance["template_text_outline"],
        slot_families=template_guidance["slot_families"],
        section_slot_map=template_guidance["section_slot_map"],
        semantic_template_profile=semantic_template_profile,
        experience_source_blocks=experience_source_blocks,
        generation_guidance=normalized_generation_guidance,
        trace_enabled=trace_enabled,
    )
    llm_trace_payload = None
    if isinstance(generation_payload, dict):
        llm_trace_payload = generation_payload.pop("_llm_trace_payload", None)
    generated_data, evidence, omissions = _validate_generation_payload(
        generation_payload=generation_payload,
        template_contract=llm_contract,
        group_definitions=group_definitions,
        slot_definitions=slot_definitions,
        source_text=source_text,
        helper_json=helper_json,
        canonical_payload=canonical_payload,
        experience_source_blocks=experience_source_blocks,
    )
    model_placeholder_values = _validate_placeholder_values(
        generation_payload=generation_payload,
        slot_definitions=slot_definitions,
        source_text=source_text,
        helper_json=helper_json,
        canonical_payload=canonical_payload,
    )
    _remove_excluded_experience_placeholder_values(
        model_placeholder_values,
        generation_guidance=normalized_generation_guidance,
        filter_summary=canonical_guidance_filter,
    )

    merged_context = deepcopy(canonical_payload)
    for root, value in generated_data.items():
        merged_context[root] = _merge_generated_value_into_context(
            merged_context.get(root),
            value,
        )
    merged_context, merged_guidance_filter = _filter_experiences_removed_by_guidance(
        merged_context,
        generation_guidance=normalized_generation_guidance,
    )

    # Keep deterministic source filename from the original context.
    if isinstance(merged_context.get("identity"), dict):
        merged_context["identity"]["source_filename"] = canonical_payload.get("identity", {}).get("source_filename", "")

    semantic_blocks = _build_semantic_cv_blocks(merged_context)
    render_context, missing_required = build_render_context(template, merged_context)
    baseline_placeholder_values = _build_placeholder_candidate_values(
        data=merged_context,
        slot_definitions=slot_definitions,
    )
    raw_placeholder_values = dict(baseline_placeholder_values)
    raw_placeholder_values.update(model_placeholder_values)
    _remove_excluded_experience_placeholder_values(
        raw_placeholder_values,
        generation_guidance=normalized_generation_guidance,
    )
    placeholder_values = _compose_placeholder_values(
        baseline=raw_placeholder_values,
        override={},
    )
    _remove_excluded_experience_placeholder_values(
        placeholder_values,
        generation_guidance=normalized_generation_guidance,
    )
    _enrich_experience_placeholder_values_from_source_blocks(
        values=placeholder_values,
        experience_source_blocks=experience_source_blocks,
    )
    _compose_multi_education_placeholder_values(
        values=placeholder_values,
        data=merged_context,
        slot_definitions=slot_definitions,
    )
    if placeholder_values:
        render_context.update(placeholder_values)
    _normalize_render_context_placeholders(render_context)
    if missing_required:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Company CV generation blocked because critical template placeholders are missing data after targeted generation: "
                + ", ".join(missing_required)
            ),
        )

    return {
        "canonical_context": merged_context,
        "render_context": render_context,
        "generation_trace": {
            "contract_version": contract_version,
            "provider": generation_payload.get("_provider"),
            "model": generation_payload.get("_model"),
            "source_cv_path": source_path,
            "template_contract": llm_contract,
            "template_guidance": template_guidance,
            "generation_guidance": {
                "enabled": bool(normalized_generation_guidance),
                "value": normalized_generation_guidance,
                "precedence": "overrides_default_orientation_but_not_source_fidelity",
                "experience_filter": {
                    "version": GUIDANCE_EXPERIENCE_FILTER_VERSION,
                    "canonical": canonical_guidance_filter,
                    "merged": merged_guidance_filter,
                },
            },
            "semantic_block_version": SEMANTIC_BLOCK_VERSION,
            "semantic_blocks_usage": "prompt_guidance_and_trace_only",
            "semantic_template_profile": semantic_template_profile,
            "semantic_blocks": semantic_blocks,
            "render_engine": f"build_render_context/{COMPANY_CV_MAPPER_VERSION}",
            "experience_source_blocks": experience_source_blocks,
            "filled_contract": generated_data,
            "placeholder_values": placeholder_values,
            "baseline_placeholder_values": baseline_placeholder_values,
            "evidence": evidence,
            "validation": {
                "missing_required": missing_required,
                "omissions": omissions,
            },
            "trace_enabled": trace_enabled,
            "coverage_summary": _build_coverage_summary(
                template_contract=llm_contract,
                generated_data=generated_data,
                omissions=omissions,
            ),
        },
        "llm_trace_payload": llm_trace_payload,
    }


def _extract_source_cv_text(canonical_payload: dict[str, Any]) -> tuple[str, str | None]:
    source_filename = (
        canonical_payload.get("identity", {}).get("source_filename")
        or ""
    )
    project_id = canonical_payload.get("project", {}).get("id") or ""
    if not source_filename or not project_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unable to resolve original CV source for targeted generation.",
        )

    from brainrh.services.cv_service import CVService

    metadata = CVService.get_cv_metadata(project_id, source_filename)
    if not metadata or not metadata.get("file_path"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Original CV source file is unavailable for targeted generation.",
        )

    storage_path = str(metadata["file_path"])
    suffix = Path(storage_path).suffix or ".tmp"
    payload = FileStorage.load_bytes(storage_path)

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as handle:
        handle.write(payload)
        handle.flush()
        return extract_text_from_file(handle.name), storage_path


def _filter_contract_roots(payload: dict[str, Any], roots: set[str]) -> dict[str, Any]:
    return {
        key: value
        for key, value in payload.items()
        if key in roots
    }


def _load_parsed_json_helper(*, project_id: str, source_filename: str) -> dict[str, Any]:
    if not project_id or not source_filename:
        return {}
    helper = CVService.get_cv(project_id, source_filename)
    if not helper:
        return {}
    payload = helper.get("data")
    return payload if isinstance(payload, dict) else {}


def _extract_template_generation_guidance(
    *,
    template: dict[str, Any],
    slot_definitions: list[dict[str, Any]],
) -> dict[str, Any]:
    allowed_placeholders = {
        str(slot.get("placeholder") or "").strip()
        for slot in slot_definitions
        if str(slot.get("placeholder") or "").strip()
    }
    raw_slot_families = template.get("slot_families") if isinstance(template.get("slot_families"), dict) else {}
    raw_section_slot_map = (
        template.get("section_slot_map")
        if isinstance(template.get("section_slot_map"), dict)
        else {}
    )

    slot_families = {
        str(placeholder): str(family)
        for placeholder, family in raw_slot_families.items()
        if str(placeholder).strip() in allowed_placeholders and str(family).strip()
    }
    section_slot_map: dict[str, list[str]] = {}
    for section_name, placeholders in raw_section_slot_map.items():
        if not isinstance(placeholders, list):
            continue
        filtered: list[str] = []
        seen: set[str] = set()
        for placeholder in placeholders:
            normalized = str(placeholder).strip()
            if normalized in allowed_placeholders and normalized not in seen:
                filtered.append(normalized)
                seen.add(normalized)
        if filtered:
            section_slot_map[str(section_name)] = filtered

    return {
        "template_text_outline": str(template.get("template_text_outline") or "").strip(),
        "slot_families": slot_families,
        "section_slot_map": section_slot_map,
    }


def _filter_experiences_removed_by_guidance(
    context: dict[str, Any],
    *,
    generation_guidance: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    guidance = str(generation_guidance if generation_guidance is not None else context.get("generation_guidance") or "")
    markers = _generation_guidance_exclusion_markers(guidance)
    summary: dict[str, Any] = {
        "version": GUIDANCE_EXPERIENCE_FILTER_VERSION,
        "enabled": bool(markers),
        "markers": sorted(markers),
        "removed_count": 0,
        "removed_experiences": [],
    }
    experiences = context.get("experiences")
    if not markers or not isinstance(experiences, list):
        return context, summary

    kept: list[Any] = []
    removed: list[dict[str, Any]] = []
    for index, experience in enumerate(experiences):
        if isinstance(experience, dict) and _experience_matches_guidance_exclusion(
            experience,
            markers=markers,
        ):
            removed.append(
                {
                    "index": index,
                    "company": str(experience.get("company_full") or experience.get("company") or ""),
                    "role": str(experience.get("role") or experience.get("position") or ""),
                    "period": str(experience.get("period_full") or experience.get("period") or ""),
                }
            )
            continue
        kept.append(experience)

    if not removed:
        return context, summary

    filtered_context = deepcopy(context)
    filtered_context["experiences"] = kept
    summary["removed_count"] = len(removed)
    summary["removed_experiences"] = removed
    return filtered_context, summary


def _filter_experience_source_blocks_removed_by_guidance(
    blocks: list[dict[str, Any]],
    *,
    filter_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    removed_indices = {
        int(item.get("index"))
        for item in filter_summary.get("removed_experiences") or []
        if isinstance(item, dict) and str(item.get("index", "")).isdigit()
    }
    if not removed_indices:
        return blocks

    filtered_blocks: list[dict[str, Any]] = []
    for block in blocks:
        try:
            source_index = int(block.get("index") or 0)
        except (TypeError, ValueError):
            continue
        if source_index in removed_indices:
            continue
        filtered_block = dict(block)
        filtered_block["index"] = len(filtered_blocks)
        filtered_block["source_index"] = source_index
        filtered_blocks.append(filtered_block)
    return filtered_blocks


def _generation_guidance_exclusion_markers(generation_guidance: Any) -> set[str]:
    guidance = str(generation_guidance or "").replace("\xa0", " ")
    normalized_guidance = _normalize_guidance_matchable_text(guidance)
    if not normalized_guidance:
        return set()
    removal_verbs = r"(?:retir\w*|supprim\w*|enl[eè]v\w*|exclu\w*|ignor\w*|\bvire\b|\bvires\b|\bvirez\b|\bvirer\b)"
    if not re.search(removal_verbs, guidance, flags=re.I):
        return set()

    markers: set[str] = set()
    removal_boundary = rf"(?:\s+(?:et|puis|ensuite)\s+{removal_verbs}|\s*[,;]\s*{removal_verbs}|[.\n]|$)"
    for match in re.finditer(
        removal_verbs
        +
        r"\s+(?:(?:l['’]?\s*)?(?:exp[ée]rience|poste|mission)\s*)?"
        r"(?P<connector>au|aux|chez|de|du|des|à|a)?\s*(?P<target>.*?)"
        rf"(?={removal_boundary})",
        guidance,
        flags=re.I,
    ):
        target = _clean_generation_guidance_exclusion_target(match.group("target"))
        if not _is_experience_removal_target(
            match.group(0),
            target=target,
            connector=match.group("connector"),
        ):
            continue
        split_targets = _split_generation_guidance_exclusion_target(target)
        if len(split_targets) <= 1:
            marker = _normalize_guidance_matchable_text(target)
            marker_tokens = _guidance_marker_tokens(marker)
            if marker_tokens:
                markers.add(" ".join(marker_tokens))
        for split_target in split_targets:
            split_marker = _normalize_guidance_matchable_text(split_target)
            split_tokens = _guidance_marker_tokens(split_marker)
            if len(split_tokens) >= 2:
                markers.add(" ".join(split_tokens))
    return markers


def _is_experience_removal_target(raw_match: str, *, target: str, connector: str | None) -> bool:
    if re.search(r"\b(?:exp[ée]rience|poste|mission)\b", raw_match, flags=re.I):
        return True
    if connector and connector.casefold() in {"au", "aux", "chez", "de", "du", "des", "à", "a"}:
        tokens = _guidance_marker_tokens(target)
        return len(tokens) >= 2 and any(token[:1].isupper() for token in str(target or "").split())
    return False


def _split_generation_guidance_exclusion_target(value: Any) -> list[str]:
    target = str(value or "")
    parts = re.split(r"\s*(?:[,;]|\bet\b|\bpuis\b|\bensuite\b)\s*", target, flags=re.I)
    return [part.strip(" .,:;") for part in parts if part.strip(" .,:;")]


def _clean_generation_guidance_exclusion_target(value: Any) -> str:
    target = str(value or "").replace("\xa0", " ")
    target = re.sub(r"</?(?:u|strong|b|em|i|span|p|br)\b[^>]*>", " ", target, flags=re.I)
    target = target.replace("**", "").replace("__", "")
    target = re.sub(
        r"\s+(?:du|de la|de ce|dans le|dans la|sur le|sur la)\s+"
        r"(?:rendu|cv|document|profil|template|mod[èe]le)\b.*$",
        "",
        target,
        flags=re.I,
    )
    target = re.sub(r"\b(?:c['’]?\s*est\s+tout|merci|stp|svp|s['’]il\s+te\s+pla[iî]t)\b.*$", "", target, flags=re.I)
    target = re.split(
        r"\s*(?:[,;]|\bet\b|\bpuis\b|\bensuite\b)\s+(?:change|changer|modifie|modifier|mets|mettre|met|oriente|orienter|garde|conserve|ajoute|ajouter|corrige|corriger)\b",
        target,
        maxsplit=1,
        flags=re.I,
    )[0]
    target = re.sub(r"^(?:l['’]?\s*)?(?:exp[ée]rience|poste|mission)\s+", "", target, flags=re.I)
    target = re.sub(r"^(?:au|aux|chez|de|du|des|à|a)\s+", "", target, flags=re.I)
    return re.sub(r"\s+", " ", target).strip(" .,:;")


def _normalize_guidance_matchable_text(value: Any) -> str:
    text = str(value or "").replace("\xa0", " ").casefold()
    text = "".join(
        character
        for character in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(character)
    )
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return " ".join(text.split()).strip()


def _guidance_marker_tokens(marker: str) -> list[str]:
    return [
        token
        for token in _normalize_guidance_matchable_text(marker).split()
        if len(token) >= 2 and token not in GUIDANCE_EXCLUSION_STOPWORDS
    ]


def _experience_matches_guidance_exclusion(
    experience: dict[str, Any],
    *,
    markers: set[str],
) -> bool:
    experience_text = _normalize_guidance_matchable_text(
        " ".join(
            [
                str(experience.get("company_full") or ""),
                str(experience.get("company") or ""),
                str(experience.get("role") or ""),
                str(experience.get("position") or ""),
                str(experience.get("period_full") or ""),
                str(experience.get("period") or ""),
            ]
        )
    )
    if not experience_text:
        return False
    experience_tokens = set(experience_text.split())
    for marker in markers:
        marker_text = _normalize_guidance_matchable_text(marker)
        marker_tokens = _guidance_marker_tokens(marker_text)
        if not marker_tokens:
            continue
        if marker_text and marker_text in experience_text:
            return True
        if len(marker_tokens) >= 2 and set(marker_tokens).issubset(experience_tokens):
            return True
        if len(marker_tokens) == 1 and len(marker_tokens[0]) >= 5 and marker_tokens[0] in experience_tokens:
            return True
    return False


def _remove_excluded_experience_placeholder_values(
    values: dict[str, str],
    *,
    generation_guidance: str | None,
    filter_summary: dict[str, Any] | None = None,
) -> None:
    markers = _generation_guidance_exclusion_markers(generation_guidance)
    if not values:
        return

    for source_index in _removed_experience_placeholder_numbers(filter_summary):
        for key in list(values):
            if key.startswith(f"exp{source_index}_"):
                values.pop(key, None)

    if not markers:
        return

    indices = sorted(
        {
            int(match.group(1))
            for key in values
            for match in [re.match(r"^exp(\d+)_", key)]
            if match
        }
    )
    for index in indices:
        indexed_values = [
            str(value or "")
            for key, value in values.items()
            if key in {
                f"exp{index}_entreprise_full",
                f"exp{index}_entreprise",
                f"exp{index}_role",
                f"exp{index}_poste",
                f"exp{index}_periode_full",
                f"exp{index}_periode",
            }
        ]
        pseudo_experience = {
            "company_full": " ".join(indexed_values),
            "role": "",
            "period_full": "",
        }
        if not _experience_matches_guidance_exclusion(pseudo_experience, markers=markers):
            continue
        for key in list(values):
            if key.startswith(f"exp{index}_"):
                values.pop(key, None)


def _removed_experience_placeholder_numbers(filter_summary: dict[str, Any] | None) -> set[int]:
    numbers: set[int] = set()
    if not isinstance(filter_summary, dict):
        return numbers
    for item in filter_summary.get("removed_experiences") or []:
        if not isinstance(item, dict):
            continue
        try:
            numbers.add(int(item.get("index")) + 1)
        except (TypeError, ValueError):
            continue
    return numbers


def _build_project_fallback_instruction(
    *,
    slot_families: dict[str, Any],
    section_slot_map: dict[str, Any],
) -> str:
    has_project_section = bool(section_slot_map.get("project_list")) or any(
        str(family) == "project_list"
        for family in slot_families.values()
    )
    has_experience_body = bool(section_slot_map.get("experience_detail_list")) or any(
        str(family) == "experience_body"
        for family in slot_families.values()
    )

    if not has_project_section and has_experience_body:
        return (
            "Le template ne montre pas de vraie zone projet exploitable mais expose une zone expérience riche. "
            "Si un projet du CV correspond manifestement à une expérience et qu'aucun slot projet propre n'existe, "
            "absorbe ce contenu dans `experiences`, en priorité dans `tasks`, puis `highlights`, puis `key_points`, "
            "sans perdre l'information utile."
        )
    return (
        "Le template expose une zone projet distincte ou ne montre pas de zone expérience riche suffisante. "
        "Ne force donc pas l'absorption de `projects` dans `experiences` sans nécessité explicite."
    )


def _build_experience_source_blocks(
    *,
    source_text: str,
    canonical_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    experiences = canonical_payload.get("experiences")
    if not isinstance(experiences, list) or not experiences:
        return []

    lines = [
        " ".join(str(line).split()).strip()
        for line in re.split(r"[\r\n]+", source_text or "")
        if " ".join(str(line).split()).strip()
    ]
    if not lines:
        return []
    normalized_lines = [_normalize_text(line) for line in lines]

    starts: list[int | None] = []
    cursor = 0
    for experience in experiences:
        if not isinstance(experience, dict):
            starts.append(None)
            continue
        start_index = _find_experience_block_start(
            lines=lines,
            normalized_lines=normalized_lines,
            experience=experience,
            start_index=cursor,
        )
        starts.append(start_index)
        if start_index is not None:
            cursor = max(cursor, start_index + 1)

    blocks: list[dict[str, Any]] = []
    for index, experience in enumerate(experiences):
        start_index = starts[index]
        if start_index is None or not isinstance(experience, dict):
            continue
        next_start = next((value for value in starts[index + 1:] if value is not None and value > start_index), len(lines))
        block_lines = _truncate_experience_block_at_global_section(lines[start_index:next_start])
        content_lines, context_candidate, environment_candidate = _extract_experience_block_content(
            block_lines=block_lines,
            experience=experience,
        )
        blocks.append(
            {
                "index": index,
                "company": str(experience.get("company_full") or experience.get("company") or ""),
                "role": str(experience.get("role") or experience.get("position") or ""),
                "period": str(experience.get("period_full") or experience.get("period") or ""),
                "block_text": "\n".join(block_lines),
                "content_lines": content_lines,
                "context_candidate": context_candidate,
                "environment_candidate": environment_candidate,
            }
        )
    return blocks


def _find_experience_block_start(
    *,
    lines: list[str],
    normalized_lines: list[str],
    experience: dict[str, Any],
    start_index: int,
) -> int | None:
    role_candidates = [
        _normalize_text(str(experience.get("role") or "")),
        _normalize_text(str(experience.get("position") or "")),
    ]
    role_candidates = [value for value in role_candidates if len(value) >= 5]
    company_candidates = [
        _normalize_text(str(experience.get("company_full") or "")),
        _normalize_text(str(experience.get("company") or "")),
    ]
    company_candidates = [value for value in company_candidates if len(value) >= 4]
    period_tokens = _extract_period_tokens(
        str(experience.get("period_full") or experience.get("period") or "")
    )

    candidates: list[int] = []

    for index in range(start_index, len(lines)):
        line = normalized_lines[index]
        role_match = any(candidate and candidate in line for candidate in role_candidates)
        company_match = any(candidate and candidate in line for candidate in company_candidates)
        if role_match:
            previous = normalized_lines[index - 1] if index > 0 else ""
            if any(candidate and candidate in previous for candidate in company_candidates):
                candidates.append(index - 1)
            candidates.append(index)
        elif company_match:
            candidates.append(index)

    candidates = list(dict.fromkeys(candidates))
    if not candidates:
        return None

    scored_candidates = [
        (
            _score_experience_block_start(
                lines=lines,
                normalized_lines=normalized_lines,
                index=index,
                role_candidates=role_candidates,
                company_candidates=company_candidates,
                period_tokens=period_tokens,
            ),
            index,
        )
        for index in candidates
    ]
    best_score, best_index = max(scored_candidates, key=lambda item: (item[0], -item[1]))
    if best_score > 0:
        return best_index
    return candidates[0]


def _score_experience_block_start(
    *,
    lines: list[str],
    normalized_lines: list[str],
    index: int,
    role_candidates: list[str],
    company_candidates: list[str],
    period_tokens: set[str],
) -> int:
    score = 0
    header_start = max(0, index - 1)
    header_end = min(len(lines), index + 4)
    detail_end = min(len(lines), index + 16)
    header_lines = normalized_lines[header_start:header_end]
    detail_lines = lines[index:detail_end]

    if any(
        candidate and any(candidate in line for line in header_lines)
        for candidate in company_candidates
    ):
        score += 2
    if any(
        candidate and any(candidate in line for line in header_lines)
        for candidate in role_candidates
    ):
        score += 2

    if period_tokens:
        header_text = " ".join(header_lines)
        matched_period_tokens = {token for token in period_tokens if token in header_text}
        if len(matched_period_tokens) >= min(2, len(period_tokens)):
            score += 4
        elif matched_period_tokens:
            score += 2

    first_global_heading_offset: int | None = None
    first_detail_marker_offset: int | None = None
    for offset, line in enumerate(detail_lines):
        if first_detail_marker_offset is None and _is_experience_detail_marker(line):
            first_detail_marker_offset = offset
        if first_global_heading_offset is None and _is_global_cv_section_heading(line):
            first_global_heading_offset = offset

    if first_detail_marker_offset is not None:
        score += 8
    if (
        first_global_heading_offset is not None
        and (
            first_detail_marker_offset is None
            or first_global_heading_offset < first_detail_marker_offset
        )
    ):
        score -= 6

    return score


def _extract_period_tokens(value: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"\b(?:\d{1,2}/\d{4}|\d{4})\b", value or "")
    }


def _is_experience_detail_marker(line: str) -> bool:
    return bool(EXPERIENCE_DETAIL_MARKER_PATTERN.match(str(line or "").strip()))


def _is_global_cv_section_heading(line: str) -> bool:
    return bool(GLOBAL_CV_SECTION_HEADING_PATTERN.match(str(line or "").strip()))


def _is_experience_footer_noise(line: str) -> bool:
    return bool(EXPERIENCE_FOOTER_NOISE_PATTERN.search(str(line or "").strip()))


def _looks_like_experience_header_line(line: str, experience: dict[str, Any]) -> bool:
    stripped_line = str(line or "").strip()
    if not stripped_line:
        return False
    if EXPERIENCE_LABEL_ONLY_PATTERN.match(stripped_line):
        return True

    normalized_line = _normalize_matchable_text(stripped_line)
    if not normalized_line:
        return False

    role_candidates = [
        _normalize_matchable_text(str(experience.get("role") or "")),
        _normalize_matchable_text(str(experience.get("position") or "")),
    ]
    role_candidates = [value for value in role_candidates if value]
    company_candidates = [
        _normalize_matchable_text(str(experience.get("company_full") or "")),
        _normalize_matchable_text(str(experience.get("company") or "")),
    ]
    company_candidates = [value for value in company_candidates if value]

    if any(candidate == normalized_line for candidate in role_candidates + company_candidates):
        return True

    line_tokens = normalized_line.split()
    if any(candidate and candidate in normalized_line for candidate in role_candidates):
        max_tokens = max((len(candidate.split()) for candidate in role_candidates), default=0) + 4
        if len(line_tokens) <= max_tokens:
            return True

    if any(candidate and candidate in normalized_line for candidate in company_candidates):
        max_tokens = max((len(candidate.split()) for candidate in company_candidates), default=0) + 6
        if len(line_tokens) <= max_tokens and not any(character in stripped_line for character in ".;!?"):
            return True

    return False


def _is_experience_source_noise_line(line: str, experience: dict[str, Any]) -> bool:
    return (
        _is_global_cv_section_heading(line)
        or _is_experience_footer_noise(line)
        or _looks_like_experience_header_line(line, experience)
    )


def _line_is_semantically_represented(line: str, represented_lines: list[str]) -> bool:
    normalized_line = _normalize_matchable_text(line)
    if not normalized_line:
        return True

    for candidate in represented_lines:
        normalized_candidate = _normalize_matchable_text(candidate)
        if not normalized_candidate:
            continue
        if normalized_candidate == normalized_line:
            return True
        shorter, longer = sorted((normalized_line, normalized_candidate), key=len)
        if len(shorter) >= 32 or len(shorter.split()) >= 5:
            if shorter in longer:
                return True
    return False


def _truncate_experience_block_at_global_section(block_lines: list[str]) -> list[str]:
    for offset, line in enumerate(block_lines):
        if offset > 0 and (
            _is_global_cv_section_heading(line) or _is_experience_footer_noise(line)
        ):
            return block_lines[:offset]
    return block_lines


def _extract_experience_block_content(
    *,
    block_lines: list[str],
    experience: dict[str, Any],
) -> tuple[list[str], str, str]:
    role = _normalize_text(str(experience.get("role") or experience.get("position") or ""))
    company = _normalize_text(str(experience.get("company_full") or experience.get("company") or ""))
    period = _normalize_text(str(experience.get("period_full") or experience.get("period") or ""))

    context_candidate = ""
    environment_candidate = ""
    content_lines: list[str] = []
    seen: set[str] = set()

    for raw_line in block_lines:
        normalized_line = _normalize_text(raw_line)
        if not normalized_line:
            continue
        if _is_experience_source_noise_line(raw_line, experience):
            continue
        if role and normalized_line == role:
            continue
        if company and normalized_line == company:
            continue
        if period and normalized_line == period:
            continue
        if company and company in normalized_line and period and any(token in normalized_line for token in period.split()):
            continue

        cleaned = EXPERIENCE_BLOCK_LABEL_PATTERN.sub("", raw_line).strip()
        cleaned = EXPERIENCE_BULLET_PREFIX_PATTERN.sub("", cleaned).strip()
        cleaned_key = _normalize_text(cleaned)
        if not cleaned_key or cleaned_key in seen:
            continue
        seen.add(cleaned_key)

        if not context_candidate and any(tag in normalized_line for tag in ("projet/contexte", "contexte")):
            context_candidate = cleaned
        elif not environment_candidate and "environnement" in normalized_line:
            environment_candidate = cleaned
        content_lines.append(cleaned)

    return content_lines, context_candidate, environment_candidate


def _merge_generated_value_into_context(original: Any, generated: Any) -> Any:
    if isinstance(original, dict) and isinstance(generated, dict):
        merged = deepcopy(original)
        for key, value in generated.items():
            merged[key] = _merge_generated_value_into_context(merged.get(key), value)
        return merged

    if isinstance(original, list) and isinstance(generated, list):
        merged_list: list[Any] = []
        max_len = max(len(original), len(generated))
        for index in range(max_len):
            orig_item = original[index] if index < len(original) else None
            gen_item = generated[index] if index < len(generated) else None
            if gen_item is None:
                merged_list.append(deepcopy(orig_item))
            elif orig_item is None:
                merged_list.append(deepcopy(gen_item))
            else:
                merged_list.append(_merge_generated_value_into_context(orig_item, gen_item))
        return merged_list

    if _is_missing_contract_value(generated):
        return deepcopy(original)
    return deepcopy(generated)


def _call_generation_llm(
    *,
    source_text: str,
    helper_json: dict[str, Any],
    canonical_payload: dict[str, Any],
    template_contract: dict[str, Any],
    group_definitions: dict[str, Any],
    slot_definitions: list[dict[str, Any]],
    template_text_outline: str,
    slot_families: dict[str, Any],
    section_slot_map: dict[str, Any],
    semantic_template_profile: dict[str, Any],
    experience_source_blocks: list[dict[str, Any]] | None = None,
    generation_guidance: str = "",
    trace_enabled: bool = False,
) -> dict[str, Any]:
    client, provider_name, model_name = _get_generation_client()
    slot_payload = [
        {
            "placeholder": slot.get("placeholder"),
            "contract_path": slot.get("contract_path"),
            "required": slot.get("required"),
            "source_kind": slot.get("source_kind"),
        }
        for slot in slot_definitions
        if slot.get("source_kind") == "cv"
    ]
    source_inventory = _build_source_inventory(canonical_payload)
    placeholder_guide = _build_placeholder_injection_guide(slot_definitions)
    project_fallback_instruction = _build_project_fallback_instruction(
        slot_families=slot_families,
        section_slot_map=section_slot_map,
    )
    experience_source_blocks = experience_source_blocks or []
    direct_override_placeholders = sorted(
        placeholder
        for placeholder in (
            str(slot.get("placeholder") or "")
            for slot in slot_definitions
        )
        if placeholder and _allow_direct_placeholder_override(placeholder)
    )

    generation_prompt = f"""
Tu es un moteur de reprise, nettoyage et structuration de CV vers JSON.

RÔLE:
Tu transformes un CV source en JSON strictement conforme au contrat fourni.
Ta mission n'est pas de rédiger une version marketing du CV.
Ta mission est de reprendre, nettoyer, ranger, et ne rien perdre d'utile.

OBJECTIF:
- produire un JSON qui correspond EXACTEMENT au contrat
- utiliser EXACTEMENT les clés du contrat
- préserver au moins 95% du contenu utile du CV
- conserver toutes les occurrences distinctes
- ne pas tronquer les listes
- produire `placeholder_values` uniquement pour les placeholders autorisés d'affichage

PRINCIPE CENTRAL:
- extraction maximale
- transformation minimale
- rangement intelligent
- aucune invention
- aucune fusion d'occurrences distinctes

RÈGLES DE REPRISE TEXTUELLE:
1. Privilégie toujours la reprise fidèle du texte source.
2. Ne reformule pas par défaut.
3. Corrige seulement les fautes évidentes, la ponctuation simple, les retours à la ligne cassés, les mots coupés et les artefacts OCR/PDF.
4. Conserve les intitulés, entreprises, projets, technologies, outils, méthodes et acronymes du CV source.
5. Reformule uniquement si le texte source est illisible, trop fragmenté ou incompatible avec la clé cible.

RÈGLES DE STRUCTURATION:
6. Réponds uniquement en JSON valide.
7. Ne crée jamais de clé supplémentaire.
8. Ne supprime jamais une clé du contrat.
9. Toutes les structures répétées restent non bornées.
10. Si le CV contient 3 expériences, renvoie 3 objets dans `experiences`.
11. Si le CV contient plusieurs formations, certifications ou langues distinctes, conserve-les toutes.
12. Ne fusionne jamais deux expériences, deux projets, deux formations, deux certifications ou deux langues distinctes.

RÈGLES DE RANGEMENT / RABATTEMENT:
13. Place chaque information dans le champ exact si disponible.
14. Si aucun champ exact n'existe, utilise le champ sémantiquement compatible le plus proche sans changer le sens.
15. Ne transforme jamais une localisation en contexte.
16. Ne transforme jamais un nom de fichier en identité.
17. Si une sous-rubrique métier n'a pas de place exacte, redistribue-la vers `tasks`, puis `highlights`, puis `key_points`.
18. {project_fallback_instruction}

CONSIGNES SPÉCIFIQUES UTILISATEUR:
- Ces consignes sont prioritaires pour orienter la sélection, la hiérarchie, le niveau de détail et la mise en avant.
- Si elles contredisent une orientation générique du template, applique les consignes spécifiques.
- Elles ne remplacent jamais la fidélité au CV source, au JSON helper et au contexte système.
- Elles ne sont jamais une source de preuve factuelle: n'invente aucun rôle, compétence, outil, diplôme, projet ou résultat absent des sources.
- Si une consigne demande une mise en avant impossible à prouver, ignore cette partie et signale l'omission.

CONSIGNES SPÉCIFIQUES FOURNIES:
{generation_guidance or "(aucune consigne spécifique)"}

MODÈLE AGNOSTIQUE PAR BLOCS:
- Le template cible doit être considéré comme une suite de grands blocs sémantiques, pas comme une collection de micro-placeholders.
- Les blocs attendus sont généralement: identité, compétences clés, compétences techniques, formation/certifications, langues, expériences.
- Dans chaque expérience, conserve une structure simple: entreprise/période, rôle, contexte/descriptif, bloc missions/projets/réalisations, environnement.
- Quand le contrat expose `experiences[].tasks`, ce champ représente le bloc libre "missions/projets/réalisations": rattache-y aussi les projets, produits, réalisations ou responsabilités qui appartiennent à la même expérience.
- Utilise `projects` au niveau racine uniquement pour des projets autonomes que le CV présente hors des expériences, ou si le template expose une vraie zone projet distincte.
- Les compétences et langues doivent rester des blocs lisibles et extensibles: ne force pas une granularité artificielle si le contrat permet une liste.

RÈGLES ANTI-DUPLICATION:
19. Une même information détaillée ne doit apparaître qu'une seule fois dans `data`.
20. Ne recopie pas la même phrase dans `tasks`, `highlights` et `key_points`.
21. Choisis l'emplacement le plus précis.
22. `summary` peut synthétiser, mais ne remplace pas les détails disponibles dans les expériences, projets ou compétences.
23. `placeholder_values` peut être compact, mais ne remplace jamais la structure de `data`.
24. Ne préfixe jamais les items de listes par `•`, `-`, `✓` ou un autre glyphe de puce: le template Word porte déjà la mise en forme.
25. Pour une expérience longue, si le bloc source contient au moins cinq lignes utiles de missions/projets/réalisations, conserve plusieurs points distincts au lieu de réduire à trois généralités.

PREUVE:
- Chaque valeur non vide doit avoir une preuve.
- Si tu n'as pas de preuve leaf-by-leaf, fournis au minimum une preuve au niveau de la clé parente correspondante.
- `source_type` autorisés: `original_text`, `parsed_json`, `system_context`
- `confidence_mode` autorisés: `explicit`, `derived`, `inferred`

AUTO-VÉRIFICATION OBLIGATOIRE AVANT DE RÉPONDRE:
- vérifie que toutes les clés de sortie existent dans le contrat et uniquement dans le contrat
- vérifie que toutes les listes gardent toutes les occurrences utiles du CV
- vérifie que tu n'as fusionné aucune occurrence distincte
- vérifie que les formations, certifications, langues et expériences distinctes du CV sont toujours présentes
- vérifie qu'aucun nom de fichier n'est utilisé comme identité
- vérifie qu'aucune localisation n'est utilisée comme contexte
- vérifie que les preuves pointent bien vers le texte source, le JSON helper ou le contexte système
- vérifie que les valeurs retournées permettront bien de remplir les placeholders attendus
- vérifie qu'aucune information utile n'a été supprimée alors qu'un champ voisin exploitable existait
- vérifie que `placeholder_values` reste un override de présentation et ne remplace pas la structure `data`

FORMAT DE SORTIE STRICT:
{{
  "data": <contrat rempli>,
  "placeholder_values": {{
    "placeholder_name": "valeur finale exacte à injecter dans le template"
  }},
  "evidence": {{
    "path.to.field": {{
      "source_quote": "...",
      "source_type": "original_text|parsed_json|system_context",
      "confidence_mode": "explicit|derived|inferred",
      "reason_if_empty": ""
    }}
  }},
  "omissions": [
    {{
      "contract_path": "path.to.field",
      "reason": "why empty"
    }}
  ]
}}

SLOTS ATTENDUS:
{json.dumps(slot_payload, ensure_ascii=False, indent=2)}

GUIDE D'INJECTION PLACEHOLDERS -> JSON:
{json.dumps(placeholder_guide, ensure_ascii=False, indent=2)}

RÈGLE SUR `placeholder_values`:
- n'utilise `placeholder_values` QUE pour cette liste autorisée
- si une valeur directe aide clairement le rendu final du template, tu dois la fournir
- si le contrat suffit déjà, tu peux laisser ce placeholder absent de `placeholder_values`
- les valeurs de `placeholder_values` doivent être finales, prêtes à injecter telles quelles dans le template
- pour `competences_metiers`, renvoie une sélection compacte des éléments les plus représentatifs plutôt qu'une liste exhaustive illisible
- pour `tech_*`, renvoie des groupes courts, nets, adaptés à une lecture de CV
- pour `competence_cle_*`, renvoie des items unitaires, distincts, sans répétition

PLACEHOLDERS AUTORISÉS EN OVERRIDE DIRECT:
{json.dumps(direct_override_placeholders, ensure_ascii=False, indent=2)}

STRUCTURE TEMPLATE:
TEMPLATE_TEXT_OUTLINE:
{template_text_outline or "(outline indisponible)"}

SLOT_FAMILIES:
{json.dumps(slot_families, ensure_ascii=False, indent=2)}

SECTION_SLOT_MAP:
{json.dumps(section_slot_map, ensure_ascii=False, indent=2)}

PROFIL DE BLOCS SÉMANTIQUES:
{json.dumps(semantic_template_profile, ensure_ascii=False, indent=2)}

CONSIGNES SPÉCIFIQUES UTILISATEUR:
{generation_guidance or "(aucune consigne spécifique)"}

RÈGLE D'EXPÉRIENCE LONGUE:
Pour chaque expérience professionnelle, considère que l'expérience s'étend depuis son titre/date/entreprise jusqu'au début de l'expérience suivante.
Toutes les sous-sections à l'intérieur de cette zone appartiennent à la même expérience:
- Contexte
- Missions
- Réalisations
- Projets
- Exemples de projets
- Environnement
Ne t'arrête pas aux premières bullets si le bloc source contient plus de matière utile.

EXPERIENCE_SOURCE_BLOCKS:
{json.dumps(experience_source_blocks, ensure_ascii=False, indent=2)}

GROUPES RÉPÉTÉS:
{json.dumps(group_definitions, ensure_ascii=False, indent=2)}

INVENTAIRE SOURCE:
{json.dumps(source_inventory, ensure_ascii=False, indent=2)}

CONTRAT À REMPLIR:
{json.dumps(template_contract, ensure_ascii=False, indent=2)}

CONTEXTE CANONIQUE:
{json.dumps(_filter_contract_roots(canonical_payload, CV_GENERATION_ROOTS), ensure_ascii=False, indent=2)}

JSON HELPER:
{json.dumps(helper_json, ensure_ascii=False, indent=2)}

CV SOURCE TEXTE:
{source_text}
"""

    generation_response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": (
                    "Tu es un moteur de structuration CV vers JSON contractuel pour un programme strict. "
                    "Tu réponds uniquement en JSON et tu respectes exactement les clés demandées."
                ),
            },
            {
                "role": "user",
                "content": generation_prompt,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.05,
    )

    draft_content = generation_response.choices[0].message.content or "{}"
    draft_parse_error: str | None = None
    try:
        draft_payload = json.loads(draft_content)
    except json.JSONDecodeError as exc:
        draft_parse_error = str(exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Targeted generation parser returned invalid JSON: {exc}",
        ) from exc

    placeholder_candidate_values = _build_placeholder_candidate_values(
        data=draft_payload.get("data") if isinstance(draft_payload, dict) else {},
        slot_definitions=slot_definitions,
    )

    verification_prompt = f"""
Tu es le contrôleur final de conformité et d'exhaustivité d'un JSON de génération CV.

Tu reçois:
- le même contrat
- le même CV source
- la même structure template-aware
- une première sortie JSON candidate

Ta mission:
- corriger la sortie candidate en te basant d'abord sur le CV source et sur le contrat
- garantir que toutes les clés correspondent exactement au contrat
- garantir que toutes les listes conservent toutes les occurrences utiles du CV
- garantir qu'au moins 95% du contenu utile du CV est préservé
- garantir qu'aucune identité de type nom de fichier n'apparaît
- garantir qu'aucune localisation n'est utilisée comme contexte
- si une occurrence distincte manque, elle doit être réintroduite
- si deux occurrences ont été fusionnées, elles doivent être séparées
- si une reformulation s'éloigne inutilement du texte source, elle doit être rapprochée du texte source
- si une information apparaît plusieurs fois, garde l'emplacement le plus précis
- si un placeholder compact est trop long ou redondant, rends-le plus lisible
- si `placeholder_values` remplace une structure exploitable dans `data`, corrige-le
- si le candidat a plusieurs formations, certifications, langues ou expériences distinctes dans la source, elles doivent rester visibles dans la sortie
- répondre uniquement avec un JSON final corrigé AU MÊME FORMAT que l'entrée candidate:
  {{
    "data": <contrat rempli>,
    "placeholder_values": {{ ... }},
    "evidence": {{ ... }},
    "omissions": [ ... ]
  }}

CONTRAT:
{json.dumps(template_contract, ensure_ascii=False, indent=2)}

GUIDE D'INJECTION PLACEHOLDERS -> JSON:
{json.dumps(placeholder_guide, ensure_ascii=False, indent=2)}

PLACEHOLDERS AUTORISÉS EN OVERRIDE DIRECT:
{json.dumps(direct_override_placeholders, ensure_ascii=False, indent=2)}

STRUCTURE TEMPLATE:
TEMPLATE_TEXT_OUTLINE:
{template_text_outline or "(outline indisponible)"}

SLOT_FAMILIES:
{json.dumps(slot_families, ensure_ascii=False, indent=2)}

SECTION_SLOT_MAP:
{json.dumps(section_slot_map, ensure_ascii=False, indent=2)}

PROFIL DE BLOCS SÉMANTIQUES:
{json.dumps(semantic_template_profile, ensure_ascii=False, indent=2)}

CONSIGNES SPÉCIFIQUES UTILISATEUR:
- Elles priment sur l'orientation générique du template pour choisir quoi mettre en avant.
- Elles ne priment jamais sur la fidélité au CV source ni sur l'obligation de preuve.
- Elles ne peuvent pas servir de source_quote.

{generation_guidance or "(aucune consigne spécifique)"}

SORTIE CANDIDATE:
{json.dumps(draft_payload, ensure_ascii=False, indent=2)}

PLACEHOLDER_VALUES CANDIDATS CALCULÉS CÔTÉ PROGRAMME:
{json.dumps(placeholder_candidate_values, ensure_ascii=False, indent=2)}

RÈGLE TEMPLATE-DRIVEN SUR LES PROJETS:
{project_fallback_instruction}

RÈGLE D'EXPÉRIENCE LONGUE:
Si une expérience source contient des sous-sections ou projets détaillés dans sa zone source, ils doivent rester attachés à cette expérience tant que le template n'impose pas une autre destination.

EXPERIENCE_SOURCE_BLOCKS:
{json.dumps(experience_source_blocks, ensure_ascii=False, indent=2)}

CV SOURCE TEXTE:
{source_text}
"""

    verification_response = client.chat.completions.create(
        model=model_name,
        messages=[
            {
                "role": "system",
                "content": (
                    "Tu es un vérificateur de JSON contractuel. "
                    "Tu corriges la structure et l'exhaustivité, sans inventer d'information."
                ),
            },
            {
                "role": "user",
                "content": verification_prompt,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0.0,
    )
    verified_content = verification_response.choices[0].message.content or "{}"
    verification_parse_error: str | None = None
    try:
        final_payload = json.loads(verified_content)
    except json.JSONDecodeError as exc:
        verification_parse_error = str(exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Targeted generation verifier returned invalid JSON: {exc}",
        ) from exc

    if isinstance(final_payload, dict) and "data" not in final_payload:
        candidate_roots = set(final_payload.keys())
        contract_roots = set(template_contract.keys())
        if candidate_roots <= contract_roots:
            final_payload = {
                "data": final_payload,
                "placeholder_values": draft_payload.get("placeholder_values", {}),
                "evidence": draft_payload.get("evidence", {}),
                "omissions": draft_payload.get("omissions", []),
            }

    if isinstance(final_payload, dict):
        verification_payload_snapshot = deepcopy(final_payload)
        final_payload.setdefault("_provider", provider_name)
        final_payload.setdefault("_model", model_name)
        if trace_enabled:
            final_payload["_llm_trace_payload"] = {
                "provider": provider_name,
                "model": model_name,
                "generation_prompt": generation_prompt,
                "generation_response_raw": draft_content,
                "generation_response_parsed": draft_payload,
                "generation_parse_error": draft_parse_error,
                "verification_prompt": verification_prompt,
                "verification_response_raw": verified_content,
                "verification_response_parsed": verification_payload_snapshot,
                "verification_parse_error": verification_parse_error,
            }
    return final_payload


def _get_generation_client() -> tuple[OpenAI, str, str]:
    client, selection = get_chat_client_for_process("company_cv_generation")
    provider_names = {
        "openai": "OpenAI",
        "xai": "xAI",
        "mistral": "Mistral AI",
    }
    return client, provider_names.get(selection.provider, selection.provider), selection.model


def _validate_placeholder_values(
    *,
    generation_payload: dict[str, Any],
    slot_definitions: list[dict[str, Any]],
    source_text: str,
    helper_json: dict[str, Any],
    canonical_payload: dict[str, Any],
) -> dict[str, str]:
    raw_values = generation_payload.get("placeholder_values") or {}
    if not isinstance(raw_values, dict):
        return {}

    allowed = {
        str(slot.get("placeholder") or "")
        for slot in slot_definitions
        if str(slot.get("placeholder") or "")
    }
    source_text_normalized = _normalize_text(source_text)
    helper_json_text = _normalize_text(json.dumps(helper_json, ensure_ascii=False))
    canonical_json_text = _normalize_text(json.dumps(_evidence_canonical_payload(canonical_payload), ensure_ascii=False))

    validated: dict[str, str] = {}
    for key, value in raw_values.items():
        placeholder = str(key or "").strip()
        if not placeholder or placeholder not in allowed or not _allow_direct_placeholder_override(placeholder):
            continue
        text = str(value or "").strip()
        if not text:
            continue
        normalized_text = _normalize_text(text)
        if normalized_text in source_text_normalized or normalized_text in helper_json_text or normalized_text in canonical_json_text:
            validated[placeholder] = text
    return validated


def _allow_direct_placeholder_override(placeholder: str) -> bool:
    return any(pattern.match(placeholder) for pattern in DIRECT_PLACEHOLDER_OVERRIDE_PATTERNS)


def _evidence_canonical_payload(canonical_payload: dict[str, Any]) -> dict[str, Any]:
    payload = deepcopy(canonical_payload)
    payload.pop("generation_guidance", None)
    return payload


def _build_placeholder_candidate_values(
    *,
    data: Any,
    slot_definitions: list[dict[str, Any]],
) -> dict[str, str]:
    if not isinstance(data, dict):
        return {}

    pseudo_template = {
        "placeholder_mappings": [
            {
                "placeholder": slot.get("placeholder"),
                "status": "resolved",
                "source_path": slot.get("source_path"),
                "transform": slot.get("transform"),
                "required": slot.get("required"),
                "params": slot.get("params") or {},
            }
            for slot in slot_definitions
            if _allow_direct_placeholder_override(str(slot.get("placeholder") or ""))
        ]
    }
    render_context, _missing = build_render_context(pseudo_template, data)
    candidate_values = {
        key: str(value).strip()
        for key, value in render_context.items()
        if _allow_direct_placeholder_override(key) and str(value).strip()
    }
    _compose_multi_education_placeholder_values(
        values=candidate_values,
        data=data,
        slot_definitions=slot_definitions,
    )
    return candidate_values


def _compose_multi_education_placeholder_values(
    *,
    values: dict[str, str],
    data: dict[str, Any],
    slot_definitions: list[dict[str, Any]],
) -> None:
    exposed_placeholders = {str(slot.get("placeholder") or "") for slot in slot_definitions}
    if not {"formation_annee", "formation_diplome", "formation_etablissement"}.intersection(exposed_placeholders):
        return

    education_items = [
        item
        for item in data.get("education") or []
        if isinstance(item, dict)
        and any(str(item.get(key) or "").strip() for key in ("year", "degree", "institution"))
    ]
    if len(education_items) <= 1:
        return

    first_education = education_items[0]
    year = str(first_education.get("year") or first_education.get("end_date") or "").strip()
    degree = str(first_education.get("degree") or "").strip()
    institution = str(first_education.get("institution") or "").strip()

    if "formation_annee" in exposed_placeholders:
        values["formation_annee"] = year
    if "formation_diplome" in exposed_placeholders:
        values["formation_diplome"] = degree
    if "formation_etablissement" in exposed_placeholders:
        values["formation_etablissement"] = institution


def _compose_placeholder_values(
    *,
    baseline: dict[str, str],
    override: dict[str, str],
) -> dict[str, str]:
    merged = dict(baseline)
    merged.update(override)
    _sanitize_experience_placeholder_values(merged)
    _compact_display_placeholder_values(merged)
    return {key: value for key, value in merged.items() if str(value).strip()}


def _enrich_experience_placeholder_values_from_source_blocks(
    *,
    values: dict[str, str],
    experience_source_blocks: list[dict[str, Any]],
) -> None:
    if not values or not experience_source_blocks:
        return

    for block in experience_source_blocks:
        try:
            experience_number = int(block.get("index") or 0) + 1
        except (TypeError, ValueError):
            continue
        task_keys = sorted(
            (
                key for key in values
                if re.match(rf"^exp{experience_number}_tache\d+$", key)
            ),
            key=lambda key: int(re.search(r"(\d+)$", key).group(1)),
        )
        axe_keys = sorted(
            (
                key for key in values
                if re.match(rf"^exp{experience_number}_axe\d+$", key)
            ),
            key=lambda key: int(re.search(r"(\d+)$", key).group(1)),
        )
        target_keys = task_keys + axe_keys
        if len(target_keys) < 4:
            continue

        source_lines = _select_representative_experience_lines(
            block.get("content_lines") or [],
            limit=len(target_keys),
        )
        if len(source_lines) < min(4, len(target_keys)):
            continue
        for key, line in zip(target_keys, source_lines):
            values[key] = line


def _select_representative_experience_lines(raw_lines: list[Any], *, limit: int) -> list[str]:
    if limit <= 0:
        return []

    candidates: list[tuple[int, str, int]] = []
    seen: set[str] = set()
    for index, raw_line in enumerate(raw_lines):
        line = EXPERIENCE_BLOCK_LABEL_PATTERN.sub("", str(raw_line or "")).strip()
        line = EXPERIENCE_BULLET_PREFIX_PATTERN.sub("", line).strip()
        normalized = _normalize_matchable_text(line)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        score = _experience_line_representative_score(line, index)
        candidates.append((index, line, score))

    if len(candidates) <= limit:
        return [line for _index, line, _score in candidates]

    selected_indexes: set[int] = {candidates[0][0]}
    for reserved_pattern in (EXPERIENCE_PILOTAGE_GOVERNANCE_PATTERN, EXPERIENCE_PROJECT_EXAMPLE_PATTERN):
        reserved_candidates = [
            (index, line, score)
            for index, line, score in candidates
            if reserved_pattern.search(line)
        ]
        if reserved_candidates and len(selected_indexes) < limit:
            reserved_index, _reserved_line, _reserved_score = max(
                reserved_candidates,
                key=lambda item: (
                    1 if reserved_pattern is EXPERIENCE_PILOTAGE_GOVERNANCE_PATTERN and EXPERIENCE_PILOTAGE_LINE_PATTERN.search(item[1]) else 0,
                    item[2],
                    -item[0],
                ),
            )
            selected_indexes.add(reserved_index)

    for index, _line, score in sorted(candidates, key=lambda item: (-item[2], item[0])):
        if score <= 0:
            continue
        selected_indexes.add(index)
        if len(selected_indexes) >= limit:
            break

    for index, _line, _score in candidates:
        if len(selected_indexes) >= limit:
            break
        selected_indexes.add(index)

    return [
        line
        for index, line, _score in candidates
        if index in selected_indexes
    ][:limit]


def _experience_line_representative_score(line: str, index: int) -> int:
    score = 10 if index < 4 else 0
    for pattern, weight in EXPERIENCE_REPRESENTATIVE_LINE_PATTERNS:
        if pattern.search(line):
            score += weight
    return score


def _sanitize_experience_placeholder_values(values: dict[str, str]) -> None:
    experience_indices = sorted({
        int(match.group(1))
        for key in values
        for match in [re.match(r"^exp(\d+)_", key)]
        if match
    })

    for exp_index in experience_indices:
        if exp_index > 3:
            values.pop(f"exp{exp_index}_poste", None)
            values.pop(f"exp{exp_index}_entreprise", None)
            values.pop(f"exp{exp_index}_periode", None)
            values.pop(f"exp{exp_index}_role", None)
            values.pop(f"exp{exp_index}_entreprise_full", None)
            values.pop(f"exp{exp_index}_periode_full", None)

        context_key = f"exp{exp_index}_contexte"
        context_value = _normalize_text(str(values.get(context_key) or ""))

        period_full_key = f"exp{exp_index}_periode_full"
        period_full_value = str(values.get(period_full_key) or "").strip()
        if period_full_value:
            values[period_full_key] = _compact_period_label(period_full_value)

        task_keys = sorted(
            (
                key for key in values
                if re.match(rf"^exp{exp_index}_tache\d+$", key)
            ),
            key=lambda key: int(re.search(r"(\d+)$", key).group(1)),
        )
        task_values = [
            str(values.get(key) or "").strip()
            for key in task_keys
            if str(values.get(key) or "").strip()
        ]
        filtered_tasks = _dedupe_placeholder_strings(task_values, blocked={context_value})
        for key, value in zip(task_keys, filtered_tasks):
            values[key] = value
        for key in task_keys[len(filtered_tasks):]:
            values.pop(key, None)

        task_blocked = {context_value, *(_normalize_text(value) for value in filtered_tasks)}
        axe_keys = sorted(
            (
                key for key in values
                if re.match(rf"^exp{exp_index}_axe\d+$", key)
            ),
            key=lambda key: int(re.search(r"(\d+)$", key).group(1)),
        )
        axe_values = [
            str(values.get(key) or "").strip()
            for key in axe_keys
            if str(values.get(key) or "").strip()
        ]
        filtered_axes = _dedupe_placeholder_strings(axe_values, blocked=task_blocked)
        for key, value in zip(axe_keys, filtered_axes):
            values[key] = value
        for key in axe_keys[len(filtered_axes):]:
            values.pop(key, None)

        point_key = f"exp{exp_index}_point_cle"
        point_value = str(values.get(point_key) or "").strip()
        if point_value and _normalize_text(point_value) in task_blocked.union(_normalize_text(value) for value in filtered_axes):
            values.pop(point_key, None)


def _dedupe_placeholder_strings(values: list[str], *, blocked: set[str]) -> list[str]:
    seen = set(blocked)
    deduped: list[str] = []
    for value in values:
        key = _normalize_text(value)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _compact_display_placeholder_values(values: dict[str, str]) -> None:
    compact_specs = {
        "competences_metiers": 10,
        "tech_data_bi": 6,
        "tech_dev": 4,
        "tech_cloud": 4,
    }
    for key, max_items in compact_specs.items():
        value = str(values.get(key) or "").strip()
        if not value:
            continue
        values[key] = _compact_comma_separated_value(value, max_items=max_items)


def _compact_comma_separated_value(value: str, *, max_items: int) -> str:
    items = [part.strip() for part in value.split(",") if part.strip()]
    seen: set[str] = set()
    compact: list[str] = []
    for item in items:
        key = _normalize_text(item)
        if not key or key in seen:
            continue
        seen.add(key)
        compact.append(item)
        if len(compact) >= max_items:
            break
    return ", ".join(compact)


def _compact_period_label(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\bPoste actuel\b", "Actuel", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text)
    return text


def _normalize_render_context_placeholders(render_context: dict[str, Any]) -> None:
    degree = str(render_context.get("formation_diplome") or "").strip()
    institution = str(render_context.get("formation_etablissement") or "").strip()
    if degree and institution and "\n" not in degree and "\n" not in institution and not degree.endswith((" -", " –", "-", "–")):
        render_context["formation_diplome"] = f"{degree} – "

    for key, value in list(render_context.items()):
        match = re.match(r"^exp(\d+)_(poste|entreprise|periode)$", key)
        if not match:
            continue

        exp_index = int(match.group(1))
        field_name = match.group(2)

        if field_name == "periode":
            compact_value = _compact_period_label(str(value or ""))
            if compact_value != str(value or ""):
                render_context[key] = compact_value

        if exp_index > 2:
            render_context[key] = ""


def _validate_generation_payload(
    *,
    generation_payload: dict[str, Any],
    template_contract: dict[str, Any],
    group_definitions: dict[str, Any],
    slot_definitions: list[dict[str, Any]],
    source_text: str,
    helper_json: dict[str, Any],
    canonical_payload: dict[str, Any],
    experience_source_blocks: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    data = generation_payload.get("data")
    evidence = generation_payload.get("evidence")
    omissions = generation_payload.get("omissions") or []

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Targeted generation parser returned an invalid 'data' payload.",
        )
    if not isinstance(evidence, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Targeted generation parser returned an invalid 'evidence' payload.",
        )
    if not isinstance(omissions, list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Targeted generation parser returned an invalid 'omissions' payload.",
        )

    _apply_required_structured_fallbacks(
        data=data,
        evidence=evidence,
        omissions=omissions,
        slot_definitions=slot_definitions,
        helper_json=helper_json,
        canonical_payload=canonical_payload,
    )
    _backfill_missing_structure_from_canonical(
        data=data,
        template_contract=template_contract,
        group_definitions=group_definitions,
        canonical_payload=canonical_payload,
    )
    _enforce_minimum_collection_counts(
        data=data,
        template_contract=template_contract,
        canonical_payload=canonical_payload,
        helper_json=helper_json,
    )
    _enforce_experience_source_block_density(
        data=data,
        experience_source_blocks=experience_source_blocks or [],
    )

    _validate_contract_shape(data, template_contract, group_definitions)

    source_text_normalized = _normalize_text(source_text)
    helper_json_text = _normalize_text(json.dumps(helper_json, ensure_ascii=False))
    canonical_json_text = _normalize_text(json.dumps(_evidence_canonical_payload(canonical_payload), ensure_ascii=False))

    for path, value in list(_iter_non_empty_leaf_values(data)):
        is_required = _is_required_contract_path(path, slot_definitions)
        semantic_issue = _semantic_validation_reason(path, value, data)
        if semantic_issue is not None:
            fallback_evidence = _build_required_evidence_fallback(
                path=path,
                current_value=value,
                helper_json=helper_json,
                canonical_payload=canonical_payload,
                allow_override=True,
            )
            if fallback_evidence is not None:
                fallback_value = _get_fallback_value(
                    path=path,
                    helper_json=helper_json,
                    canonical_payload=canonical_payload,
                )
                if not _is_missing_contract_value(fallback_value):
                    _set_contract_value(data, path, fallback_value)
                    evidence[path] = fallback_evidence
                    omissions.append({"contract_path": path, "reason": semantic_issue})
                    continue
            if is_required:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid semantic value for generated field: {path}",
                )
            _clear_contract_value(data, path)
            omissions.append({"contract_path": path, "reason": semantic_issue})
            continue

        evidence_key, evidence_item = _lookup_evidence_item(evidence, path)
        if isinstance(evidence_item, dict) and evidence_key != path:
            evidence[path] = dict(evidence_item)
        if not isinstance(evidence_item, dict):
            inferred_evidence = _infer_evidence_from_value(
                path=path,
                value=value,
                source_text_normalized=source_text_normalized,
                helper_json_text=helper_json_text,
                canonical_json_text=canonical_json_text,
            )
            if inferred_evidence is not None:
                evidence[path] = inferred_evidence
                continue
            fallback_evidence, fallback_value = _resolve_generation_evidence_fallback(
                path=path,
                current_value=value,
                helper_json=helper_json,
                canonical_payload=canonical_payload,
                source_text=source_text,
                experience_source_blocks=experience_source_blocks or [],
                allow_override=is_required,
            )
            if fallback_evidence is not None:
                _set_contract_value(data, path, fallback_value)
                evidence[path] = fallback_evidence
                continue
            if is_required:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing evidence for generated field: {path}",
                )
            _clear_contract_value(data, path)
            omissions.append({"contract_path": path, "reason": "missing_evidence"})
            continue
        source_quote = str(evidence_item.get("source_quote") or "").strip()
        source_type = str(evidence_item.get("source_type") or "").strip()
        confidence_mode = str(evidence_item.get("confidence_mode") or "").strip()

        if confidence_mode not in {"explicit", "derived", "inferred"}:
            inferred_evidence = _infer_evidence_from_value(
                path=path,
                value=value,
                source_text_normalized=source_text_normalized,
                helper_json_text=helper_json_text,
                canonical_json_text=canonical_json_text,
            )
            if inferred_evidence is not None:
                evidence[path] = inferred_evidence
                continue
            fallback_evidence, fallback_value = _resolve_generation_evidence_fallback(
                path=path,
                current_value=value,
                helper_json=helper_json,
                canonical_payload=canonical_payload,
                source_text=source_text,
                experience_source_blocks=experience_source_blocks or [],
                allow_override=is_required,
            )
            if fallback_evidence is not None:
                _set_contract_value(data, path, fallback_value)
                evidence[path] = fallback_evidence
                continue
            if is_required:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid confidence mode for generated field: {path}",
                )
            _clear_contract_value(data, path)
            omissions.append({"contract_path": path, "reason": "invalid_confidence_mode"})
            continue
        if not source_quote:
            inferred_evidence = _infer_evidence_from_value(
                path=path,
                value=value,
                source_text_normalized=source_text_normalized,
                helper_json_text=helper_json_text,
                canonical_json_text=canonical_json_text,
            )
            if inferred_evidence is not None:
                evidence[path] = inferred_evidence
                continue
            fallback_evidence, fallback_value = _resolve_generation_evidence_fallback(
                path=path,
                current_value=value,
                helper_json=helper_json,
                canonical_payload=canonical_payload,
                source_text=source_text,
                experience_source_blocks=experience_source_blocks or [],
                allow_override=is_required,
            )
            if fallback_evidence is not None:
                _set_contract_value(data, path, fallback_value)
                evidence[path] = fallback_evidence
                continue
            if is_required:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Missing source quote for generated field: {path}",
                )
            _clear_contract_value(data, path)
            omissions.append({"contract_path": path, "reason": "missing_source_quote"})
            continue

        normalized_quote = _normalize_text(source_quote)
        if source_type == "original_text":
            if normalized_quote not in source_text_normalized:
                inferred_evidence = _infer_evidence_from_value(
                    path=path,
                    value=value,
                    source_text_normalized=source_text_normalized,
                    helper_json_text=helper_json_text,
                    canonical_json_text=canonical_json_text,
                )
                if inferred_evidence is not None:
                    evidence[path] = inferred_evidence
                    continue
                fallback_evidence, fallback_value = _resolve_generation_evidence_fallback(
                    path=path,
                    current_value=value,
                    helper_json=helper_json,
                    canonical_payload=canonical_payload,
                    source_text=source_text,
                    experience_source_blocks=experience_source_blocks or [],
                    allow_override=is_required,
                )
                if fallback_evidence is not None:
                    _set_contract_value(data, path, fallback_value)
                    evidence[path] = fallback_evidence
                    continue
                if is_required:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Evidence quote not found in original CV text for field: {path}",
                    )
                _clear_contract_value(data, path)
                omissions.append({"contract_path": path, "reason": "quote_not_found_in_original_text"})
                continue
        elif source_type == "parsed_json":
            if normalized_quote not in helper_json_text:
                inferred_evidence = _infer_evidence_from_value(
                    path=path,
                    value=value,
                    source_text_normalized=source_text_normalized,
                    helper_json_text=helper_json_text,
                    canonical_json_text=canonical_json_text,
                )
                if inferred_evidence is not None:
                    evidence[path] = inferred_evidence
                    continue
                fallback_evidence, fallback_value = _resolve_generation_evidence_fallback(
                    path=path,
                    current_value=value,
                    helper_json=helper_json,
                    canonical_payload=canonical_payload,
                    source_text=source_text,
                    experience_source_blocks=experience_source_blocks or [],
                    allow_override=is_required,
                )
                if fallback_evidence is not None:
                    _set_contract_value(data, path, fallback_value)
                    evidence[path] = fallback_evidence
                    continue
                if is_required:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Evidence quote not found in parsed JSON helper for field: {path}",
                    )
                _clear_contract_value(data, path)
                omissions.append({"contract_path": path, "reason": "quote_not_found_in_helper_json"})
                continue
        elif source_type == "system_context":
            if normalized_quote not in canonical_json_text:
                inferred_evidence = _infer_evidence_from_value(
                    path=path,
                    value=value,
                    source_text_normalized=source_text_normalized,
                    helper_json_text=helper_json_text,
                    canonical_json_text=canonical_json_text,
                )
                if inferred_evidence is not None:
                    evidence[path] = inferred_evidence
                    continue
                fallback_evidence, fallback_value = _resolve_generation_evidence_fallback(
                    path=path,
                    current_value=value,
                    helper_json=helper_json,
                    canonical_payload=canonical_payload,
                    source_text=source_text,
                    experience_source_blocks=experience_source_blocks or [],
                    allow_override=is_required,
                )
                if fallback_evidence is not None:
                    _set_contract_value(data, path, fallback_value)
                    evidence[path] = fallback_evidence
                    continue
                if is_required:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Evidence quote not found in system context for field: {path}",
                    )
                _clear_contract_value(data, path)
                omissions.append({"contract_path": path, "reason": "quote_not_found_in_system_context"})
                continue
        else:
            inferred_evidence = _infer_evidence_from_value(
                path=path,
                value=value,
                source_text_normalized=source_text_normalized,
                helper_json_text=helper_json_text,
                canonical_json_text=canonical_json_text,
            )
            if inferred_evidence is not None:
                evidence[path] = inferred_evidence
                continue
            fallback_evidence, fallback_value = _resolve_generation_evidence_fallback(
                path=path,
                current_value=value,
                helper_json=helper_json,
                canonical_payload=canonical_payload,
                source_text=source_text,
                experience_source_blocks=experience_source_blocks or [],
                allow_override=is_required,
            )
            if fallback_evidence is not None:
                _set_contract_value(data, path, fallback_value)
                evidence[path] = fallback_evidence
                continue
            if is_required:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid source type for generated field: {path}",
                )
            _clear_contract_value(data, path)
            omissions.append({"contract_path": path, "reason": "invalid_source_type"})
            continue

    _postprocess_generated_contract(
        data=data,
        evidence=evidence,
        group_definitions=group_definitions,
        source_text=source_text,
    )

    return data, evidence, omissions


def _validate_contract_shape(
    data: Any,
    skeleton: Any,
    group_definitions: dict[str, Any],
    *,
    path: str = "",
) -> None:
    if isinstance(skeleton, dict):
        if not isinstance(data, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Contract payload must be an object for path '{path or 'root'}'.",
            )
        unknown_keys = set(data.keys()) - set(skeleton.keys())
        if unknown_keys:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Targeted generation parser returned unsupported keys: {sorted(unknown_keys)}",
            )
        for key, value in data.items():
            _validate_contract_shape(
                value,
                skeleton[key],
                group_definitions,
                path=f"{path}.{key}" if path else key,
            )
        return

    if isinstance(skeleton, list):
        if not isinstance(data, list):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Contract payload must be a list for path '{path or 'list'}'.",
            )
        if not skeleton:
            return
        for index, item in enumerate(data):
            next_path = f"{path}[{index}]" if path else f"[{index}]"
            _validate_contract_shape(item, skeleton[0], group_definitions, path=next_path)
        return

    if not isinstance(data, str):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Contract payload must use string scalar values for '{path or 'scalar'}'.",
        )


def _iter_non_empty_leaf_values(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else key
            yield from _iter_non_empty_leaf_values(item, next_prefix)
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            next_prefix = f"{prefix}[{index}]"
            yield from _iter_non_empty_leaf_values(item, next_prefix)
        return
    if isinstance(value, str) and value.strip():
        yield prefix, value


def _normalize_text(value: str) -> str:
    return " ".join((value or "").split()).strip().lower()


def _normalize_matchable_text(value: str) -> str:
    normalized = _normalize_text(value)
    normalized = re.sub(r"[^\w\s]", " ", normalized, flags=re.UNICODE)
    return " ".join(normalized.split()).strip()


def _apply_required_structured_fallbacks(
    *,
    data: dict[str, Any],
    evidence: dict[str, Any],
    omissions: list[dict[str, Any]],
    slot_definitions: list[dict[str, Any]],
    helper_json: dict[str, Any],
    canonical_payload: dict[str, Any],
) -> None:
    for slot in slot_definitions:
        if not bool(slot.get("required")):
            continue
        contract_path = str(slot.get("contract_path") or "")
        if not contract_path or "[]" in contract_path:
            continue
        current_value = _get_contract_value(data, contract_path)
        if not _is_missing_contract_value(current_value):
            continue

        helper_value = _get_contract_value(helper_json, contract_path)
        if not _is_missing_contract_value(helper_value):
            if not _should_accept_fallback_value(contract_path, helper_value):
                continue
            _set_contract_value(data, contract_path, helper_value)
            evidence[contract_path] = {
                "source_quote": _stringify_for_evidence(helper_value),
                "source_type": "parsed_json",
                "confidence_mode": "derived",
                "reason_if_empty": "",
            }
            omissions.append({"contract_path": contract_path, "reason": "filled_from_parsed_json_helper"})
            continue

        canonical_value = _get_contract_value(canonical_payload, contract_path)
        if not _is_missing_contract_value(canonical_value):
            if not _should_accept_fallback_value(contract_path, canonical_value):
                continue
            _set_contract_value(data, contract_path, canonical_value)
            evidence[contract_path] = {
                "source_quote": _stringify_for_evidence(canonical_value),
                "source_type": "system_context",
                "confidence_mode": "derived",
                "reason_if_empty": "",
            }
            omissions.append({"contract_path": contract_path, "reason": "filled_from_system_context"})


def _get_contract_value(data: Any, path: str) -> Any:
    current = data
    steps: list[Any] = []
    for segment in path.split("."):
        if "[" not in segment:
            steps.append(segment)
            continue
        base, remainder = segment.split("[", 1)
        if base:
            steps.append(base)
        for raw_index in re.findall(r"\[(\d+)\]", f"[{remainder}"):
            steps.append(int(raw_index))

    for step in steps:
        if isinstance(step, int):
            if not isinstance(current, list) or step >= len(current):
                return None
            current = current[step]
        else:
            if not isinstance(current, dict) or step not in current:
                return None
            current = current[step]
    return current


def _set_contract_value(data: Any, path: str, value: Any) -> None:
    steps: list[Any] = []
    for segment in path.split("."):
        if "[" not in segment:
            steps.append(segment)
            continue
        base, remainder = segment.split("[", 1)
        if base:
            steps.append(base)
        for raw_index in re.findall(r"\[(\d+)\]", f"[{remainder}"):
            steps.append(int(raw_index))

    current = data
    for index, step in enumerate(steps):
        is_last = index == len(steps) - 1
        if isinstance(step, int):
            if not isinstance(current, list):
                return
            while len(current) <= step:
                current.append("")
            if is_last:
                current[step] = value
                return
            if not isinstance(current[step], (dict, list)):
                next_step = steps[index + 1]
                current[step] = [] if isinstance(next_step, int) else {}
            current = current[step]
        else:
            if not isinstance(current, dict):
                return
            if is_last:
                current[step] = value
                return
            if step not in current or not isinstance(current[step], (dict, list)):
                next_step = steps[index + 1]
                current[step] = [] if isinstance(next_step, int) else {}
            current = current[step]


def _is_missing_contract_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, list):
        return not any(not _is_missing_contract_value(item) for item in value)
    if isinstance(value, dict):
        return not any(not _is_missing_contract_value(item) for item in value.values())
    return False


def _stringify_for_evidence(value: Any) -> str:
    if isinstance(value, list):
        return " | ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        return " | ".join(str(item).strip() for item in value.values() if str(item).strip())
    return str(value or "").strip()


def _build_required_evidence_fallback(
    *,
    path: str,
    current_value: Any,
    helper_json: dict[str, Any],
    canonical_payload: dict[str, Any],
    allow_override: bool = False,
) -> dict[str, Any] | None:
    helper_value = _get_contract_value(helper_json, path)
    if (
        not _is_missing_contract_value(helper_value)
        and _should_accept_fallback_value(path, helper_value)
        and (
            allow_override
            or _normalize_text(_stringify_for_evidence(helper_value)) == _normalize_text(_stringify_for_evidence(current_value))
        )
    ):
        return {
            "source_quote": _stringify_for_evidence(helper_value),
            "source_type": "parsed_json",
            "confidence_mode": "derived",
            "reason_if_empty": "",
        }

    canonical_value = _get_contract_value(canonical_payload, path)
    if not _is_missing_contract_value(canonical_value) and _should_accept_fallback_value(path, canonical_value):
        normalized_current = _normalize_text(_stringify_for_evidence(current_value))
        normalized_canonical = _normalize_text(_stringify_for_evidence(canonical_value))
        if allow_override or not normalized_current or normalized_current == normalized_canonical:
            return {
                "source_quote": _stringify_for_evidence(canonical_value),
                "source_type": "system_context",
                "confidence_mode": "derived",
                "reason_if_empty": "",
            }
    return None


def _get_fallback_value(
    *,
    path: str,
    helper_json: dict[str, Any],
    canonical_payload: dict[str, Any],
) -> Any:
    helper_value = _get_contract_value(helper_json, path)
    if not _is_missing_contract_value(helper_value) and _should_accept_fallback_value(path, helper_value):
        return helper_value
    canonical_value = _get_contract_value(canonical_payload, path)
    if _should_accept_fallback_value(path, canonical_value):
        return canonical_value
    return None


_EXPERIENCE_SOURCE_EVIDENCE_FIELDS = {
    "company",
    "company_full",
    "period",
    "period_full",
    "position",
    "role",
}


def _resolve_generation_evidence_fallback(
    *,
    path: str,
    current_value: Any,
    helper_json: dict[str, Any],
    canonical_payload: dict[str, Any],
    source_text: str,
    experience_source_blocks: list[dict[str, Any]],
    allow_override: bool,
) -> tuple[dict[str, Any] | None, Any]:
    fallback_evidence = _build_required_evidence_fallback(
        path=path,
        current_value=current_value,
        helper_json=helper_json,
        canonical_payload=canonical_payload,
        allow_override=allow_override,
    )
    if fallback_evidence is not None:
        fallback_value = _get_fallback_value(
            path=path,
            helper_json=helper_json,
            canonical_payload=canonical_payload,
        )
        if _is_missing_contract_value(fallback_value):
            fallback_value = current_value
        return fallback_evidence, fallback_value

    fallback_evidence = _build_experience_source_evidence_fallback(
        path=path,
        current_value=current_value,
        experience_source_blocks=experience_source_blocks,
    )
    if fallback_evidence is not None:
        return fallback_evidence, current_value

    fallback_evidence = _build_source_text_period_evidence_fallback(
        path=path,
        current_value=current_value,
        source_text=source_text,
    )
    if fallback_evidence is not None:
        return fallback_evidence, current_value

    return None, None


def _build_experience_source_evidence_fallback(
    *,
    path: str,
    current_value: Any,
    experience_source_blocks: list[dict[str, Any]],
) -> dict[str, Any] | None:
    match = re.match(r"^experiences\[(\d+)\]\.([a-z_]+)$", path or "")
    if not match:
        return None
    index = int(match.group(1))
    field_name = match.group(2)
    if field_name not in _EXPERIENCE_SOURCE_EVIDENCE_FIELDS:
        return None

    quote = _stringify_for_evidence(current_value)
    normalized_quote = _normalize_text(quote)
    if not normalized_quote:
        return None

    block = next((item for item in experience_source_blocks if int(item.get("index") or -1) == index), None)
    if not isinstance(block, dict):
        return None

    source_quote = _find_experience_source_quote(
        block=block,
        field_name=field_name,
        quote=quote,
    )
    if source_quote is None:
        return None

    return {
        "source_quote": source_quote,
        "source_type": "original_text",
        "confidence_mode": "derived",
        "reason_if_empty": "",
    }


def _find_experience_source_quote(
    *,
    block: dict[str, Any],
    field_name: str,
    quote: str,
) -> str | None:
    normalized_quote = _normalize_text(quote)
    block_lines = [
        str(line).strip()
        for line in str(block.get("block_text") or "").splitlines()
        if str(line).strip()
    ]
    block_lines.extend(
        str(line).strip()
        for line in block.get("content_lines") or []
        if str(line).strip()
    )

    for line in block_lines:
        if normalized_quote and normalized_quote in _normalize_text(line):
            return line

    if field_name in {"period", "period_full"}:
        period_tokens = _extract_period_tokens(quote)
        if not period_tokens:
            return None
        for line in block_lines:
            line_tokens = _extract_period_tokens(line)
            if len(period_tokens & line_tokens) >= min(2, len(period_tokens)):
                return line
        return None

    block_value = str(block.get(field_name) or "").strip()
    if block_value and _normalize_text(block_value) == normalized_quote:
        return block_value
    return None


def _build_source_text_period_evidence_fallback(
    *,
    path: str,
    current_value: Any,
    source_text: str,
) -> dict[str, Any] | None:
    match = re.match(r"^experiences\[\d+\]\.(period|period_full)$", path or "")
    if not match:
        return None

    period_tokens = _extract_period_tokens(_stringify_for_evidence(current_value))
    if not period_tokens:
        return None

    for raw_line in re.split(r"[\r\n]+", source_text or ""):
        line = " ".join(str(raw_line).split()).strip()
        if not line:
            continue
        line_tokens = _extract_period_tokens(line)
        if len(period_tokens & line_tokens) >= min(2, len(period_tokens)):
            return {
                "source_quote": line,
                "source_type": "original_text",
                "confidence_mode": "derived",
                "reason_if_empty": "",
            }
    return None


def _normalize_contract_path(path: str) -> str:
    normalized = re.sub(r"\[\d+\]", "[]", path or "")
    normalized = normalized.replace(".[]", "[]")
    return normalized


def _is_required_contract_path(path: str, slot_definitions: list[dict[str, Any]]) -> bool:
    normalized_path = _normalize_contract_path(path)
    for slot in slot_definitions:
        contract_path = str(slot.get("contract_path") or "")
        if not contract_path:
            continue
        if (
            normalized_path == contract_path
            or normalized_path == f"{contract_path}[]"
            or normalized_path.startswith(f"{contract_path}[")
        ):
            return bool(slot.get("required"))
    return False


def _clear_contract_value(data: Any, path: str) -> None:
    steps: list[Any] = []
    for segment in path.split("."):
        if "[" not in segment:
            steps.append(segment)
            continue
        base, remainder = segment.split("[", 1)
        if base:
            steps.append(base)
        for raw_index in re.findall(r"\[(\d+)\]", f"[{remainder}"):
            steps.append(int(raw_index))

    current = data
    parent = None
    parent_key: Any = None
    for step in steps:
        parent = current
        parent_key = step
        if isinstance(step, int):
            if not isinstance(current, list) or step >= len(current):
                return
            current = current[step]
        else:
            if not isinstance(current, dict) or step not in current:
                return
            current = current[step]

    if isinstance(parent, list) and isinstance(parent_key, int) and parent_key < len(parent):
        parent[parent_key] = ""
    elif isinstance(parent, dict) and isinstance(parent_key, str):
        parent[parent_key] = ""


def _build_coverage_summary(
    *,
    template_contract: dict[str, Any],
    generated_data: dict[str, Any],
    omissions: list[dict[str, Any]],
) -> dict[str, Any]:
    requested = sum(1 for _ in _iter_leaf_paths(template_contract))
    filled = sum(1 for _path, _value in _iter_non_empty_leaf_values(generated_data))
    return {
        "requested_slots": requested,
        "filled_slots": filled,
        "omitted_slots": len(omissions),
        "coverage_ratio": round((filled / requested), 4) if requested else 1.0,
    }


def _build_semantic_template_profile(
    *,
    template_contract: dict[str, Any],
    group_definitions: dict[str, Any],
    template_guidance: dict[str, Any],
) -> dict[str, Any]:
    section_slot_map = template_guidance.get("section_slot_map")
    if not isinstance(section_slot_map, dict):
        section_slot_map = {}

    experiences_contract = template_contract.get("experiences")
    experience_item = experiences_contract[0] if isinstance(experiences_contract, list) and experiences_contract else {}
    if not isinstance(experience_item, dict):
        experience_item = {}

    skills_contract = template_contract.get("skills")
    skills_keys = sorted(skills_contract.keys()) if isinstance(skills_contract, dict) else []

    available_sections = []
    for section_id, root_name in (
        ("identity", "identity"),
        ("key_skills", "skills"),
        ("technical_skills", "skills"),
        ("education_certifications", "education"),
        ("languages", "languages"),
        ("experiences", "experiences"),
    ):
        if root_name in template_contract:
            available_sections.append(section_id)

    explicit_template_sections = sorted(
        str(section_name)
        for section_name in section_slot_map.keys()
        if str(section_name).strip()
    )

    return {
        "version": SEMANTIC_BLOCK_VERSION,
        "available_sections": available_sections,
        "explicit_template_sections": explicit_template_sections,
        "skills_shape": skills_keys,
        "experience_shape": {
            "has_company_period": any(
                key in experience_item
                for key in ("company", "company_full", "period", "period_full", "start_date", "end_date")
            ),
            "has_role": any(key in experience_item for key in ("role", "position")),
            "has_context": any(key in experience_item for key in ("context", "summary")),
            "work_item_fields": [
                key
                for key in ("tasks", "highlights", "key_points")
                if isinstance(experience_item.get(key), list)
            ],
            "has_environment": "environment" in experience_item,
        },
        "repeatability": {
            "experiences": bool((group_definitions.get("experiences") or {}).get("unbounded")),
            "languages": bool((group_definitions.get("languages") or {}).get("unbounded")),
            "education": bool((group_definitions.get("education") or {}).get("unbounded")),
            "certifications": bool((group_definitions.get("certifications") or {}).get("unbounded")),
        },
        "projection_policy": {
            "mode": "prompt_guidance_and_trace_only",
            "experience_work_block": "missions_projects_realisations",
            "project_handling": (
                "Attach project-like lines to the owning experience work block when the source places them "
                "inside that experience; keep root projects only for autonomous project sections."
            ),
        },
    }


def _build_semantic_cv_blocks(canonical_context: dict[str, Any]) -> dict[str, Any]:
    identity = canonical_context.get("identity") if isinstance(canonical_context.get("identity"), dict) else {}
    skills = canonical_context.get("skills") if isinstance(canonical_context.get("skills"), dict) else {}

    return {
        "version": SEMANTIC_BLOCK_VERSION,
        "identity": {
            "full_name": _semantic_text(identity.get("full_name")),
            "title": _semantic_text(canonical_context.get("title") or identity.get("title")),
            "availability": _semantic_text(canonical_context.get("availability")),
        },
        "key_skills": _semantic_list(
            skills.get("key")
            or skills.get("domain")
            or skills.get("soft")
        ),
        "technical_skills": _semantic_skill_block(skills),
        "education_certifications": _semantic_education_certification_block(canonical_context),
        "languages": _semantic_language_block(canonical_context.get("languages")),
        "experiences": [
            _semantic_experience_block(experience)
            for experience in _semantic_dict_items(canonical_context.get("experiences"))
        ],
        "global_projects": _semantic_project_block(canonical_context.get("projects")),
        "policy": {
            "experience_work_items": "tasks + highlights + key_points, deduplicated in source order",
            "global_projects": "kept separate unless a renderer explicitly maps them into an experience block",
        },
    }


def _semantic_experience_block(experience: dict[str, Any]) -> dict[str, Any]:
    company = _semantic_text(experience.get("company_full") or experience.get("company"))
    period = _semantic_text(experience.get("period_full") or experience.get("period"))
    return {
        "company_period": " ".join(value for value in (company, period) if value).strip(),
        "role": _semantic_text(experience.get("role") or experience.get("position")),
        "context": _semantic_text(experience.get("context") or experience.get("summary")),
        "missions_projects": _semantic_deduped_list(
            _semantic_list(experience.get("tasks"))
            + _semantic_list(experience.get("highlights"))
            + _semantic_list(experience.get("key_points"))
        ),
        "environment": _semantic_text(experience.get("environment")),
    }


def _semantic_skill_block(skills: dict[str, Any]) -> list[str]:
    items = _semantic_list(skills.get("technical"))
    categories = skills.get("categories")
    if isinstance(categories, dict):
        for category, values in categories.items():
            category_items = _semantic_list(values)
            if category_items:
                items.append(f"{category}: {', '.join(category_items)}")
    return _semantic_deduped_list(items)


def _semantic_education_certification_block(canonical_context: dict[str, Any]) -> list[str]:
    items: list[str] = []
    for education in _semantic_dict_items(canonical_context.get("education")):
        year = _semantic_text(education.get("year") or education.get("end_date"))
        degree = _semantic_text(education.get("degree"))
        institution = _semantic_text(education.get("institution"))
        line = " - ".join(value for value in (year, degree, institution) if value)
        if line:
            items.append(line)
    for certification in _semantic_dict_items(canonical_context.get("certifications")):
        year = _semantic_text(certification.get("year"))
        name = _semantic_text(certification.get("name"))
        issuer = _semantic_text(certification.get("issuer"))
        line = " - ".join(value for value in (year, name, issuer) if value)
        if line:
            items.append(line)
    return _semantic_deduped_list(items)


def _semantic_language_block(languages: Any) -> list[str]:
    items: list[str] = []
    for language in _semantic_dict_items(languages):
        name = _semantic_text(language.get("name"))
        level = _semantic_text(language.get("level"))
        if name and level:
            items.append(f"{name}: {level}")
        elif name:
            items.append(name)
    return _semantic_deduped_list(items)


def _semantic_project_block(projects: Any) -> list[str]:
    items: list[str] = []
    for project in _semantic_dict_items(projects):
        name = _semantic_text(project.get("name"))
        description = _semantic_text(project.get("description"))
        role = _semantic_text(project.get("role"))
        technologies = ", ".join(_semantic_list(project.get("technologies")))
        line = " - ".join(value for value in (name, role, description, technologies) if value)
        if line:
            items.append(line)
    return _semantic_deduped_list(items)


def _semantic_dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _semantic_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [
            text
            for text in (_semantic_text(item) for item in value)
            if text
        ]
    text = _semantic_text(value)
    return [text] if text else []


def _semantic_text(value: Any) -> str:
    if isinstance(value, dict):
        return _stringify_for_evidence(value)
    if isinstance(value, list):
        return _stringify_for_evidence(value)
    return str(value or "").strip()


def _semantic_deduped_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        key = _normalize_text(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


def _enforce_minimum_collection_counts(
    *,
    data: dict[str, Any],
    template_contract: dict[str, Any],
    canonical_payload: dict[str, Any],
    helper_json: dict[str, Any],
) -> None:
    collection_roots = ("experiences", "education", "certifications", "languages")

    for root_name in collection_roots:
        contract_root = template_contract.get(root_name)
        if not isinstance(contract_root, list) or not contract_root:
            continue

        generated_list = data.get(root_name)
        if not isinstance(generated_list, list):
            generated_list = []
            data[root_name] = generated_list

        exemplar = contract_root[0]
        canonical_list = canonical_payload.get(root_name) if isinstance(canonical_payload.get(root_name), list) else []
        helper_list = helper_json.get(root_name) if isinstance(helper_json.get(root_name), list) else []
        projected_source_items = [
            _project_value_to_contract_shape(item, exemplar, path=f"{root_name}[{index}]")
            for index, item in enumerate(canonical_list)
        ]
        projected_source_items = [item for item in projected_source_items if not _is_missing_contract_value(item)]
        if not projected_source_items:
            projected_source_items = [
                _project_value_to_contract_shape(item, exemplar, path=f"{root_name}[{index}]")
                for index, item in enumerate(helper_list)
            ]
            projected_source_items = [item for item in projected_source_items if not _is_missing_contract_value(item)]
        target_count = len(projected_source_items)
        if target_count <= len(generated_list):
            continue

        for index in range(target_count):
            projected = projected_source_items[index]
            if index >= len(generated_list):
                generated_list.append(projected)
                continue
            if _is_missing_contract_value(generated_list[index]):
                generated_list[index] = projected
                continue
            _merge_missing_values_from_source(
                generated_list[index],
                exemplar,
                projected,
                group_definitions={},
                path=f"{root_name}[{index}]",
            )

        if len(generated_list) < target_count:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Targeted generation lost distinct {root_name} entries: "
                    f"expected at least {target_count}, got {len(generated_list)}."
                ),
            )


def _enforce_experience_source_block_density(
    *,
    data: dict[str, Any],
    experience_source_blocks: list[dict[str, Any]],
) -> None:
    experiences = data.get("experiences")
    if not isinstance(experiences, list) or not experiences or not experience_source_blocks:
        return

    for block in experience_source_blocks:
        index = int(block.get("index") or 0)
        if index >= len(experiences):
            continue
        experience = experiences[index]
        if not isinstance(experience, dict):
            continue

        context_candidate = str(block.get("context_candidate") or "").strip()
        environment_candidate = str(block.get("environment_candidate") or "").strip()
        content_lines = [
            str(line).strip()
            for line in block.get("content_lines") or []
            if str(line).strip()
        ]

        if context_candidate and _is_missing_contract_value(experience.get("context")):
            experience["context"] = context_candidate
        if environment_candidate and _is_missing_contract_value(experience.get("environment")):
            experience["environment"] = environment_candidate

        represented_lines = [
            str(experience.get("context") or ""),
            str(experience.get("environment") or ""),
            str(experience.get("role") or ""),
            str(experience.get("position") or ""),
            str(experience.get("company") or ""),
            str(experience.get("company_full") or ""),
            str(experience.get("period") or ""),
            str(experience.get("period_full") or ""),
        ]
        represented = {
            _normalize_matchable_text(line)
            for line in represented_lines
            if _normalize_matchable_text(line)
        }
        for field_name in ("tasks", "highlights", "key_points"):
            field_value = experience.get(field_name)
            if isinstance(field_value, list):
                represented_lines.extend(str(item) for item in field_value if str(item).strip())
                represented.update(
                    _normalize_matchable_text(str(item))
                    for item in field_value
                    if _normalize_matchable_text(str(item))
                )

        tasks = experience.get("tasks")
        if not isinstance(tasks, list):
            tasks = []
            experience["tasks"] = tasks

        normalized_context = _normalize_matchable_text(str(experience.get("context") or context_candidate))
        normalized_environment = _normalize_matchable_text(str(experience.get("environment") or environment_candidate))
        task_source_lines = [
            line
            for line in content_lines
            if not _is_experience_source_noise_line(line, experience)
            and _normalize_matchable_text(line)
            and _normalize_matchable_text(line) not in {normalized_context, normalized_environment}
        ]
        meaningful_source_lines: list[str] = []
        distinct_task_source_lines = {
            _normalize_matchable_text(line)
            for line in task_source_lines
            if _normalize_matchable_text(line)
        }
        for line in task_source_lines:
            normalized = _normalize_matchable_text(line)
            if not normalized or normalized not in distinct_task_source_lines:
                continue
            if normalized in represented or _line_is_semantically_represented(line, represented_lines):
                continue
            meaningful_source_lines.append(line)

        existing_task_count = sum(1 for item in tasks if str(item).strip())
        source_task_count = len(distinct_task_source_lines)
        target_task_floor = min(6, source_task_count) if source_task_count >= 5 else source_task_count
        if existing_task_count < target_task_floor:
            for line in meaningful_source_lines:
                if existing_task_count >= target_task_floor:
                    break
                tasks.append(line)
                represented.add(_normalize_matchable_text(line))
                represented_lines.append(line)
                existing_task_count += 1

        if target_task_floor and existing_task_count < target_task_floor:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Targeted generation under-represented source block for experience[{index}] "
                    "after verification; task density remained too low."
                ),
            )


def _iter_leaf_paths(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            next_prefix = f"{prefix}.{key}" if prefix else key
            yield from _iter_leaf_paths(item, next_prefix)
        return
    if isinstance(value, list):
        exemplar = value[0] if value else ""
        next_prefix = f"{prefix}[]"
        yield from _iter_leaf_paths(exemplar, next_prefix)
        return
    yield prefix


def _build_source_inventory(canonical_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "identity_present": bool((canonical_payload.get("identity") or {}).get("full_name")),
        "experience_count": len(canonical_payload.get("experiences") or []),
        "education_count": len(canonical_payload.get("education") or []),
        "language_count": len(canonical_payload.get("languages") or []),
        "certification_count": len(canonical_payload.get("certifications") or []),
        "project_count": len(canonical_payload.get("projects") or []),
        "technical_skill_count": len((canonical_payload.get("skills") or {}).get("technical") or []),
        "soft_skill_count": len((canonical_payload.get("skills") or {}).get("soft") or []),
        "domain_skill_count": len((canonical_payload.get("skills") or {}).get("domain") or []),
        "key_skill_count": len((canonical_payload.get("skills") or {}).get("key") or []),
    }


def _build_placeholder_injection_guide(slot_definitions: list[dict[str, Any]]) -> dict[str, Any]:
    scalars: list[dict[str, Any]] = []
    repeated_groups: dict[str, list[dict[str, Any]]] = {}

    for slot in slot_definitions:
        placeholder = str(slot.get("placeholder") or "")
        contract_path = str(slot.get("contract_path") or "")
        source_path = str(slot.get("source_path") or "")
        required = bool(slot.get("required"))
        normalized_group = _normalize_contract_path(contract_path).split(".", 1)[0]
        is_repeated = "[]" in _normalize_contract_path(contract_path)

        item = {
            "placeholder": placeholder,
            "contract_path": contract_path,
            "source_path": source_path,
            "required": required,
        }
        if is_repeated:
            repeated_groups.setdefault(normalized_group, []).append(item)
        else:
            scalars.append(item)

    return {
        "scalars": scalars,
        "repeated_groups": {
            key: sorted(values, key=lambda value: value["placeholder"])
            for key, values in sorted(repeated_groups.items())
        },
    }


def _infer_evidence_from_value(
    *,
    path: str,
    value: Any,
    source_text_normalized: str,
    helper_json_text: str,
    canonical_json_text: str,
) -> dict[str, Any] | None:
    quote = _stringify_for_evidence(value)
    normalized_quote = _normalize_text(quote)
    if not normalized_quote:
        return None
    if normalized_quote in source_text_normalized:
        return {
            "source_quote": quote,
            "source_type": "original_text",
            "confidence_mode": "derived",
            "reason_if_empty": "",
        }
    if normalized_quote in helper_json_text:
        return {
            "source_quote": quote,
            "source_type": "parsed_json",
            "confidence_mode": "derived",
            "reason_if_empty": "",
        }
    if normalized_quote in canonical_json_text:
        return {
            "source_quote": quote,
            "source_type": "system_context",
            "confidence_mode": "derived",
            "reason_if_empty": "",
        }
    return None


def _backfill_missing_structure_from_canonical(
    *,
    data: dict[str, Any],
    template_contract: dict[str, Any],
    group_definitions: dict[str, Any],
    canonical_payload: dict[str, Any],
) -> None:
    _merge_missing_values_from_source(
        data,
        template_contract,
        canonical_payload,
        group_definitions=group_definitions,
        path="",
    )


def _merge_missing_values_from_source(
    current_value: Any,
    skeleton: Any,
    source_value: Any,
    *,
    group_definitions: dict[str, Any],
    path: str,
) -> None:
    if isinstance(skeleton, dict):
        if not isinstance(current_value, dict):
            return
        source_dict = source_value if isinstance(source_value, dict) else {}
        for key, child_skeleton in skeleton.items():
            child_path = f"{path}.{key}" if path else key
            child_source = source_dict.get(key) if isinstance(source_dict, dict) else None
            if key not in current_value or _is_missing_contract_value(current_value.get(key)):
                projected = _project_value_to_contract_shape(child_source, child_skeleton, path=child_path)
                if not _is_missing_contract_value(projected):
                    current_value[key] = projected
                    continue
            if key in current_value:
                _merge_missing_values_from_source(
                    current_value[key],
                    child_skeleton,
                    child_source,
                    group_definitions=group_definitions,
                    path=child_path,
                )
        return

    if isinstance(skeleton, list):
        if not isinstance(current_value, list) or not skeleton:
            return
        source_list = source_value if isinstance(source_value, list) else []
        exemplar = skeleton[0]

        for index, source_item in enumerate(source_list):
            child_path = f"{path}[{index}]"
            projected = _project_value_to_contract_shape(source_item, exemplar, path=child_path)
            if _is_missing_contract_value(projected):
                continue
            if index >= len(current_value):
                current_value.append(projected)
                continue
            if _is_missing_contract_value(current_value[index]):
                current_value[index] = projected
                continue
            _merge_missing_values_from_source(
                current_value[index],
                exemplar,
                source_item,
                group_definitions=group_definitions,
                path=child_path,
            )


def _project_value_to_contract_shape(value: Any, skeleton: Any, *, path: str) -> Any:
    if isinstance(skeleton, dict):
        if not isinstance(value, dict):
            return {}
        projected: dict[str, Any] = {}
        for key, child_skeleton in skeleton.items():
            child_value = value.get(key)
            child_path = f"{path}.{key}" if path else key
            projected_child = _project_value_to_contract_shape(child_value, child_skeleton, path=child_path)
            if not _is_missing_contract_value(projected_child):
                projected[key] = projected_child
        return projected

    if isinstance(skeleton, list):
        if not isinstance(value, list) or not skeleton:
            return []
        exemplar = skeleton[0]
        projected_list = [
            _project_value_to_contract_shape(item, exemplar, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
        return [item for item in projected_list if not _is_missing_contract_value(item)]

    if not _can_backfill_from_canonical_path(path):
        return ""
    if not _should_accept_fallback_value(path, value):
        return ""
    if value is None:
        return ""
    return str(value).strip()


def _lookup_evidence_item(evidence: dict[str, Any], path: str) -> tuple[str | None, Any]:
    current = path
    while current:
        item = evidence.get(current)
        if isinstance(item, dict):
            return current, item
        stripped_index = re.sub(r"\[\d+\]$", "", current)
        if stripped_index != current:
            current = stripped_index
            continue
        current = current.rsplit(".", 1)[0] if "." in current else ""
    return None, None


def _should_accept_fallback_value(path: str, value: Any) -> bool:
    if _is_missing_contract_value(value):
        return False
    if path == "identity.full_name" and _looks_like_source_filename(str(value or "")):
        return False
    return True


def _looks_like_source_filename(value: str) -> bool:
    normalized = (value or "").strip()
    if not normalized:
        return False
    return bool(FILENAME_LIKE_PATTERN.fullmatch(normalized))


def _semantic_validation_reason(path: str, value: Any, data: dict[str, Any]) -> str | None:
    normalized = _normalize_text(_stringify_for_evidence(value))
    if path == "identity.full_name" and _looks_like_source_filename(str(value or "")):
        return "identity_looks_like_filename"

    if path.endswith(".context"):
        if normalized in GENERIC_LOCATION_VALUES:
            return "context_looks_like_location"
        location_path = re.sub(r"\.context$", ".location", path)
        location_value = _get_contract_value(data, location_path)
        if normalized and normalized == _normalize_text(_stringify_for_evidence(location_value)):
            return "context_matches_location"

    return None


def _postprocess_generated_contract(
    *,
    data: dict[str, Any],
    evidence: dict[str, Any],
    group_definitions: dict[str, Any],
    source_text: str,
) -> None:
    _dedupe_experience_render_blocks(data)
    _normalize_single_language_slot(data, evidence, group_definitions, source_text=source_text)


def _dedupe_experience_render_blocks(data: dict[str, Any]) -> None:
    experiences = data.get("experiences")
    if not isinstance(experiences, list):
        return

    for experience in experiences:
        if not isinstance(experience, dict):
            continue
        context = _normalize_text(_stringify_for_evidence(experience.get("context")))
        tasks = [
            str(item).strip()
            for item in experience.get("tasks", [])
            if str(item).strip()
        ] if isinstance(experience.get("tasks"), list) else []

        if context and tasks and _normalize_text(tasks[0]) == context and len(tasks) > 1:
            tasks = tasks[1:]
            experience["tasks"] = tasks

        highlights = [
            str(item).strip()
            for item in experience.get("highlights", [])
            if str(item).strip()
        ] if isinstance(experience.get("highlights"), list) else []
        task_keys = {_normalize_text(item) for item in tasks if _normalize_text(item)}
        highlights = [
            item for item in highlights
            if _normalize_text(item) != context and _normalize_text(item) not in task_keys
        ]
        if tasks:
            seen = set()
            deduped_highlights: list[str] = []
            for item in highlights:
                key = _normalize_text(item)
                if not key or key in seen:
                    continue
                seen.add(key)
                deduped_highlights.append(item)
            experience["highlights"] = deduped_highlights[:3]

        key_points = [
            str(item).strip()
            for item in experience.get("key_points", [])
            if str(item).strip()
        ] if isinstance(experience.get("key_points"), list) else []
        key_points = [
            item for item in key_points
            if _normalize_text(item) != context
        ]
        if tasks:
            for candidate in tasks:
                if _normalize_text(candidate) != context:
                    experience["key_points"] = [candidate]
                    break
            else:
                experience["key_points"] = key_points[:1]
            if (
                experience.get("key_points")
                and isinstance(experience["key_points"], list)
                and experience["key_points"]
                and _normalize_text(str(experience["key_points"][0])) == _normalize_text(tasks[0])
            ):
                experience["key_points"] = []


def _normalize_single_language_slot(
    data: dict[str, Any],
    evidence: dict[str, Any],
    group_definitions: dict[str, Any],
    *,
    source_text: str,
) -> None:
    languages = data.get("languages")
    if not isinstance(languages, list) or not languages:
        return

    if len(languages) != 1:
        return

    first = languages[0]
    if not isinstance(first, dict):
        return

    ev = evidence.get("languages[0].name")
    if not isinstance(ev, dict):
        return

    quote = str(ev.get("source_quote") or "").strip()
    if "/" in quote:
        match = re.search(r"([A-Za-z]+(?:/[A-Za-z]+)+)", quote)
        if match:
            first["name"] = match.group(1)
    if not str(first.get("level") or "").strip():
        inferred_level = _infer_language_level(
            language_name=str(first.get("name") or ""),
            quote=quote,
            source_text=source_text,
        )
        if inferred_level:
            first["level"] = inferred_level
            evidence["languages[0].level"] = {
                "source_quote": inferred_level,
                "source_type": "original_text",
                "confidence_mode": "derived",
                "reason_if_empty": "",
            }


def _infer_language_level(*, language_name: str, quote: str, source_text: str) -> str:
    direct_match = LANGUAGE_LEVEL_PATTERN.search(quote or "")
    if direct_match:
        return direct_match.group(1).strip()

    relaxed_language = _build_relaxed_language_pattern(language_name)
    if not relaxed_language:
        return ""

    for pattern in (
        rf"{relaxed_language}\s*[:\-–]?\s*(?P<level>{LANGUAGE_LEVEL_PATTERN.pattern})",
        rf"(?P<level>{LANGUAGE_LEVEL_PATTERN.pattern})\s*[:\-–]?\s*{relaxed_language}",
    ):
        match = re.search(pattern, source_text or "", flags=re.I)
        if match:
            return str(match.group("level") or "").strip()
    return ""


def _build_relaxed_language_pattern(value: str) -> str:
    parts: list[str] = []
    for character in str(value or "").strip():
        if character.isalnum():
            parts.append(re.escape(character))
        elif character in {"/", "-", "–"}:
            parts.append(r"[/\-\u2013]")
        elif character.isspace():
            continue
        else:
            parts.append(re.escape(character))
    if not parts:
        return ""
    return r"\s*".join(parts)


def _can_backfill_from_canonical_path(path: str) -> bool:
    return _normalize_contract_path(path) not in CANONICAL_BACKFILL_BLOCKLIST
