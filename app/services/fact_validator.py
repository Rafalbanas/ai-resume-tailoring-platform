from copy import deepcopy
from dataclasses import dataclass

from app.models.candidate import CandidateProfile
from app.models.job import JobRequest
from app.models.resume import (
    ResumeCertification,
    ResumeEducation,
    ResumeExperience,
    ResumeProject,
    TailoredResume,
)


@dataclass
class ValidationResult:
    resume: TailoredResume
    warnings: list[str]


class FactValidator:
    """Turns model output into profile-backed data; prompts are never the trust boundary."""

    def __init__(self, profile: CandidateProfile):
        self.profile = profile
        self.catalog = self._catalog(profile)

    @staticmethod
    def _catalog(profile: CandidateProfile) -> dict[str, str]:
        catalog: dict[str, str] = {}
        for i, fact in enumerate(profile.summary_facts):
            catalog[f"summary:{i}"] = fact
        for i, exp in enumerate(profile.experience):
            for j, fact in enumerate(exp.facts):
                catalog[f"experience:{i}:fact:{j}"] = fact
        for i, project in enumerate(profile.projects):
            catalog[f"project:{i}:description"] = project.description
            for j, fact in enumerate(project.facts):
                catalog[f"project:{i}:fact:{j}"] = fact
        return catalog

    def validate(self, candidate: TailoredResume, job: JobRequest) -> ValidationResult:
        draft = deepcopy(candidate)
        warnings: list[str] = []

        allowed_skills = {value.casefold(): value for values in self.profile.skills.values() for value in values}
        clean_skills = []
        for skill in draft.core_skills:
            if skill.casefold() in allowed_skills:
                canonical = allowed_skills[skill.casefold()]
                if canonical not in clean_skills:
                    clean_skills.append(canonical)
            else:
                warnings.append(f"Unsupported AI fact removed: {skill}")
        draft.core_skills = clean_skills[:18]

        valid_summary_ids = [key for key in draft.summary_source_fact_ids if key.startswith("summary:") and key in self.catalog]
        if len(valid_summary_ids) != len(draft.summary_source_fact_ids):
            warnings.append("Unsupported AI summary content was replaced with source facts")
        draft.summary_source_fact_ids = valid_summary_ids[:4]
        draft.professional_summary = " ".join(self.catalog[key] for key in draft.summary_source_fact_ids)
        draft.headline = f"{job.role} | {' • '.join(draft.core_skills[:3])}".rstrip(" |")

        clean_experience: list[ResumeExperience] = []
        exp_lookup = {(item.company.casefold(), item.title.casefold()): (i, item) for i, item in enumerate(self.profile.experience)}
        for exp in draft.experience:
            match = exp_lookup.get((exp.company.casefold(), exp.title.casefold()))
            if not match:
                warnings.append(f"Unsupported AI experience removed: {exp.company} — {exp.title}")
                continue
            exp_index, source = match
            bullets = []
            for bullet in exp.bullets:
                valid_ids = [
                    key for key in bullet.source_fact_ids
                    if key.startswith(f"experience:{exp_index}:fact:") and key in self.catalog
                ]
                if not valid_ids:
                    warnings.append(f"Unsupported AI bullet removed from {source.company}")
                    continue
                bullet.source_fact_ids = valid_ids
                bullet.text = " ".join(self.catalog[key] for key in valid_ids)
                bullets.append(bullet)
            if bullets:
                exp.company = source.company
                exp.title = source.title
                exp.dates = " – ".join(filter(None, [source.start, source.end]))
                exp.bullets = bullets[:4]
                clean_experience.append(exp)
        draft.experience = clean_experience

        project_lookup = {project.name.casefold(): (i, project) for i, project in enumerate(self.profile.projects)}
        clean_projects: list[ResumeProject] = []
        for project in draft.projects:
            match = project_lookup.get(project.name.casefold())
            if not match:
                warnings.append(f"Unsupported AI project removed: {project.name}")
                continue
            index, source = match
            valid_ids = [key for key in project.source_fact_ids if key.startswith(f"project:{index}:") and key in self.catalog]
            if not valid_ids:
                warnings.append(f"Unsupported AI project content removed: {project.name}")
                continue
            project.name = source.name
            project.description = " ".join(self.catalog[key] for key in valid_ids if self.catalog[key])
            project.technologies = [tech for tech in source.technologies if tech.casefold() in allowed_skills]
            project.source_fact_ids = valid_ids
            clean_projects.append(project)
        draft.projects = clean_projects[:2]

        education_lookup = {item.institution.casefold(): item for item in self.profile.education}
        draft.education = [
            ResumeEducation(**education_lookup[item.institution.casefold()].model_dump(exclude={"facts"}))
            for item in draft.education
            if item.institution.casefold() in education_lookup
        ]
        cert_lookup = {item.name.casefold(): item for item in self.profile.certifications}
        clean_certs = []
        for cert in draft.certifications:
            if cert.name.casefold() not in cert_lookup:
                warnings.append(f"Unsupported AI fact removed: {cert.name}")
                continue
            clean_certs.append(ResumeCertification(**cert_lookup[cert.name.casefold()].model_dump()))
        draft.certifications = clean_certs
        return ValidationResult(resume=draft, warnings=warnings)
