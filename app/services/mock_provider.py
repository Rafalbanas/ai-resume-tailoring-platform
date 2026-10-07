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


class MockAIProvider(AIProvider):
    """Deterministic local provider for development and end-to-end smoke tests."""

    async def tailor(self, job: JobRequest, profile: CandidateProfile) -> WorkflowResponse:
        description = job.job_description.casefold()
        all_skills = [s for values in profile.skills.values() for s in values]
        matches = [s for s in all_skills if re.search(rf"\b{re.escape(s.casefold())}\b", description)]
        partial = [s for s in all_skills if s not in matches][:4]
        known_terms = ["kubernetes", "terraform", "aws", "azure", "ccna", "docker", "python", "linux"]
        missing = [term.title() for term in known_terms if term in description and term.casefold() not in profile.skill_set()]
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
            supported_keywords=matches[:12],
            unsupported_keywords=missing,
            recommendation=recommendation,
            match_level=level,
            reasoning_summary=(
                "The recommendation compares explicit profile facts with the advertised requirements; "
                "it is qualitative rather than a fabricated precision score."
            ),
        )
        summary_ids = [f"summary:{i}" for i in range(min(3, len(profile.summary_facts)))]
        experience = []
        for exp_index, item in enumerate(profile.experience[:3]):
            bullets = [
                ResumeBullet(text=fact, source_fact_ids=[f"experience:{exp_index}:fact:{fact_index}"])
                for fact_index, fact in enumerate(item.facts[:4])
            ]
            experience.append(
                ResumeExperience(
                    company=item.company,
                    title=item.title,
                    dates=" – ".join(filter(None, [item.start, item.end])),
                    bullets=bullets,
                )
            )
        projects = [
            ResumeProject(
                name=project.name,
                description=project.description,
                technologies=project.technologies,
                source_fact_ids=[f"project:{i}:fact:{j}" for j in range(len(project.facts))] or [f"project:{i}:description"],
            )
            for i, project in enumerate(profile.projects[:2])
        ]
        resume = TailoredResume(
            headline=f"{job.role} | {' • '.join(matches[:3] or all_skills[:3])}",
            professional_summary=" ".join(profile.summary_facts[:3]),
            summary_source_fact_ids=summary_ids,
            core_skills=(matches + [s for s in all_skills if s not in matches])[:12],
            experience=experience,
            education=[ResumeEducation(**item.model_dump(exclude={"facts"})) for item in profile.education],
            projects=projects,
            certifications=[ResumeCertification(**item.model_dump()) for item in profile.certifications],
        )
        return WorkflowResponse(analysis=analysis, resume=resume)
