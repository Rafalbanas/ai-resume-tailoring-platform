import asyncio
import copy
import json
import logging
import re
from typing import Any, Callable, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.core.config import Settings
from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume, WorkflowResponse
from app.services.ai_provider import (
    JOB_ANALYSIS_SYSTEM_PROMPT,
    AIProvider,
    AIProviderError,
    GeminiAuthError,
    GeminiQuotaError,
    ProviderResponseError,
    ProviderUnavailableError,
    build_compact_analysis_payload,
    build_compact_tailor_payload,
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

        # Gemini OpenAPI requirement: object types MUST specify non-empty properties
        if "properties" in clean and isinstance(clean["properties"], dict):
            valid_props = {}
            for pk, pv in clean["properties"].items():
                if isinstance(pv, dict) and pv.get("type") == "object" and not pv.get("properties"):
                    continue
                valid_props[pk] = pv
            clean["properties"] = valid_props
            if "required" in clean and isinstance(clean["required"], list):
                clean["required"] = [r for r in clean["required"] if r in valid_props]

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
        self.model = (settings.gemini_model or "gemini-3.1-flash-lite").strip()
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
        gemini_schema = to_gemini_schema(schema)

        generation_config: dict[str, Any] = {
            "temperature": 0.0,
            "responseMimeType": "application/json",
            "responseSchema": gemini_schema,
        }
        # In Gemini 3.x (including gemini-3.1-flash-lite), reasoning uses thinkingLevel ("minimal" for low-latency tasks)
        if "gemini-3" in self.model or "flash-lite" in self.model:
            generation_config["thinkingConfig"] = {"thinkingLevel": "minimal"}
        elif "gemini-2.5" in self.model:
            generation_config["thinkingConfig"] = {"thinkingBudget": 0}

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
            "generationConfig": generation_config,
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

                if response.status_code == 404:
                    logger.error("Gemini model not found (status 404): %s", self.model)
                    raise ProviderUnavailableError(
                        f"Model Gemini '{self.model}' jest niedostępny lub wycofany dla tego konta API. Zaktualizuj GEMINI_MODEL w konfiguracji."
                    )

                if response.status_code >= 400:
                    raise AIProviderError(f"Gemini API returned an error (HTTP {response.status_code}).")

                envelope = response.json()
                usage = envelope.get("usageMetadata", {})
                logger.info(
                    "Gemini call succeeded: model=%s, prompt_tokens=%s, candidate_tokens=%s, total_tokens=%s",
                    self.model,
                    usage.get("promptTokenCount"),
                    usage.get("candidatesTokenCount"),
                    usage.get("totalTokenCount"),
                )
                break

            except (GeminiAuthError, GeminiQuotaError):
                raise
            except httpx.TimeoutException as exc:
                logger.warning("Gemini timed out while generating response")
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
                data = json.loads(clean_text)
                if isinstance(data, dict):
                    if "reasoning_summary" in data and isinstance(data["reasoning_summary"], str) and len(data["reasoning_summary"]) > 1900:
                        data["reasoning_summary"] = data["reasoning_summary"][:1900]
                    return response_model.model_validate(data)
                return response_model.model_validate_json(clean_text)
            except (ValidationError, json.JSONDecodeError) as exc:
                logger.error("Gemini structured JSON validation failed")
                raise ProviderResponseError("Gemini returned invalid structured JSON. Try again.") from exc

    async def analyze_job(self, job: JobRequest, profile: CandidateProfile) -> JobAnalysis:
        payload = build_compact_analysis_payload(job, profile, self.skills_bank)
        analysis = await self._chat(
            JobAnalysis,
            JOB_ANALYSIS_SYSTEM_PROMPT,
            payload,
        )
        return AnalysisValidator(profile, self.skills_bank).validate(analysis, f"{job.role}\n{job.job_description}")

    async def tailor_resume(
        self,
        job: JobRequest,
        profile: CandidateProfile,
        analysis: JobAnalysis,
    ) -> TailoredResume:
        references = (
            self.reference_library.select(job.role, job.job_description)[:1]
            if self.reference_library
            else []
        )
        layout_guide = self.reference_library.layout_guide() if self.reference_library else {}
        catalog = FactCatalog(profile).for_prompt()
        job_text = f"{job.role}\n{job.job_description}".casefold()
        if self.skills_bank:
            relevant = [
                s for s in self.skills_bank.skills
                if self.skills_bank.eligible(s) and (
                    self.skills_bank.confirmed_profile_skill(s)
                    or self.skills_bank.mentioned(s, job_text)
                    or s.name in analysis.strong_matches
                    or s.id in analysis.strong_skill_ids
                )
            ]
            if not relevant:
                relevant = [s for s in self.skills_bank.skills if self.skills_bank.eligible(s)][:35]
            allowed_skills = list(dict.fromkeys(val for s in relevant for val in (s.name, self.skills_bank.wording(s))))
            allowed_skill_ids = [s.id for s in relevant]
        else:
            allowed_skills = [skill for values in profile.skills.values() for skill in values]
            allowed_skill_ids = []
        payload = build_compact_tailor_payload(job, profile, analysis, self.skills_bank, layout_guide, references)
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
            payload,
            source_catalog=catalog,
            allowed_skills=allowed_skills,
            allowed_skill_ids=allowed_skill_ids,
        )

    async def tailor(
        self,
        job: JobRequest,
        profile: CandidateProfile,
        on_stage: Callable[[str], None] | None = None,
    ) -> WorkflowResponse:
        if on_stage:
            on_stage("Analizowanie wymagań oferty (Gemini)...")
        analysis = await self.analyze_job(job, profile)
        if on_stage:
            on_stage("Generowanie dopasowanego CV (Gemini)...")
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
                if response.status_code == 404:
                    raise AIProviderError(f"Model Gemini '{self.model}' jest niedostępny (404). Zaktualizuj GEMINI_MODEL w konfiguracji.")
                response.raise_for_status()
        except GeminiAuthError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise AIProviderError("Cannot connect to Gemini API. Check configuration.") from exc

        return {"status": "ok", "provider": self.name, "model": self.model}
