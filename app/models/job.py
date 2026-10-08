from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class MatchLevel(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Recommendation(StrEnum):
    APPLY = "APPLY"
    REASONABLE_STRETCH = "REASONABLE_STRETCH"
    SKIP = "SKIP"


class JobRequest(BaseModel):
    company: str = Field(min_length=1, max_length=150)
    role: str = Field(min_length=1, max_length=150)
    job_url: HttpUrl | None = None
    job_description: str = Field(min_length=30, max_length=30_000)


class JobUrlRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


class JobExtraction(BaseModel):
    company: str = ""
    role: str = ""
    job_description: str = ""
    source: str
    extraction_method: Literal["jsonld", "html", "playwright", "manual_required"]


class JobAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company: str
    role: str
    strong_matches: list[str]
    partial_matches: list[str]
    missing_requirements: list[str]
    match_sources: dict[str, list[str]] = Field(default_factory=dict)
    supported_keywords: list[str]
    unsupported_keywords: list[str]
    recommendation: Recommendation
    match_level: MatchLevel
    reasoning_summary: str = Field(max_length=600)
