from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SkillLevel = Literal["basic", "intermediate", "advanced", "hands_on", "learning"]
EvidenceSourceType = Literal["master_profile", "employment", "project", "education", "manual_verified"]


class SkillEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: EvidenceSourceType
    source_id: str = Field(min_length=1, max_length=240)
    description: str = Field(min_length=1, max_length=500)


class VerifiedSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^skill_[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    subcategory: str = Field(default="", max_length=80)
    level: SkillLevel
    verified: bool = False
    allowed_in_cv: bool = False
    enabled: bool = True
    priority: int = Field(default=5, ge=0, le=10)
    aliases: list[str] = Field(default_factory=list, max_length=30)
    evidence: list[SkillEvidence] = Field(default_factory=list, max_length=30)
    notes: str = Field(default="", max_length=1000)
    cv_wording: str = Field(default="", max_length=140)

    @model_validator(mode="after")
    def validate_trust_state(self):
        if self.level == "learning" and (self.verified or self.allowed_in_cv):
            raise ValueError("A learning skill cannot be verified or allowed in a CV")
        if self.verified and not self.evidence:
            raise ValueError("A verified skill requires evidence")
        return self


class SkillsDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    skills: list[VerifiedSkill]

    @model_validator(mode="after")
    def validate_unique_skills(self):
        ids = [skill.id for skill in self.skills]
        names = [skill.name.casefold() for skill in self.skills]
        if len(ids) != len(set(ids)):
            raise ValueError("Skill IDs must be unique")
        if len(names) != len(set(names)):
            raise ValueError("Skill names must be unique")
        return self
