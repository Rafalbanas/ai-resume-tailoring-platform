from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, PrivateAttr, field_validator, model_validator


class MatchLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNRELIABLE = "UNRELIABLE"
    LIMITED = "LIMITED"


class Recommendation(StrEnum):
    APPLY = "APPLY"
    REASONABLE_STRETCH = "REASONABLE_STRETCH"
    SKIP = "SKIP"
    RETRY = "RETRY"
    REVIEW = "REVIEW"


class RequirementPriority(StrEnum):
    MANDATORY = "mandatory"
    PREFERRED = "preferred"
    NICE_TO_HAVE = "nice_to_have"
    UNSPECIFIED = "unspecified"


class RequirementStatus(StrEnum):
    STRONG = "strong"
    PARTIAL = "partial"
    MISSING = "missing"
    ABSENT = "absent"


class RequirementComponent(BaseModel):
    name: str
    status: RequirementStatus = RequirementStatus.MISSING
    required_level: str = ""
    source_fact_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    evidence_sources: list[dict[str, str]] = Field(default_factory=list)
    reason: str = ""


class JobRequirement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str
    source_quote: str = ""
    source_quotes: list[str] = Field(default_factory=list)
    required_level: str = ""
    required_years: float | None = None
    observed_years: float | None = None
    operator: Literal["single", "all", "any", "ambiguous"] = "single"
    alternatives: list[str] = Field(default_factory=list)
    accepted_alternatives: list[str] = Field(default_factory=list)
    interpretation_origin: Literal["", "llm", "source_review"] = ""
    components: list[RequirementComponent] = Field(default_factory=list)
    interpretation_uncertain: bool = False
    scoring_key: str = ""
    duplicate_of: str = ""
    evidence_sources: list[dict[str, str]] = Field(default_factory=list)
    clarification_needed: str = ""
    classification_basis: str = ""
    source_section: str = ""
    group_id: str = ""
    priority: RequirementPriority = RequirementPriority.MANDATORY
    status: RequirementStatus = RequirementStatus.MISSING
    evidence: list[str] = Field(default_factory=list)
    source_fact_ids: list[str] = Field(default_factory=list)
    reason: str = ""


class JobRequest(BaseModel):
    _source_resume: dict | None = PrivateAttr(default=None)
    company: str = Field(min_length=1, max_length=150)
    role: str = Field(min_length=1, max_length=150)
    job_url: HttpUrl | None = None
    job_description: str = Field(default="", max_length=30_000)
    tailoring_level: float = Field(default=0.0, ge=0, le=1, allow_inf_nan=False)
    workflow: Literal["job", "custom"] = "job"
    custom_instructions: str = Field(default="", max_length=30_000)
    cv_name: str = Field(default="", max_length=150)
    source_cv: str = Field(default="", max_length=241, pattern=r"^[a-z0-9_-]*$")

    @property
    def relevance_text(self) -> str:
        return self.custom_instructions if self.workflow == "custom" else self.job_description

    @model_validator(mode="after")
    def validate_workflow(self):
        if self.workflow == "job" and len(self.job_description) < 30:
            raise ValueError("Paste at least 30 characters of the job description.")
        if self.workflow == "custom" and len(self.custom_instructions) < 10:
            raise ValueError("Describe your CV instructions in at least 10 characters.")
        return self


    @field_validator("company", "role", "job_description", "custom_instructions", "cv_name", mode="before")
    @classmethod
    def strip_text(cls, value):
        return value.strip() if isinstance(value, str) else value


class JobUrlRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class JobExtraction(BaseModel):
    company: str = ""
    role: str = ""
    job_description: str = ""
    source: str
    extraction_method: Literal["jsonld", "html", "playwright", "manual_required"]
    failure_reason: Literal["blocked", "timeout", "fetch_failed", "description_unavailable", "unsafe_url", "unsupported_browser"] | None = None


class JobAnalysis(BaseModel):
    _model_output: dict | None = PrivateAttr(default=None)
    model_config = ConfigDict(extra="ignore")

    company: str
    role: str
    strong_matches: list[str]
    partial_matches: list[str]
    missing_requirements: list[str]
    match_sources: dict[str, list[str]] = Field(default_factory=dict)
    strong_skill_ids: list[str] = Field(default_factory=list)
    partial_skill_ids: list[str] = Field(default_factory=list)
    learning_skill_ids: list[str] = Field(default_factory=list)
    learning_matches: list[str] = Field(default_factory=list)
    match_evidence: dict[str, list[str]] = Field(default_factory=dict)
    supported_keywords: list[str] = Field(default_factory=list)
    unsupported_keywords: list[str] = Field(default_factory=list)
    recommendation: Recommendation
    match_level: MatchLevel
    reasoning_summary: str = Field(default="", max_length=2000)
    requirements: list[JobRequirement] = Field(default_factory=list)
    is_reliable: bool = True
    analysis_method: Literal["legacy", "llm_validated", "source_review"] = "legacy"
    job_source: dict[str, str] = Field(default_factory=dict)
    source_context: list[dict[str, str]] = Field(default_factory=list)
    analysis_language: str = ""
    validation_version: int = 0
    classification_issues: list[str] = Field(default_factory=list)
    validation_corrections: list[str] = Field(default_factory=list)
    evidence_issues: list[str] = Field(default_factory=list)
    completeness_issues: list[str] = Field(default_factory=list)
    unassessed_source_passages: list[str] = Field(default_factory=list)
    source_sections: list[str] = Field(default_factory=list)
    responsibilities: list[dict[str, str]] = Field(default_factory=list)
    role_competencies: list[JobRequirement] = Field(default_factory=list)
    organization_context: list[dict[str, str]] = Field(default_factory=list)
    qualification_assessment: str = ""
    role_alignment_summary: str = ""
    role_competency_counts: dict[str, int] = Field(default_factory=dict)
    requirement_counts: dict[str, int] = Field(default_factory=dict)
    scoring_counts: dict[str, int] = Field(default_factory=dict)
    profile_clarifications: list[str] = Field(default_factory=list)


class JobTextRequest(BaseModel):
    text: str = Field(min_length=30, max_length=50_000)
    url: str = Field(default="", max_length=2048)
