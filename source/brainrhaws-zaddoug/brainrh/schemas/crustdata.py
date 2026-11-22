from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SearchLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=200)
    radius_km: int = Field(default=50, ge=1, le=500)

class CandidateSearchCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")
    titles: list[str] = Field(default_factory=list, max_length=20)
    required_skills: list[str] = Field(default_factory=list, max_length=30)
    locations: list[SearchLocation] = Field(default_factory=list, max_length=10)
    min_years_experience: Optional[int] = Field(default=None, ge=0, le=80)
    seniority_levels: list[str] = Field(default_factory=list, max_length=10)
    max_profile_age_days: Optional[int] = Field(default=180, ge=1, le=3650)
    result_limit: int = Field(default=50, ge=1, le=1000)

    @field_validator("titles", "required_skills", "seniority_levels")
    @classmethod
    def normalize_strings(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip() for item in value if item.strip()))


class CriteriaResponse(BaseModel):
    offer_derived_criteria: CandidateSearchCriteria
    current_criteria: CandidateSearchCriteria
    stale: bool


class CriteriaPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_criteria: CandidateSearchCriteria


class SearchRequest(BaseModel):
    operation_id: str = Field(min_length=8, max_length=128)
    criteria: Optional[CandidateSearchCriteria] = None


class NextSearchRequest(BaseModel):
    operation_id: str = Field(min_length=8, max_length=128)
    cursor: str = Field(min_length=1, max_length=2048)


class SearchProfile(BaseModel):
    result_id: str
    name: str = ""
    headline: str = ""
    current_title: str = ""
    current_company: str = ""
    location: str = ""
    updated_at: Optional[str] = None
    profile_url: Optional[str] = None
    selectable: bool


class CreditsSummary(BaseModel):
    estimated: str
    consumed: Optional[str] = None
    available: Optional[str] = None
    search_cost_per_result: str
    enrich_cost_per_person: str
    status: str
    error_code: Optional[str] = None


class SearchResponse(BaseModel):
    session_id: str
    profiles: list[SearchProfile]
    next_cursor: Optional[str] = None
    total_count: Optional[int] = None
    requested_count: int
    returned_count: int
    credits: CreditsSummary


class ImportRequest(BaseModel):
    operation_id: str = Field(min_length=8, max_length=128)
    session_id: str
    result_ids: list[str] = Field(min_length=1, max_length=250)


class ImportResponse(BaseModel):
    imported_count: int
    already_imported_count: int = 0
    failed_count: int
    imported: list[dict[str, Any]]
    already_imported: list[dict[str, Any]] = Field(default_factory=list)
    failed: list[dict[str, Any]]
    credits: CreditsSummary
    warnings: list[str]


class AutocompleteRequest(BaseModel):
    field: Literal[
        "experience.employment_details.current.title",
        "skills.professional_network_skills",
        "professional_network.location.raw",
        "experience.employment_details.current.seniority_level",
    ]
    query: str = Field(min_length=1, max_length=100)


class TenantWalletUpdate(BaseModel):
    balance: str


class CreditSyncRequest(BaseModel):
    operation_id: Optional[str] = None


class CreditReconcileRequest(BaseModel):
    actual_credits: str
