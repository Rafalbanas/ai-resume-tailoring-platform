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
from app.models.interpretation import JobInterpretation
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume, WorkflowResponse
from app.services.ai_provider import (
    JOB_ANALYSIS_SYSTEM_PROMPT,
    RESUME_TAILOR_SYSTEM_PROMPT,
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
from app.services.comparison_capture import record_call
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
        self.summary_review_key = settings.csrf_secret
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

        from app.services.bounded_http import bounded_post, model_call
        schema = response_model.model_json_schema()
        gemini_schema = to_gemini_schema(schema)

        generation_config: dict[str, Any] = {
            "temperature": 0.0,
            "maxOutputTokens": 8192,
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
        from app.services.token_progress import new_call, report
        for attempt in range(self.max_retries + 1):
            usage_id = new_call(self.name, self.model)
            usage_reported = False
            try:
                async with model_call(self), httpx.AsyncClient(
                    timeout=self.timeout,
                    follow_redirects=False,
                    transport=self.transport,
                ) as client:
                    response = await bounded_post(client, url, json=request_body, headers=headers)

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
                        f"Model Gemini '{self.model}' is unavailable or retired for this API account. Update GEMINI_MODEL in the configuration."
                    )

                if response.status_code >= 400:
                    raise AIProviderError(f"Gemini API returned an error (HTTP {response.status_code}).")

                envelope = response.json()
                usage = envelope.get("usageMetadata", {})
                report(usage_id, phase="done", input_tokens=usage.get("promptTokenCount"),
                       output_tokens=usage.get("candidatesTokenCount"), total_tokens=usage.get("totalTokenCount"))
                usage_reported = True
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
            finally:
                if not usage_reported:
                    report(usage_id, phase="done", total_tokens=None)
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

        record_call(self.name, payload, f"{TRUTH_RULES}\n\n{system_prompt}", gemini_schema, raw_text, usage)

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
        interpretation = await self._chat(
            JobInterpretation,
            JOB_ANALYSIS_SYSTEM_PROMPT,
            payload,
        )
        analysis = interpretation.to_analysis(job)
        validated = AnalysisValidator(profile, self.skills_bank).validate(analysis, f"{job.role}\n{job.job_description}", semantic=True)
        import hashlib
        validated.company, validated.role = job.company, job.role
        validated.job_source = {'url': str(job.job_url or ''), 'sha256': hashlib.sha256(job.job_description.encode()).hexdigest()}
        validated._model_output = analysis.model_dump(mode="json")
        return validated

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
        resume = await self._chat(
            TailoredResume,
            RESUME_TAILOR_SYSTEM_PROMPT,
            payload,
            source_catalog=payload["source_catalog"],
            allowed_skills=allowed_skills,
            allowed_skill_ids=allowed_skill_ids,
        )

        from app.services.summary_review import review_summary
        resume = await review_summary(self, resume, profile)
        # Keep the selected source text with the server-side trace so later
        # profile edits cannot erase generation provenance. Do not send another
        # copy of these facts to the model in retrieval diagnostics.
        resume._retrieval_trace = {**payload["retrieval"], "source_snapshot": payload["source_catalog"]}
        return resume

    async def tailor(
        self,
        job: JobRequest,
        profile: CandidateProfile,
        on_stage: Callable[[str], None] | None = None,
    ) -> WorkflowResponse:
        if on_stage:
            on_stage("Analyzing job requirements (Gemini)...")
        analysis = await self.analyze_job(job, profile)
        if on_stage:
            on_stage("Generating tailored CV (Gemini)...")
        resume = await self.tailor_resume(job, profile, analysis)
        return WorkflowResponse(analysis=analysis, resume=resume, provider_used=self.name, model_used=self.model)

    async def health(self) -> dict[str, str]:
        from app.services.bounded_http import bounded_get
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
                response = await bounded_get(client, url, headers=headers)
                if response.status_code in (401, 403):
                    raise GeminiAuthError("Gemini API key is invalid.")
                if response.status_code == 404:
                    raise AIProviderError(f"Model Gemini '{self.model}' is unavailable (404). Update GEMINI_MODEL in the configuration.")
                response.raise_for_status()
        except GeminiAuthError:
            raise
        except (httpx.HTTPError, ValueError) as exc:
            raise AIProviderError("Cannot connect to Gemini API. Check configuration.") from exc

        return {"status": "ok", "provider": self.name, "model": self.model}
