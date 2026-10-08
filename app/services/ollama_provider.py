import json
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume, WorkflowResponse
from app.services.ai_provider import AIProvider, AIProviderError
from app.services.reference_cvs import ReferenceCVLibrary

ModelT = TypeVar("ModelT", bound=BaseModel)

TRUTH_RULES = """MASTER PROFILE IS THE ONLY SOURCE OF FACTS.
Do not invent skills, technologies, certifications, employers, education, projects, metrics, or responsibilities.
You may only select facts, change their order, shorten them, paraphrase them, and adapt wording to the job description.
Return only JSON matching the supplied schema. Do not return markdown or additional text."""


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        reference_library: ReferenceCVLibrary | None = None,
    ):
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model
        self.timeout = httpx.Timeout(
            settings.ollama_timeout_seconds,
            connect=min(settings.ollama_timeout_seconds, 10.0),
        )
        self.transport = transport
        self.reference_library = reference_library

    async def _chat(self, response_model: type[ModelT], system_prompt: str, payload: dict) -> ModelT:
        request = {
            "model": self.model,
            "stream": False,
            "think": False,
            "format": response_model.model_json_schema(),
            "options": {"temperature": 0},
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
        return await self._chat(
            JobAnalysis,
            """Analyze the job against the master profile. Strong matches, partial matches, and supported keywords
must be supported by the master profile. Missing and unsupported requirements must come from the job description.
Use a qualitative HIGH, MEDIUM, or LOW match and APPLY, REASONABLE_STRETCH, or SKIP recommendation.""",
            {
                "stage": "analyze_job",
                "job": job.model_dump(mode="json"),
                "master_profile": profile.model_dump(mode="json"),
            },
        )

    async def tailor_resume(
        self,
        job: JobRequest,
        profile: CandidateProfile,
        analysis: JobAnalysis,
    ) -> TailoredResume:
        references = self.reference_library.select(job.role, job.job_description) if self.reference_library else []
        layout_guide = self.reference_library.layout_guide() if self.reference_library else {}
        return await self._chat(
            TailoredResume,
            """Select and tailor a resume for the job. Every summary statement must reference summary:N.
Every experience bullet must reference experience:N:fact:M and must use the matching employer and title.
Every project must reference project:N:description or project:N:fact:M and use the matching project name.
Only include skills, education, and certifications present in the master profile. Source IDs are mandatory because
an independent Truth Lock will resolve them back to the exact source facts and remove unsupported content.
Reference CVs are style examples only. Never copy their people, employers, facts, metrics, skills, education,
certifications, projects, or responsibilities unless the same fact exists in the master profile.""",
            {
                "stage": "tailor_resume",
                "job": job.model_dump(mode="json"),
                "analysis": analysis.model_dump(mode="json"),
                "master_profile": profile.model_dump(mode="json"),
                "reference_cvs_style_only": references,
                "layout_constraints": layout_guide,
            },
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
