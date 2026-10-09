import json
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume, WorkflowResponse
from app.services.ai_provider import AIProvider, AIProviderError
from app.services.analysis_validator import AnalysisValidator
from app.services.fact_catalog import FactCatalog
from app.services.reference_cvs import ReferenceCVLibrary
from app.services.skills_bank import SkillsBank

ModelT = TypeVar("ModelT", bound=BaseModel)

TRUTH_RULES = """MASTER PROFILE IS THE ONLY SOURCE OF FACTS.
Do not invent skills, technologies, certifications, employers, education, projects, metrics, or responsibilities.
The verified skills bank is an evidence-backed index of master-profile facts. Select only supplied skill IDs;
never create a skill, change its trust state, or create evidence.
You may only select facts, change their order, shorten them, paraphrase them, and adapt wording to the job description.
Return only JSON matching the supplied schema. Do not return markdown or additional text."""


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        reference_library: ReferenceCVLibrary | None = None,
        skills_bank: SkillsBank | None = None,
    ):
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self.timeout = httpx.Timeout(
            settings.ollama_timeout_seconds,
            connect=min(settings.ollama_timeout_seconds, 10.0),
        )
        self.num_predict = settings.ollama_num_predict
        self.num_ctx = settings.ollama_num_ctx
        self.transport = transport
        self.reference_library = reference_library
        self.skills_bank = skills_bank

    async def _chat(
        self,
        response_model: type[ModelT],
        system_prompt: str,
        payload: dict,
        *,
        source_catalog: list[dict[str, str]] | None = None,
        allowed_skills: list[str] | None = None,
        allowed_skill_ids: list[str] | None = None,
    ) -> ModelT:
        schema = response_model.model_json_schema()
        if response_model is JobAnalysis and self.skills_bank:
            properties = schema["properties"]
            all_ids = [skill.id for skill in self.skills_bank.skills if skill.enabled]
            eligible_ids = [skill.id for skill in self.skills_bank.skills if self.skills_bank.eligible(skill)]
            learning_ids = [skill.id for skill in self.skills_bank.skills if skill.level == "learning"]
            properties["strong_skill_ids"]["items"]["enum"] = eligible_ids
            properties["partial_skill_ids"]["items"]["enum"] = all_ids
            properties["learning_skill_ids"]["items"]["enum"] = learning_ids
        if response_model is TailoredResume and source_catalog is not None:
            ids_by_type = {
                kind: [
                    entry["source_id"]
                    for entry in source_catalog
                    if entry["type"] == kind
                ]
                for kind in ("summary", "experience", "education", "project")
            }
            properties = schema["properties"]
            definitions = schema["$defs"]
            properties["summary_source_fact_ids"]["items"]["enum"] = ids_by_type["summary"]
            properties["summary_source_fact_ids"]["minItems"] = 1
            properties["core_skills"]["items"]["enum"] = allowed_skills or []
            properties["selected_skill_ids"]["items"]["enum"] = allowed_skill_ids or []
            properties["selected_skill_ids"]["minItems"] = min(8, len(allowed_skill_ids or []))
            properties["selected_skill_ids"]["maxItems"] = 16
            definitions["ResumeBullet"]["properties"]["source_fact_ids"]["items"]["enum"] = ids_by_type[
                "experience"
            ]
            definitions["ResumeProject"]["properties"]["source_fact_ids"]["items"]["enum"] = ids_by_type["project"]
            definitions["ResumeEducation"]["properties"]["source_fact_ids"]["items"]["enum"] = ids_by_type[
                "education"
            ]
            if ids_by_type["experience"]:
                properties["experience"]["minItems"] = 1
            if ids_by_type["education"]:
                properties["education"]["minItems"] = 1
            if ids_by_type["project"]:
                properties["projects"]["minItems"] = 1
        request = {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": schema,
            "options": {
                "temperature": 0,
                "num_predict": self.num_predict,
                "num_ctx": self.num_ctx,
            },
            "messages": [
                {"role": "system", "content": f"{TRUTH_RULES}\n\n{system_prompt}"},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.post("/api/chat", json=request)
                response.raise_for_status()
                envelope = response.json()
        except httpx.TimeoutException as exc:
            raise AIProviderError("Ollama timed out while generating the response. Try again.") from exc
        except httpx.RequestError as exc:
            raise AIProviderError("Cannot connect to Ollama. Check that the local Ollama service is running.") from exc
        except (httpx.HTTPStatusError, ValueError) as exc:
            raise AIProviderError("Ollama returned an invalid HTTP response.") from exc

        try:
            content = envelope["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message content is not text")
            return response_model.model_validate_json(content)
        except (KeyError, TypeError, ValidationError) as exc:
            raise AIProviderError("Ollama returned invalid structured JSON. Try again.") from exc

    async def analyze_job(self, job: JobRequest, profile: CandidateProfile) -> JobAnalysis:
        analysis = await self._chat(
            JobAnalysis,
            """Analyze the job against the master profile. Strong matches, partial matches, and supported keywords
must be supported by the master profile. Missing and unsupported requirements must come from the job description.
For skill matches, select exact IDs from skills_bank into strong_skill_ids, partial_skill_ids, or learning_skill_ids.
Never create a skill or evidence. A learning/unverified/disabled skill is Missing/Learning, never Strong. A basic
verified skill is Partial. For non-skill matches, populate match_sources with exact source_id values.
A strong match requires direct evidence. A partial match requires related transferable evidence. Never describe the
master profile as a template or infer a fact from the job description or reference CV.
Use a qualitative HIGH, MEDIUM, or LOW match and APPLY, REASONABLE_STRETCH, or SKIP recommendation.""",
            {
                "stage": "analyze_job",
                "job": job.model_dump(mode="json"),
                "master_profile": profile.model_dump(mode="json"),
                "source_catalog": FactCatalog(profile).for_prompt(),
                "skills_bank": self.skills_bank.for_prompt() if self.skills_bank else [],
            },
        )
        return AnalysisValidator(profile, self.skills_bank).validate(analysis, f"{job.role}\n{job.job_description}")

    async def tailor_resume(
        self,
        job: JobRequest,
        profile: CandidateProfile,
        analysis: JobAnalysis,
    ) -> TailoredResume:
        references = self.reference_library.select(job.role, job.job_description) if self.reference_library else []
        layout_guide = self.reference_library.layout_guide() if self.reference_library else {}
        catalog = FactCatalog(profile).for_prompt()
        eligible = [skill for skill in self.skills_bank.skills if self.skills_bank.eligible(skill)] if self.skills_bank else []
        allowed_skills = (
            list(dict.fromkeys(value for skill in eligible for value in (skill.name, self.skills_bank.wording(skill))))
            if self.skills_bank
            else [skill for values in profile.skills.values() for skill in values]
        )
        return await self._chat(
            TailoredResume,
            """Select and tailor a resume for the job. Use only exact source_id values supplied in source_catalog.
Set headline to the target role only. Python will deterministically append verified skills; never add technologies,
capabilities, requirements, or marketing wording to headline.
Every summary must reference summary source IDs. Every experience bullet must reference experience source IDs.
Every project must reference project source IDs and every education item must reference its education source ID.
Copy every source_id exactly and completely from source_catalog. Never shorten, construct, or guess an ID.
Select 8-16 relevant existing skill IDs in selected_skill_ids. Never create a skill or evidence. Learning, disabled,
unverified, and not-allowed skills must never be presented as experience. Select at most three skills from the
AI-Assisted Development subcategory. core_skills may contain only the corresponding supplied CV wording.
The source IDs, not string equality, bind paraphrased wording to verified facts.
Only include skills, education, and certifications present in the master profile. Source IDs are mandatory because
an independent Truth Lock will resolve them back to verified facts and reject unsupported content.
Reference CVs are style examples only. Never copy their people, employers, facts, metrics, skills, education,
certifications, projects, or responsibilities unless the same fact exists in the master profile.""",
            {
                "stage": "tailor_resume",
                "job": job.model_dump(mode="json"),
                "analysis": analysis.model_dump(mode="json"),
                "master_profile": profile.model_dump(mode="json"),
                "source_catalog": catalog,
                "skills_bank": self.skills_bank.for_prompt() if self.skills_bank else [],
                "reference_cvs_style_only": references,
                "layout_constraints": layout_guide,
            },
            source_catalog=catalog,
            allowed_skills=allowed_skills,
            allowed_skill_ids=[skill.id for skill in eligible],
        )

    async def tailor(self, job: JobRequest, profile: CandidateProfile) -> WorkflowResponse:
        analysis = await self.analyze_job(job, profile)
        resume = await self.tailor_resume(job, profile, analysis)
        return WorkflowResponse(analysis=analysis, resume=resume)

    async def health(self) -> dict[str, str]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(10.0, connect=3.0),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.get("/api/tags")
                response.raise_for_status()
                data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AIProviderError("Cannot connect to Ollama. Check that the local Ollama service is running.") from exc
        available = {
            value
            for item in data.get("models", [])
            if isinstance(item, dict)
            for value in (item.get("name"), item.get("model"))
            if isinstance(value, str)
        }
        if self.model not in available:
            raise AIProviderError(f"Ollama model {self.model} is not available.")
        return {"status": "ok", "provider": self.name, "model": self.model}
