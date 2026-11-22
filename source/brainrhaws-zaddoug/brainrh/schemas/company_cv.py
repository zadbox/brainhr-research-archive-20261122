from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CompanyCvSchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CompanyCvIdentity(CompanyCvSchemaModel):
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    title: str = ""
    source_filename: str = ""
    source_display_name: str = ""


class CompanyCvExperience(CompanyCvSchemaModel):
    position: str = ""
    role: str = ""
    company: str = ""
    company_full: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    duration: str = ""
    period: str = ""
    period_full: str = ""
    summary: str = ""
    context: str = ""
    environment: str = ""
    tasks: list[str] = Field(default_factory=list)
    highlights: list[str] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)


class CompanyCvEducation(CompanyCvSchemaModel):
    degree: str = ""
    institution: str = ""
    field: str = ""
    start_date: str = ""
    end_date: str = ""
    year: str = ""
    description: str = ""


class CompanyCvCertification(CompanyCvSchemaModel):
    name: str = ""
    issuer: str = ""
    year: str = ""
    link: str = ""


class CompanyCvLanguage(CompanyCvSchemaModel):
    name: str = ""
    level: str = ""


class CompanyCvProject(CompanyCvSchemaModel):
    name: str = ""
    description: str = ""
    role: str = ""
    technologies: list[str] = Field(default_factory=list)


class CompanyCvExtraSection(CompanyCvSchemaModel):
    title: str = ""
    items: list[str] = Field(default_factory=list)


class CompanyCvSkills(CompanyCvSchemaModel):
    technical: list[str] = Field(default_factory=list)
    soft: list[str] = Field(default_factory=list)
    domain: list[str] = Field(default_factory=list)
    key: list[str] = Field(default_factory=list)
    categories: dict[str, list[str]] = Field(default_factory=dict)


class CompanyCvEnterpriseInfo(CompanyCvSchemaModel):
    id: str = ""
    name: str = ""
    sector: str = ""
    notes: str = ""


class CompanyCvProjectInfo(CompanyCvSchemaModel):
    id: str = ""
    name: str = ""
    department: str = ""
    manager: str = ""
    manager_contact: str = ""
    notes: str = ""


class CompanyCvInterviewSheetInfo(CompanyCvSchemaModel):
    id: str = ""
    status: str = ""
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    verdict: str = ""
    verdict_detail: str = ""


class CompanyCvMetrics(CompanyCvSchemaModel):
    total_experience_years: float = 0.0
    total_experience_years_label: str = ""
    source_experience_years_label: str = ""


class CompanyCvContext(CompanyCvSchemaModel):
    schema_version: str = "company_cv_context.v1"
    generation_guidance: str = ""
    identity: CompanyCvIdentity = Field(default_factory=CompanyCvIdentity)
    title: str = ""
    summary: str = ""
    availability: str = ""
    experiences: list[CompanyCvExperience] = Field(default_factory=list)
    education: list[CompanyCvEducation] = Field(default_factory=list)
    certifications: list[CompanyCvCertification] = Field(default_factory=list)
    languages: list[CompanyCvLanguage] = Field(default_factory=list)
    skills: CompanyCvSkills = Field(default_factory=CompanyCvSkills)
    projects: list[CompanyCvProject] = Field(default_factory=list)
    extra_sections: list[CompanyCvExtraSection] = Field(default_factory=list)
    enterprise: CompanyCvEnterpriseInfo = Field(default_factory=CompanyCvEnterpriseInfo)
    project: CompanyCvProjectInfo = Field(default_factory=CompanyCvProjectInfo)
    interview_sheet: CompanyCvInterviewSheetInfo = Field(default_factory=CompanyCvInterviewSheetInfo)
    metrics: CompanyCvMetrics = Field(default_factory=CompanyCvMetrics)
    generated_at: str = ""
    generated_date: str = ""
