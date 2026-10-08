from copy import deepcopy
from dataclasses import dataclass

from app.models.candidate import CandidateProfile
from app.models.job import JobRequest
from app.models.resume import (
    ResumeBullet,
    ResumeCertification,
    ResumeEducation,
    ResumeExperience,
    ResumeProject,
    TailoredResume,
)
from app.services.fact_catalog import FactCatalog
from app.services.skills_bank import SkillsBank


@dataclass
class ValidationResult:
    resume: TailoredResume
    warnings: list[str]


class FactValidator:
    """Turns model output into profile-backed data; prompts are never the trust boundary."""

    def __init__(self, profile: CandidateProfile, skills_bank: SkillsBank | None = None):
        self.profile = profile
        self.catalog = FactCatalog(profile)
        self.skills_bank = skills_bank

    def validate(self, candidate: TailoredResume, job: JobRequest) -> ValidationResult:
        draft = deepcopy(candidate)
        warnings: list[str] = []

        def skill_key(value: str) -> str:
            return " ".join(value.casefold().replace("(basic)", "").replace("/", " ").replace("-", " ").split())

        allowed_skills = {skill_key(value): value for values in self.profile.skills.values() for value in values}
        clean_skills = []
        if self.skills_bank:
            manual_skill_list = bool(draft.core_skills) and not draft.selected_skill_ids
            requested_ids = list(draft.selected_skill_ids)
            for value in draft.core_skills:
                skill = self.skills_bank.find(value)
                if skill and self.skills_bank.eligible(skill):
                    requested_ids.append(skill.id)
                elif value.strip():
                    warnings.append(f"Unsupported AI fact removed: {value}")
            selected = self.skills_bank.select_for_job(
                list(dict.fromkeys(requested_ids)),
                f"{job.role}\n{job.job_description}",
                minimum=0 if manual_skill_list else 8,
                maximum=16,
            )
            draft.selected_skill_ids = [skill.id for skill in selected]
            draft.core_skills = [self.skills_bank.wording(skill) for skill in selected]
            allowed_skills = {
                skill_key(alias): self.skills_bank.wording(skill)
                for skill in self.skills_bank.skills
                if self.skills_bank.eligible(skill)
                for alias in self.skills_bank.aliases_for(skill)
            }
        else:
            for skill in draft.core_skills:
                key = skill_key(skill)
                if key in allowed_skills:
                    canonical = allowed_skills[key]
                    if canonical not in clean_skills:
                        clean_skills.append(canonical)
                else:
                    warnings.append(f"Unsupported AI fact removed: {skill}")
            if not clean_skills:
                job_text = job.job_description.casefold()
                relevant = [
                    canonical
                    for key, canonical in allowed_skills.items()
                    if key and (key in job_text or canonical.casefold() in job_text)
                ]
                clean_skills = relevant or list(dict.fromkeys(allowed_skills.values()))[:10]
            draft.core_skills = clean_skills[:18]

        summary_entries = self.catalog.valid(draft.summary_source_fact_ids, kind="summary")[:4]
        if not summary_entries:
            summary_entries = [entry for entry in self.catalog.prompt_entries if entry.kind == "summary"][:3]
        summary_ids = [entry.source_id for entry in summary_entries]
        if not self.catalog.supports_paraphrase(draft.professional_summary, summary_ids):
            if draft.professional_summary:
                warnings.append("Unsupported AI summary content was replaced with source facts")
            draft.professional_summary = " ".join(entry.text for entry in summary_entries)
        draft.summary_source_fact_ids = summary_ids
        if not draft.headline.strip() or "candidate name" in draft.headline.casefold():
            draft.headline = job.role

        clean_experience: list[ResumeExperience] = []
        for exp in draft.experience:
            bullets = []
            exp_index: int | None = None
            for bullet in exp.bullets:
                entries = self.catalog.valid(bullet.source_fact_ids, kind="experience")
                owner_indexes = {entry.owner_index for entry in entries}
                if len(owner_indexes) != 1:
                    warnings.append(f"Unsupported AI bullet removed from {exp.company}")
                    continue
                bullet_index = owner_indexes.pop()
                if bullet_index is None or (exp_index is not None and bullet_index != exp_index):
                    warnings.append(f"Unsupported AI bullet removed from {exp.company}")
                    continue
                exp_index = bullet_index
                valid_ids = [entry.source_id for entry in entries]
                if not self.catalog.supports_paraphrase(bullet.text, valid_ids):
                    warnings.append(f"Unsupported AI bullet replaced in {self.profile.experience[exp_index].company}")
                    bullet.text = " ".join(entry.text for entry in entries)
                bullet.source_fact_ids = valid_ids
                bullets.append(bullet)
            if exp_index is None or not bullets:
                warnings.append(f"Unsupported AI experience removed: {exp.company} — {exp.title}")
                continue
            source = self.profile.experience[exp_index]
            exp.company = source.company
            exp.title = source.title
            exp.dates = " – ".join(filter(None, [source.start, source.end]))
            exp.bullets = bullets[:4]
            clean_experience.append(exp)
        if not clean_experience:
            for exp_index, source in enumerate(self.profile.experience):
                entries = [
                    entry
                    for entry in self.catalog.prompt_entries
                    if entry.kind == "experience" and entry.owner_index == exp_index
                ][:2]
                if not entries:
                    continue
                clean_experience.append(
                    ResumeExperience(
                        company=source.company,
                        title=source.title,
                        dates=" – ".join(filter(None, [source.start, source.end])),
                        bullets=[ResumeBullet(text=entry.text, source_fact_ids=[entry.source_id]) for entry in entries],
                    )
                )
        draft.experience = clean_experience

        clean_projects: list[ResumeProject] = []
        for project in draft.projects:
            entries = self.catalog.valid(project.source_fact_ids, kind="project")
            owner_indexes = {entry.owner_index for entry in entries}
            if len(owner_indexes) != 1:
                warnings.append(f"Unsupported AI project removed: {project.name}")
                continue
            index = owner_indexes.pop()
            if index is None:
                warnings.append(f"Unsupported AI project content removed: {project.name}")
                continue
            source = self.profile.projects[index]
            valid_ids = [entry.source_id for entry in entries]
            project.name = source.name
            if not self.catalog.supports_paraphrase(project.description, valid_ids):
                if project.description:
                    warnings.append(f"Unsupported AI project content replaced: {project.name}")
                project.description = " ".join(entry.text for entry in entries)
            project.technologies = [
                allowed_skills[skill_key(tech)] for tech in source.technologies if skill_key(tech) in allowed_skills
            ]
            project.source_fact_ids = valid_ids
            clean_projects.append(project)
        if not clean_projects:
            for index, source in enumerate(self.profile.projects[:2]):
                entries = [
                    entry
                    for entry in self.catalog.prompt_entries
                    if entry.kind == "project" and entry.owner_index == index
                ]
                content = next((entry for entry in entries if ":description:" in entry.source_id), None)
                content = content or next(iter(entries), None)
                if content:
                    clean_projects.append(
                        ResumeProject(
                            name=source.name,
                            description=content.text,
                            technologies=[
                                allowed_skills[skill_key(tech)]
                                for tech in source.technologies
                                if skill_key(tech) in allowed_skills
                            ],
                            source_fact_ids=[content.source_id],
                        )
                    )
        draft.projects = clean_projects[:2]

        clean_education = []
        education_lookup = {
            item.institution.casefold(): (index, item) for index, item in enumerate(self.profile.education)
        }
        for item in draft.education:
            entries = self.catalog.valid(item.source_fact_ids, kind="education")
            index = entries[0].owner_index if entries else None
            if index is None:
                match = education_lookup.get(item.institution.casefold())
                index = match[0] if match else None
            if index is None:
                warnings.append(f"Unsupported AI education removed: {item.institution}")
                continue
            source = self.profile.education[index]
            main_entry = next(
                (
                    entry
                    for entry in self.catalog.prompt_entries
                    if entry.kind == "education" and entry.owner_index == index and ":fact:" not in entry.source_id
                ),
                None,
            )
            clean_education.append(
                ResumeEducation(
                    institution=source.institution,
                    qualification=source.qualification,
                    dates=source.dates,
                    source_fact_ids=[main_entry.source_id] if main_entry else [],
                )
            )
        if not clean_education:
            for index, source in enumerate(self.profile.education):
                main_entry = next(
                    (
                        entry
                        for entry in self.catalog.prompt_entries
                        if entry.kind == "education" and entry.owner_index == index and ":fact:" not in entry.source_id
                    ),
                    None,
                )
                clean_education.append(
                    ResumeEducation(
                        institution=source.institution,
                        qualification=source.qualification,
                        dates=source.dates,
                        source_fact_ids=[main_entry.source_id] if main_entry else [],
                    )
                )
        draft.education = clean_education
        cert_lookup = {item.name.casefold(): item for item in self.profile.certifications}
        clean_certs = []
        for cert in draft.certifications:
            if cert.name.casefold() not in cert_lookup:
                warnings.append(f"Unsupported AI fact removed: {cert.name}")
                continue
            clean_certs.append(ResumeCertification(**cert_lookup[cert.name.casefold()].model_dump()))
        draft.certifications = clean_certs
        return ValidationResult(resume=draft, warnings=warnings)
