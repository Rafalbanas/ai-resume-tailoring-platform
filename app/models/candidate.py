from pydantic import BaseModel, ConfigDict, EmailStr, Field


class Personal(BaseModel):
    name: str = ""
    location: str = ""
    email: EmailStr | str = ""
    phone: str = ""
    linkedin: str = ""
    website: str = ""
    github: str = ""


class Experience(BaseModel):
    company: str
    title: str
    start: str = ""
    end: str = ""
    employment_note: str = ""
    facts: list[str] = Field(default_factory=list)


class Education(BaseModel):
    institution: str
    qualification: str = ""
    dates: str = ""
    facts: list[str] = Field(default_factory=list)


class Project(BaseModel):
    name: str
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)
    url: str = ""


class Certification(BaseModel):
    name: str
    issuer: str = ""
    date: str = ""


class CandidateProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    personal: Personal
    summary_facts: list[str] = Field(default_factory=list)
    skills: dict[str, list[str]] = Field(default_factory=dict)
    experience: list[Experience] = Field(default_factory=list)
    education: list[Education] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    certifications: list[Certification] = Field(default_factory=list)

    def skill_set(self) -> set[str]:
        return {skill.casefold() for values in self.skills.values() for skill in values}
