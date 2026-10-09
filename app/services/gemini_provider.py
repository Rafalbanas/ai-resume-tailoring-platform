import asyncio
import copy
import json
import logging
import re
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume, WorkflowResponse
from app.services.ai_provider import (
    AIProvider,
    AIProviderError,
    GeminiAuthError,
    GeminiQuotaError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from app.services.analysis_validator import AnalysisValidator
from app.services.fact_catalog import FactCatalog
from app.services.ollama_provider import TRUTH_RULES
from app.services.reference_cvs import ReferenceCVLibrary
from app.services.skills_bank import SkillsBank

logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)

ALLOWED_GEMINI_SCHEMA_KEYS = {
    "type",
    "format",
    "description",
    "nullable",
    "enum",
    "properties",
    "required",
    "items",
}


def to_gemini_schema(schema: dict) -> dict:
    """Convert a Pydantic JSON schema into Google Gemini OpenAPI 3.0 subset.

    Inlines all $defs and $ref references, strips disallowed keys such as title,
    default, minItems, maxItems, and additionalProperties.
    """
    schema_copy = copy.deepcopy(schema)
    defs = schema_copy.pop("$defs", {})

    def resolve(node):
        if not isinstance(node, dict):
            if isinstance(node, list):
                return [resolve(x) for x in node]
            return node
        if "$ref" in node:
            ref_name = node["$ref"].split("/")[-1]
            target = copy.deepcopy(defs.get(ref_name, {}))
            resolved_target = resolve(target)
            merged = {}
            for k, v in resolved_target.items():
                if k in ALLOWED_GEMINI_SCHEMA_KEYS:
                    merged[k] = (
                        {pk: resolve(pv) for pk, pv in v.items()}
                        if k == "properties" and isinstance(v, dict)
                        else v
                    )
            for k, v in node.items():
                if k != "$ref" and k in ALLOWED_GEMINI_SCHEMA_KEYS:
                    merged[k] = (
                        {pk: resolve(pv) for pk, pv in v.items()}
                        if k == "properties" and isinstance(v, dict)
                        else resolve(v)
                    )
            return merged

        clean = {}
        for k, v in node.items():
            if k in ALLOWED_GEMINI_SCHEMA_KEYS:
                clean[k] = (
                    {pk: resolve(pv) for pk, pv in v.items()}
                    if k == "properties" and isinstance(v, dict)
                    else resolve(v)
                )
        if "properties" in clean and "type" not in clean:
            clean["type"] = "object"
        if "items" in clean and "type" not in clean:
            clean["type"] = "array"
        return clean

    return resolve(schema_copy)


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        reference_library: ReferenceCVLibrary | None = None,
        skills_bank: SkillsBank | None = None,
    ):
        self.api_key = (settings.gemini_api_key or "").strip()
        self.model = (settings.gemini_model or "gemini-2.5-flash").strip()
        self.base_url = (settings.gemini_base_url or "https://generativelanguage.googleapis.com").rstrip("/")
        self.connect_timeout = getattr(settings, "gemini_connect_timeout_seconds", 10.0)
        self.read_timeout = getattr(
            settings,
            "gemini_read_timeout_seconds",
            getattr(settings, "gemini_timeout_seconds", 60.0),
        )
        self.timeout = httpx.Timeout(
            self.read_timeout,
            connect=self.connect_timeout,
            write=30.0,
            pool=10.0,
        )
        self.max_retries = max(0, int(settings.gemini_max_retries))
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
        if not self.api_key:
            raise GeminiAuthError("Gemini API key is not configured. Set GEMINI_API_KEY in your environment.")

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
            definitions = schema.get("$defs", {})
            properties["summary_source_fact_ids"]["items"]["enum"] = ids_by_type["summary"]
            properties["core_skills"]["items"]["enum"] = allowed_skills or []
            properties["selected_skill_ids"]["items"]["enum"] = allowed_skill_ids or []
            if "ResumeBullet" in definitions:
                definitions["ResumeBullet"]["properties"]["source_fact_ids"]["items"]["enum"] = ids_by_type[
                    "experience"
                ]
            if "ResumeProject" in definitions:
                definitions["ResumeProject"]["properties"]["source_fact_ids"]["items"]["enum"] = ids_by_type["project"]
                project_names = list(
                    dict.fromkeys(entry["owner"] for entry in source_catalog if entry["type"] == "project")
                )
                definitions["ResumeProject"]["properties"]["name"]["enum"] = project_names
                definitions["ResumeProject"]["properties"]["technologies"]["items"]["enum"] = allowed_skills or []
            if "ResumeEducation" in definitions:
                definitions["ResumeEducation"]["properties"]["source_fact_ids"]["items"]["enum"] = ids_by_type[
                    "education"
                ]

        gemini_schema = to_gemini_schema(schema)

        request_body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": json.dumps(payload, ensure_ascii=False)}],
                }
            ],
            "systemInstruction": {
                "parts": [{"text": f"{TRUTH_RULES}\n\n{system_prompt}"}],
            },
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json",
                "responseSchema": gemini_schema,
            },
        }

        url = f"{self.base_url}/v1beta/models/{self.model}:generateContent"
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(
                    timeout=self.timeout,
                    follow_redirects=False,
                    transport=self.transport,
                ) as client:
                    response = await client.post(url, json=request_body, headers=headers)

                if response.status_code in (401, 403):
                    logger.error("Gemini authentication failed (status %s)", response.status_code)
                    raise GeminiAuthError(
                        "Gemini API key is invalid or lacks permission. Check your GEMINI_API_KEY configuration."
                    )

                if response.status_code == 429:
                    retry_after_str = response.headers.get("Retry-After")
                    retry_sec = None
                    if retry_after_str:
                        try:
                            retry_sec = float(retry_after_str)
                        except ValueError:
                            pass
                    if attempt < self.max_retries and retry_sec is not None and 0 < retry_sec <= 3.0:
                        logger.warning("Gemini 429 rate limit hit, backing off %s seconds", retry_sec)
                        await asyncio.sleep(retry_sec)
                        continue
                    raise GeminiQuotaError(
                        f"Gemini API rate limit or quota exceeded (HTTP 429). {f'Retry-After: {retry_sec}s' if retry_sec else ''}".strip()
                    )

                if response.status_code in (500, 502, 503, 504):
                    if attempt < self.max_retries:
                        logger.warning(
                            "Gemini transient error HTTP %s on attempt %s, retrying",
                            response.status_code,
                            attempt + 1,
                        )
                        await asyncio.sleep(1.0)
                        continue
                    raise ProviderUnavailableError(
                        f"Gemini service is temporarily unavailable (HTTP {response.status_code})."
                    )

                if response.status_code >= 400:
                    detail = response.text[:250]
                    raise AIProviderError(f"Gemini API returned HTTP {response.status_code}: {detail}")

                envelope = response.json()
                break

            except (GeminiAuthError, GeminiQuotaError):
                raise
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt < self.max_retries:
                    logger.warning("Gemini timed out on attempt %s, retrying", attempt + 1)
                    await asyncio.sleep(1.0)
                    continue
                raise ProviderUnavailableError("Gemini timed out while generating the response.") from exc
            except httpx.RequestError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    logger.warning("Gemini connection error on attempt %s, retrying", attempt + 1)
                    await asyncio.sleep(1.0)
                    continue
                raise ProviderUnavailableError("Cannot connect to Gemini API. Check your network.") from exc
        else:
            raise ProviderUnavailableError("Gemini failed after retry attempts.") from last_error

        # Parse structured candidates
        try:
            candidates = envelope.get("candidates", [])
            if not candidates:
                raise ValueError("No candidates returned in Gemini response.")
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                raise ValueError("No content parts in Gemini candidate response.")
            raw_text = parts[0].get("text", "")
            if not isinstance(raw_text, str) or not raw_text.strip():
                raise ValueError("Empty text received from Gemini.")
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderResponseError("Gemini returned invalid or missing response envelope.") from exc

        # Validate against response_model
        try:
            return response_model.model_validate_json(raw_text)
        except (ValidationError, json.JSONDecodeError):
            # Attempt stripping markdown block if model added formatting
            clean_text = raw_text.strip()
            if clean_text.startswith("```"):
                clean_text = re.sub(r"^```(?:json)?\s*", "", clean_text)
                clean_text = re.sub(r"\s*```$", "", clean_text)
            try:
                return response_model.model_validate_json(clean_text)
            except (ValidationError, json.JSONDecodeError) as exc:
                logger.error("Gemini structured JSON validation error: %s", exc)
                raise ProviderResponseError("Gemini returned invalid structured JSON. Try again.") from exc

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
        eligible = (
            [skill for skill in self.skills_bank.skills if self.skills_bank.eligible(skill)]
            if self.skills_bank
            else []
        )
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
Every project must use a supplied project name, reference project source IDs, and keep project identity in name.
Project technologies may contain only supplied skill wording; never place a project name in technologies.
Every education item must reference its education source ID.
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
        return WorkflowResponse(analysis=analysis, resume=resume, provider_used=self.name, model_used=self.model)

    async def health(self) -> dict[str, str]:
        if not self.api_key:
            return {
                "status": "unconfigured",
                "provider": self.name,
                "model": self.model,
                "error": "GEMINI_API_KEY is not set",
            }
        url = f"{self.base_url}/v1beta/models/{self.model}"
        headers = {"x-goog-api-key": self.api_key}
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(self.connect_timeout + 5.0, connect=self.connect_timeout),
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                response = await client.get(url, headers=headers)
                if response.status_code in (401, 403):
                    raise GeminiAuthError("Gemini API key is invalid.")
                response.raise_for_status()
        except GeminiAuthError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise AIProviderError("Cannot connect to Gemini API. Check configuration.") from exc

        return {"status": "ok", "provider": self.name, "model": self.model}
