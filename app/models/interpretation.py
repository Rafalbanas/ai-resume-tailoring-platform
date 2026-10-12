"""Provider-neutral LLM contract; derived scores/layout fields belong to code."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.job import JobAnalysis, JobRequest, RequirementPriority, RequirementStatus


class ModelComponent(BaseModel):
    name: str
    status: RequirementStatus
    source_fact_ids: list[str]
    reason: str
    required_level: str = ""


class ModelRequirement(BaseModel):
    name: str
    source_quote: str = Field(min_length=1)
    priority: RequirementPriority
    status: RequirementStatus
    source_fact_ids: list[str]
    reason: str = Field(min_length=1)
    operator: Literal["single", "all", "any", "ambiguous"]
    components: list[ModelComponent]
    classification_basis: str
    required_level: str = ""
    required_years: float | None = None
    accepted_alternatives: list[str] = Field(default_factory=list)
    interpretation_uncertain: bool = False


class JobInterpretation(BaseModel):
    requirements: list[ModelRequirement]
    role_competencies: list[ModelRequirement] = Field(default_factory=list)
    responsibilities: list[dict[str, str]] = Field(default_factory=list)
    source_context: list[dict[str, str]] = Field(default_factory=list)
    reasoning_summary: str = Field(default="", max_length=1500)

    @model_validator(mode="before")
    @classmethod
    def legacy_response(cls, value):
        # Retain compatibility with older provider/mock responses. A random
        # object still fails; only a complete former JobAnalysis envelope qualifies.
        legacy = {"company", "role", "strong_matches", "partial_matches", "missing_requirements"}
        if isinstance(value, dict) and "requirements" not in value and legacy <= value.keys():
            value = {**value, "requirements": []}
        return value

    def to_analysis(self, job: JobRequest) -> JobAnalysis:
        return JobAnalysis(
            company=job.company,
            role=job.role,
            strong_matches=[],
            partial_matches=[],
            missing_requirements=[],
            recommendation="REVIEW",
            match_level="LOW",
            **self.model_dump(),
        )
