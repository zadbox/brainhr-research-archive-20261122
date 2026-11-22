from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from brainrh.schemas.crustdata import CandidateSearchCriteria


SEARCH_FIELDS = [
    "crustdata_person_id",
    "metadata.updated_at",
    "basic_profile.name",
    "basic_profile.headline",
    "basic_profile.current_title",
    "basic_profile.location",
    "experience.employment_details.current",
    "social_handles.professional_network_identifier.profile_url",
]

ALLOWED_FIELD_OPERATORS = {
    "experience.employment_details.current.title": {"(.)"},
    "skills.professional_network_skills": {"(.)"},
    "years_of_experience_raw": {"=>"},
    "experience.employment_details.current.seniority_level": {"in"},
    "professional_network.location.raw": {"geo_distance"},
    "metadata.updated_at": {"=>"},
}


class CandidateSearchCriteriaCompiler:
    @staticmethod
    def compile(criteria: CandidateSearchCriteria, *, now: datetime | None = None) -> dict[str, Any]:
        conditions: list[dict[str, Any]] = []
        if criteria.titles:
            conditions.append({
                "op": "or",
                "conditions": [
                    CandidateSearchCriteriaCompiler._condition(
                        "experience.employment_details.current.title", "(.)", title
                    )
                    for title in criteria.titles
                ],
            })
        conditions.extend(
            CandidateSearchCriteriaCompiler._condition("skills.professional_network_skills", "(.)", skill)
            for skill in criteria.required_skills
        )
        if criteria.min_years_experience is not None:
            conditions.append(CandidateSearchCriteriaCompiler._condition(
                "years_of_experience_raw", "=>", criteria.min_years_experience
            ))
        if criteria.seniority_levels:
            conditions.append(CandidateSearchCriteriaCompiler._condition(
                "experience.employment_details.current.seniority_level", "in", criteria.seniority_levels
            ))
        location_conditions = [
            CandidateSearchCriteriaCompiler._condition(
                "professional_network.location.raw",
                "geo_distance",
                {"location": location.label, "distance": location.radius_km, "unit": "km"},
            )
            for location in criteria.locations
        ]
        if len(location_conditions) == 1:
            conditions.append(location_conditions[0])
        elif location_conditions:
            conditions.append({"op": "or", "conditions": location_conditions})
        if criteria.max_profile_age_days is not None:
            reference = now or datetime.now(timezone.utc)
            cutoff = (reference - timedelta(days=criteria.max_profile_age_days)).date().isoformat()
            conditions.append(CandidateSearchCriteriaCompiler._condition("metadata.updated_at", "=>", cutoff))
        return {
            "filters": {"op": "and", "conditions": conditions},
            "fields": list(SEARCH_FIELDS),
            "sorts": [{"field": "metadata.updated_at", "order": "desc"}],
            "limit": criteria.result_limit,
        }

    @staticmethod
    def _condition(field: str, operator: str, value: Any) -> dict[str, Any]:
        if operator not in ALLOWED_FIELD_OPERATORS.get(field, set()):
            raise ValueError("Champ ou opérateur Crustdata non autorisé")
        return {"field": field, "type": operator, "value": value}
