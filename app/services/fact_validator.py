import re
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
from app.services.fact_catalog import FactCatalog, normalized_tokens
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

        verified_headline = self._build_headline(job.role, draft.selected_skill_ids, draft.core_skills)
        if draft.headline.strip() and draft.headline.strip() not in {job.role.strip(), verified_headline}:
            warnings.append("Unsupported or non-deterministic headline was replaced with verified role and skills")
        draft.headline = verified_headline

        summary_entries = self.catalog.valid(draft.summary_source_fact_ids, kind="summary")[:4]
        if not summary_entries:
            summary_entries = [entry for entry in self.catalog.prompt_entries if entry.kind == "summary"][:3]
        summary_ids = [entry.source_id for entry in summary_entries]
        summary_supported = self.catalog.supports_paraphrase(draft.professional_summary, summary_ids)
        summary_complete = self._is_complete_summary(draft.professional_summary)
        if not summary_supported or not summary_complete:
            if draft.professional_summary:
                reason = "unsupported" if not summary_supported else "truncated or incomplete"
                warnings.append(f"The {reason} professional summary was replaced with source facts")
            draft.professional_summary = " ".join(self._complete_sentence(entry.text) for entry in summary_entries)
        draft.summary_source_fact_ids = summary_ids
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
            verified_technologies = [
                allowed_skills[skill_key(tech)] for tech in source.technologies if skill_key(tech) in allowed_skills
            ]
            requested_technologies = []
            unsupported_technologies = []
            for value in project.technologies:
                canonical = allowed_skills.get(skill_key(value))
                if canonical:
                    requested_technologies.append(canonical)
                else:
                    unsupported_technologies.append(value)
            source_technology_keys = {skill_key(value) for value in verified_technologies}
            unsupported_technologies.extend(
                value for value in requested_technologies if skill_key(value) not in source_technology_keys
            )
            if unsupported_technologies:
                warnings.append(
                    f"Unsupported technologies removed from project {project.name}: "
                    f"{', '.join(dict.fromkeys(unsupported_technologies))}"
                )
            project.technologies = verified_technologies
            project.source_fact_ids = valid_ids
            clean_projects.append(project)
        selected_project_names = {project.name.casefold() for project in clean_projects}
        for index, source in enumerate(self.profile.projects):
            if source.name.casefold() in selected_project_names:
                continue
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
        ranked_projects = self._rank_projects(clean_projects, job)
        if len(ranked_projects) > 2 and self._project_relevance(ranked_projects[2], job) > 0:
            draft.projects = ranked_projects[:3]
        else:
            draft.projects = ranked_projects[:2]
        thesis_in_projects = any("thesis" in p.name.casefold() for p in draft.projects)

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
            thesis_subline = ""
            specialisation = ""
            if not thesis_in_projects and getattr(source, "thesis_title", None):
                thesis_subline = f"Thesis: {source.thesis_title}"
            if getattr(source, "specialisation", None):
                specialisation = f"Specialisation: {source.specialisation}"
            clean_education.append(
                ResumeEducation(
                    institution=source.institution,
                    qualification=source.qualification,
                    dates=source.dates,
                    specialisation=specialisation,
                    thesis_subline=thesis_subline,
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
                thesis_subline = ""
                specialisation = ""
                if not thesis_in_projects and getattr(source, "thesis_title", None):
                    thesis_subline = f"Thesis: {source.thesis_title}"
                if getattr(source, "specialisation", None):
                    specialisation = f"Specialisation: {source.specialisation}"
                clean_education.append(
                    ResumeEducation(
                        institution=source.institution,
                        qualification=source.qualification,
                        dates=source.dates,
                        specialisation=specialisation,
                        thesis_subline=thesis_subline,
                        source_fact_ids=[main_entry.source_id] if main_entry else [],
                    )
                )
        draft.education = clean_education

        allowed_interests = {
            interest.name.casefold(): interest
            for interest in getattr(self.profile, "interests", [])
            if interest.verified and interest.allowed_in_cv and interest.enabled
        }
        clean_interests = []
        selected_interest_ids = []
        if draft.interests:
            for item in draft.interests:
                canonical = allowed_interests.get(item.casefold())
                if canonical and canonical.name not in clean_interests:
                    clean_interests.append(canonical.name)
                    selected_interest_ids.append(canonical.id)
                elif not canonical:
                    warnings.append(f"Unsupported interest removed: {item}")
        else:
            for interest in allowed_interests.values():
                if interest.name not in clean_interests:
                    clean_interests.append(interest.name)
                    selected_interest_ids.append(interest.id)

        draft.interests = clean_interests
        draft.selected_interest_ids = selected_interest_ids

        cert_lookup = {item.name.casefold(): item for item in self.profile.certifications}
        clean_certs = []
        for cert in draft.certifications:
            if cert.name.casefold() not in cert_lookup:
                warnings.append(f"Unsupported AI fact removed: {cert.name}")
                continue
            clean_certs.append(ResumeCertification(**cert_lookup[cert.name.casefold()].model_dump()))
        draft.certifications = clean_certs
        return ValidationResult(resume=draft, warnings=warnings)

    def _build_headline(self, role: str, selected_ids: list[str], core_skills: list[str]) -> str:
        capabilities: list[str] = []
        generic_names = {
            "troubleshooting",
            "technical troubleshooting",
            "technical documentation",
            "runbooks",
            "operational runbooks",
            "documentation",
            "tier 2 support",
            "tier 1 support",
            "incident handling",
            "customer service",
            "user support",
        }
        if self.skills_bank:
            hard_skills: list[str] = []
            generic_skills: list[str] = []
            for skill_id in selected_ids:
                skill = self.skills_bank.get(skill_id)
                if skill and self.skills_bank.eligible(skill):
                    if skill.name.casefold() in generic_names or skill.category == "Support / Operations":
                        if skill.name not in generic_skills:
                            generic_skills.append(skill.name)
                    else:
                        if skill.name not in hard_skills:
                            hard_skills.append(skill.name)
            capabilities = hard_skills + generic_skills
        else:
            allowed = {value.casefold(): value for values in self.profile.skills.values() for value in values}
            for value in core_skills:
                canonical = allowed.get(value.casefold())
                if canonical and canonical not in capabilities:
                    capabilities.append(canonical)

        parts = [role.strip()]
        for capability in capabilities:
            candidate = " | ".join([*parts, capability])
            if len(candidate) > 75 and len(parts) >= 3:
                break
            if len(parts) >= 4:
                break
            parts.append(capability)
        return " | ".join(parts)[:100]

    @staticmethod
    def _is_complete_summary(value: str) -> bool:
        text = value.strip()
        if not text or text[-1] not in ".!?" or text.count("(") != text.count(")"):
            return False
        sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
        if any(len(re.findall(r"[\w'-]+", sentence)) < 4 for sentence in sentences):
            return False
        hanging = re.compile(r"\b(?:and|or|including|such as|cross-tier|cross-functional)[.!?]$", re.I)
        return not any(hanging.search(sentence) for sentence in sentences)

    @staticmethod
    def _complete_sentence(value: str) -> str:
        text = value.strip()
        return text if not text or text[-1] in ".!?" else f"{text}."

    def _project_relevance(self, project: ResumeProject, job: JobRequest) -> int:
        job_tokens = normalized_tokens(f"{job.role} {job.job_description}")
        role_tokens = normalized_tokens(job.role)
        generic = {
            "built",
            "control",
            "data",
            "hands",
            "human",
            "job",
            "large",
            "pipeline",
            "project",
            "review",
            "services",
            "source",
            "that",
            "using",
            "workflows",
        }
        profile_projects = {p.name.casefold(): p for p in self.profile.projects}
        source = profile_projects.get(project.name.casefold())
        technologies = source.technologies if source else project.technologies
        facts = source.facts if source else [project.description]
        tech_tokens = normalized_tokens(" ".join(technologies))
        fact_tokens = normalized_tokens(" ".join(facts)) - generic
        tech_role_overlap = len(role_tokens & tech_tokens)
        tech_job_overlap = len(job_tokens & tech_tokens)
        fact_overlap = len(job_tokens & fact_tokens)
        return 8 * tech_role_overlap + 4 * tech_job_overlap + 2 * fact_overlap

    def _rank_projects(self, projects: list[ResumeProject], job: JobRequest) -> list[ResumeProject]:
        profile_projects = {project.name.casefold(): project for project in self.profile.projects}

        def score(project: ResumeProject) -> tuple[int, int, str]:
            source = profile_projects.get(project.name.casefold())
            technologies = source.technologies if source else project.technologies
            relevance = self._project_relevance(project, job)
            return relevance, len(technologies), project.name

        return sorted(projects, key=score, reverse=True)

