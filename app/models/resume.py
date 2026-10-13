from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator


class ResumeBullet(BaseModel):
    text: str
    source_fact_ids: list[str] = Field(min_length=1)


class ResumeExperience(BaseModel):
    company: str
    title: str
    dates: str
    bullets: list[ResumeBullet] = Field(max_length=4)


class ResumeProject(BaseModel):
    url: str = ""
    name: str
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    source_fact_ids: list[str] = Field(min_length=1)


class ResumeEducation(BaseModel):
    institution: str
    qualification: str = ""
    dates: str = ""
    specialisation: str = ""
    thesis_subline: str = ""
    source_fact_ids: list[str] = Field(default_factory=list)


class ResumeCertification(BaseModel):
    name: str
    issuer: str = ""
    date: str = ""


class ResumeLearningSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_id: str
    name: str = Field(max_length=120)
    status: Literal["Learning in progress", "Course in progress"] = "Learning in progress"


class TailoredResume(BaseModel):
    model_config = ConfigDict(extra="forbid")

    headline: str = Field(max_length=140)
    professional_summary: str = Field(max_length=700)
    summary_source_fact_ids: list[str] = Field(default_factory=list)
    _summary_attestation: str = PrivateAttr(default="")

    @property
    def summary_attestation(self) -> str:
        return self._summary_attestation

    @summary_attestation.setter
    def summary_attestation(self, value: str) -> None:
        self._summary_attestation = value
    currently_learning: list[ResumeLearningSkill] = Field(default_factory=list, max_length=8)
    core_skills: list[str] = Field(max_length=18)
    selected_skill_ids: list[str] = Field(default_factory=list, max_length=16)
    experience: list[ResumeExperience]
    education: list[ResumeEducation] = Field(default_factory=list)
    projects: list[ResumeProject] = Field(default_factory=list, max_length=3)
    certifications: list[ResumeCertification] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    selected_interest_ids: list[str] = Field(default_factory=list)


class WorkflowResponse(BaseModel):
    call_metrics: list[dict] = Field(default_factory=list)
    token_usage: dict = Field(default_factory=dict)
    analysis: "JobAnalysis"
    resume: TailoredResume
    provider_used: str = "unknown"
    model_used: str = "unknown"
    fallback_used: bool = False
    fallback_reason: str | None = None
    summary_attestation: str = Field(default="", max_length=128)

    @model_validator(mode='after')
    def attach_summary_review(self):
        if self.summary_attestation:
            self.resume.summary_attestation = self.summary_attestation
        else:
            self.summary_attestation = self.resume.summary_attestation
        return self


from app.models.job import JobAnalysis  # noqa: E402

WorkflowResponse.model_rebuild()
