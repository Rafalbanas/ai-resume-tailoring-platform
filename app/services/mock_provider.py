import re

from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis, JobRequest, MatchLevel, Recommendation
from app.models.resume import (
    ResumeBullet,
    ResumeCertification,
    ResumeEducation,
    ResumeExperience,
    ResumeProject,
    TailoredResume,
    WorkflowResponse,
)
from app.services.ai_provider import AIProvider
from app.services.fact_catalog import FactCatalog
from app.services.skills_bank import SkillsBank


class MockAIProvider(AIProvider):
    """Deterministic local provider for development and end-to-end smoke tests."""

    name = "mock"

    def __init__(self, skills_bank: SkillsBank | None = None):
        self.skills_bank = skills_bank

    async def tailor(self, job: JobRequest, profile: CandidateProfile) -> WorkflowResponse:
        catalog = FactCatalog(profile)
        description = job.job_description.casefold()
        all_skills = [s for values in profile.skills.values() for s in values]
        bank_matches = (
            [skill for skill in self.skills_bank.skills if self.skills_bank.eligible(skill) and self.skills_bank.mentioned(skill, description)]
            if self.skills_bank
            else []
        )
        matches = [skill.name for skill in bank_matches] or [
            s for s in all_skills if re.search(rf"\b{re.escape(s.casefold())}\b", description)
        ]
        partial = [s for s in all_skills if s not in matches][:4]
        known_terms = ["kubernetes", "terraform", "aws", "azure", "ccna", "docker", "python", "linux"]
        missing = [
            term.title() for term in known_terms if term in description and term.casefold() not in profile.skill_set()
        ]
        level = MatchLevel.HIGH if len(matches) >= 5 else MatchLevel.MEDIUM if matches else MatchLevel.LOW
        recommendation = {
            MatchLevel.HIGH: Recommendation.APPLY,
            MatchLevel.MEDIUM: Recommendation.REASONABLE_STRETCH,
            MatchLevel.LOW: Recommendation.SKIP,
        }[level]
        analysis = JobAnalysis(
            company=job.company,
            role=job.role,
            strong_matches=matches[:8],
            partial_matches=partial,
            missing_requirements=missing,
            match_sources={
                match: catalog.direct_sources(match) for match in matches + partial if catalog.direct_sources(match)
            },
            strong_skill_ids=[skill.id for skill in bank_matches if skill.level != "basic"],
            partial_skill_ids=[skill.id for skill in bank_matches if skill.level == "basic"],
            supported_keywords=matches[:12],
            unsupported_keywords=missing,
            recommendation=recommendation,
            match_level=level,
            reasoning_summary=(
                "The recommendation compares explicit profile facts with the advertised requirements; "
                "it is qualitative rather than a fabricated precision score."
            ),
        )
        summary_ids = [entry.source_id for entry in catalog.prompt_entries if entry.kind == "summary"][:3]
        experience = []
        for exp_index, item in enumerate(profile.experience[:3]):
            entries = [
                entry
                for entry in catalog.prompt_entries
                if entry.kind == "experience" and entry.owner_index == exp_index
            ][:4]
            bullets = [ResumeBullet(text=entry.text, source_fact_ids=[entry.source_id]) for entry in entries]
            experience.append(
                ResumeExperience(
                    company=item.company,
                    title=item.title,
                    dates=" – ".join(filter(None, [item.start, item.end])),
                    bullets=bullets,
                )
            )
        projects = []
        for index, project in enumerate(profile.projects[:2]):
            entries = [
                entry for entry in catalog.prompt_entries if entry.kind == "project" and entry.owner_index == index
            ]
            projects.append(
                ResumeProject(
                    name=project.name,
                    description=project.description,
                    technologies=project.technologies,
                    source_fact_ids=[entry.source_id for entry in entries],
                )
            )
        education = []
        for index, item in enumerate(profile.education):
            source = next(
                (
                    entry.source_id
                    for entry in catalog.prompt_entries
                    if entry.kind == "education" and entry.owner_index == index and ":fact:" not in entry.source_id
                ),
                "",
            )
            education.append(
                ResumeEducation(
                    **item.model_dump(exclude={"facts"}),
                    source_fact_ids=[source] if source else [],
                )
            )
        selected = self.skills_bank.select_for_job(
            [skill.id for skill in bank_matches], f"{job.role}\n{job.job_description}"
        ) if self.skills_bank else []
        resume = TailoredResume(
            headline=job.role,
            professional_summary=" ".join(profile.summary_facts[:3]),
            summary_source_fact_ids=summary_ids,
            core_skills=[self.skills_bank.wording(skill) for skill in selected] if self.skills_bank else (
                matches + [s for s in all_skills if s not in matches]
            )[:12],
            selected_skill_ids=[skill.id for skill in selected],
            experience=experience,
            education=education,
            projects=projects,
            certifications=[ResumeCertification(**item.model_dump()) for item in profile.certifications],
        )
        return WorkflowResponse(analysis=analysis, resume=resume, provider_used=self.name, model_used=self.name)
