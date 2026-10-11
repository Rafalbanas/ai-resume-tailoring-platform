import hashlib
from abc import ABC, abstractmethod
from typing import Any, Callable

from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume, WorkflowResponse


class AIProviderError(RuntimeError):
    """An AI provider failure that is safe to show to the user."""


class GeminiAuthError(AIProviderError):
    """Authentication or configuration failure for Gemini (invalid or missing key)."""


class GeminiQuotaError(AIProviderError):
    """Gemini quota or rate limit exceeded (HTTP 429)."""


class ProviderUnavailableError(AIProviderError):
    """Provider connection error, timeout, or transient 5xx."""


class ProviderResponseError(AIProviderError):
    """Provider returned malformed JSON or invalid schema."""


JOB_ANALYSIS_SYSTEM_PROMPT = """Analyze the job against the candidate master profile.
CRITICAL RULES FOR REQUIREMENTS AND MATCHING:
1. Extract requirements EXCLUSIVELY from the job description and target role. Every requirement must have a clear readable title.
2. DO NOT invent or assume requirements that do not appear in the job description (e.g., do not add ONVIF, VMS, CCNA, or AWS unless explicitly stated in the job text).
3. The candidate's master profile, source catalog, and skills bank are EVIDENCE ONLY. NEVER place source catalog IDs, skill IDs (e.g. skill:..., experience:..., summary:..., education:..., project:..., interest:...), or unused candidate facts/interests into missing_requirements!
4. missing_requirements may ONLY contain actual requirements from the job description for which there is no sufficient evidence in the candidate profile.
5. If a job requirement lists alternatives with OR (e.g. 'telecommunications or video conferencing'), confirmed evidence for ANY one alternative satisfies the requirement.
6. A candidate with an MSc in Computer Science (magisterka informatyczna) satisfies a requirement for a Degree or Diploma in Computer Science.
7. Experience with Salesforce provides direct evidence of CRM systems experience. Evaluate KCS (Knowledge Centered Service) methodology separately if mentioned in the job.
8. Describe any unconfirmed requirement as 'not confirmed in profile' (no confirmation in profile), not as candidate inability.
9. For skill matches, select exact IDs from skills_bank into strong_skill_ids, partial_skill_ids, or learning_skill_ids.
10. Use qualitative HIGH, MEDIUM, or LOW match and APPLY, REASONABLE_STRETCH, or SKIP recommendation based solely on the actual job requirements.
11. All generated reasoning, explanations and status messages MUST be in English. Preserve verbatim source quotes and proper names. Separate mandatory requirements, preferred requirements, responsibilities and organization context. Treat examples (such as) as examples, not cumulative mandatory certifications. If the analysis is incomplete, use UNRELIABLE / RETRY; never make a firm SKIP recommendation.
12. Keep reasoning_summary concise (max 3-5 sentences, summary of match strengths and genuine gaps)."""


def _digest(value: str) -> str:
    return hashlib.sha256(value.casefold().strip().encode()).hexdigest()[:12]


def clean_job_description(text: str) -> str:
    """Trim repetitive HR/legal footers like EEO statements while preserving requirements."""
    lines = text.splitlines()
    cleaned = []
    skip_rest = False
    for line in lines:
        stripped = line.strip()
        lower = stripped.casefold()
        if any(
            marker in lower
            for marker in (
                "eeo statement",
                "equal opportunity employer",
                "referral payment plan",
                "relocation provided",
                "travel requirements",
            )
        ):
            if "eeo statement" in lower or "equal opportunity employer" in lower or "referral payment plan" in lower:
                skip_rest = True
                continue
        if skip_rest:
            if "tech stack" in lower or "wymagania" in lower or "requirements" in lower or "qualifications" in lower or "preference" in lower:
                skip_rest = False
            else:
                continue
        cleaned.append(line)
    result = "\n".join(cleaned).strip()
    return result if len(result) >= 30 else text.strip()


def build_compact_analysis_payload(
    job: JobRequest,
    profile: CandidateProfile,
    skills_bank: Any = None,
) -> dict[str, Any]:
    cleaned_desc = job.job_description
    experience_summary = [
        {
            "title": exp.title,
            "company": exp.company,
            "dates": f"{exp.start} - {exp.end}",
            "bullets": exp.facts,
        }
        for exp in profile.experience
    ]
    education_summary = [
        {
            "institution": edu.institution,
            "qualification": edu.qualification,
            "specialisation": getattr(edu, "specialisation", ""),
            "dates": getattr(edu, "dates", getattr(edu, "year", "")),
        }
        for edu in profile.education
    ]
    projects_summary = [
        {
            "name": p.name,
            "description": p.description,
            "technologies": p.technologies,
            "bullets": p.facts,
        }
        for p in profile.projects
    ]
    compact_skills = []
    if skills_bank and hasattr(skills_bank, "skills"):
        job_text = f"{job.role}\n{cleaned_desc}".casefold()
        relevant_skills = {}
        for s in skills_bank.skills:
            if not getattr(s, "enabled", True):
                continue
            is_candidate = hasattr(skills_bank, "confirmed_profile_skill") and skills_bank.confirmed_profile_skill(s)
            is_mentioned = hasattr(skills_bank, "mentioned") and skills_bank.mentioned(s, job_text)
            if is_candidate or is_mentioned:
                relevant_skills[s.id] = s
        if not relevant_skills:
            for s in skills_bank.skills[:40]:
                if getattr(s, "enabled", True):
                    relevant_skills[s.id] = s
        for s in relevant_skills.values():
            compact_skills.append({
                "id": s.id,
                "name": s.name,
                "category": getattr(s, "category", ""),
                "level": getattr(s, "level", ""),
            })
    return {
        "stage": "analyze_job",
        "job": {
            "company": job.company,
            "role": job.role,
            "job_description": cleaned_desc,
        },
        "candidate": {
            "title": profile.experience[0].title if profile.experience else "",
            "summary_facts": profile.summary_facts,
            "experience": experience_summary,
            "education": education_summary,
            "projects": projects_summary,
        },
        "skills_bank": compact_skills,
    }


