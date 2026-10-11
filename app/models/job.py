from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class MatchLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNRELIABLE = "UNRELIABLE"


class Recommendation(StrEnum):
    APPLY = "APPLY"
    REASONABLE_STRETCH = "REASONABLE_STRETCH"
    SKIP = "SKIP"
    RETRY = "RETRY"


class RequirementPriority(StrEnum):
    MANDATORY = "mandatory"
    PREFERRED = "preferred"
    NICE_TO_HAVE = "nice_to_have"


class RequirementStatus(StrEnum):
    STRONG = "strong"
    PARTIAL = "partial"
    MISSING = "missing"


class JobRequirement(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str
    source_quote: str = ""
    priority: RequirementPriority = RequirementPriority.MANDATORY
    status: RequirementStatus = RequirementStatus.MISSING
    evidence: list[str] = Field(default_factory=list)
    reason: str = ""


class JobRequest(BaseModel):
    company: str = Field(min_length=1, max_length=150)
    role: str = Field(min_length=1, max_length=150)
    job_url: HttpUrl | None = None
    job_description: str = Field(min_length=30, max_length=30_000)


    @field_validator("company", "role", "job_description", mode="before")
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


class JobAnalysis(BaseModel):
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