def build_compact_tailor_payload(
    job: JobRequest,
    profile: CandidateProfile,
    analysis: JobAnalysis,
    skills_bank: Any = None,
    layout_guide: dict[str, Any] | None = None,
    references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    grouped_facts = {
        "summary": [
            {"source_id": f"summary:{_digest(f)}", "text": f}
            for f in profile.summary_facts
        ],
        "experience": [
            {
                "company": exp.company,
                "title": exp.title,
                "dates": f"{exp.start} - {exp.end}",
                "bullets": [
                    {
                        "source_id": f"experience:{_digest('|'.join([exp.company, exp.title, exp.start, exp.end]))}:fact:{_digest(fact)}",
                        "text": fact,
                    }
                    for fact in exp.facts
                ],
            }
            for exp in profile.experience
        ],
        "education": [
            {
                "source_id": f"education:{_digest('|'.join([edu.institution, getattr(edu, 'qualification', ''), getattr(edu, 'dates', getattr(edu, 'year', ''))]))}",
                "institution": edu.institution,
                "qualification": getattr(edu, "qualification", ""),
                "dates": getattr(edu, "dates", getattr(edu, "year", "")),
                "specialisation": getattr(edu, "specialisation", ""),
            }
            for edu in profile.education
        ],
        "projects": [
            {
                "name": prj.name,
                "description": prj.description,
                "technologies": prj.technologies,
                "bullets": [
                    {
                        "source_id": f"project:{_digest(prj.name)}:fact:{_digest(fact)}",
                        "text": fact,
                    }
                    for fact in prj.facts
                ],
            }
            for prj in profile.projects
        ],
    }
    eligible_skills = []
    if skills_bank and hasattr(skills_bank, "skills"):
        job_text = f"{job.role}\n{job.job_description}".casefold()
        for s in skills_bank.skills:
            if hasattr(skills_bank, "eligible") and skills_bank.eligible(s):
                is_candidate = hasattr(skills_bank, "confirmed_profile_skill") and skills_bank.confirmed_profile_skill(s)
                is_mentioned = hasattr(skills_bank, "mentioned") and skills_bank.mentioned(s, job_text)
                is_matched = (
                    s.name in analysis.strong_matches
                    or s.name in analysis.partial_matches
                    or s.id in analysis.strong_skill_ids
                    or s.id in getattr(analysis, "partial_skill_ids", [])
                )
                if is_candidate or is_mentioned or is_matched:
                    wording = skills_bank.wording(s) if hasattr(skills_bank, "wording") else s.name
                    eligible_skills.append({
                        "id": s.id,
                        "name": s.name,
                        "wording": wording,
                    })
        if not eligible_skills:
            for s in skills_bank.skills[:35]:
                if hasattr(skills_bank, "eligible") and skills_bank.eligible(s):
                    wording = skills_bank.wording(s) if hasattr(skills_bank, "wording") else s.name
                    eligible_skills.append({
                        "id": s.id,
                        "name": s.name,
                        "wording": wording,
                    })
    analysis_reqs = []
    if hasattr(analysis, "requirements") and analysis.requirements:
        analysis_reqs = [r.name if hasattr(r, "name") else str(r) for r in analysis.requirements][:10]
    elif hasattr(analysis, "missing_requirements"):
        analysis_reqs = list(analysis.missing_requirements)[:10]

    return {
        "stage": "tailor_resume",
        "target_role": job.role,
        "target_company": job.company,
        "analysis_summary": {
            "strong_matches": analysis.strong_matches,
            "strong_skill_ids": analysis.strong_skill_ids,
            "key_requirements": analysis_reqs,
        },
        "candidate_facts": grouped_facts,
        "eligible_skills": eligible_skills,
        "reference_cvs_style_only": references or [],
        "layout_guide": layout_guide or {},
        "layout_constraints": layout_guide or {},
    }


class AIProvider(ABC):
    name: str = "unknown"
    model: str = "unknown"

    @abstractmethod
    async def tailor(
        self,
        job: JobRequest,
        profile: CandidateProfile,
        on_stage: Callable[[str], None] | None = None,
    ) -> WorkflowResponse:
        """Analyze a job and return a source-referenced resume draft."""

    async def analyze_job(self, job: JobRequest, profile: CandidateProfile) -> JobAnalysis:
        """Analyze the job against candidate profile."""
        response = await self.tailor(job, profile)
        return response.analysis

    async def tailor_resume(
        self, job: JobRequest, profile: CandidateProfile, analysis: JobAnalysis
    ) -> TailoredResume:
        """Generate tailored resume for the job."""
        response = await self.tailor(job, profile)
        return response.resume

    async def health(self) -> dict[str, str]:
        """Return provider readiness without processing private candidate data."""
        return {"status": "ok", "provider": self.name, "model": self.model}

