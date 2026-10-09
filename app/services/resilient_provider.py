import asyncio
import logging
import time
from typing import Any

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

logger = logging.getLogger(__name__)


class ResilientAIProvider(AIProvider):
    """Router that handles primary selection, operation budget, and bidirectional fallback (Ollama <-> Gemini)."""

    def __init__(
        self,
        providers: dict[str, AIProvider],
        default_primary: str = "ollama",
        default_fallback: str | None = "gemini",
        operation_budget_seconds: float = 300.0,
    ):
        self.providers = providers
        self.default_primary = default_primary
        self.default_fallback = default_fallback if default_fallback != "none" else None
        self.operation_budget_seconds = operation_budget_seconds
        self.name = "resilient"
        self.model = f"primary:{default_primary}"

    def resolve_chain(self, requested: str | None = None) -> tuple[str, str | None]:
        req = (requested or "auto").strip().lower()
        if req == "auto":
            primary = self.default_primary
            fallback = self.default_fallback if self.default_fallback != primary else None
        elif req == "ollama":
            primary = "ollama"
            fallback = "gemini" if "gemini" in self.providers else None
        elif req == "gemini":
            primary = "gemini"
            fallback = "ollama" if "ollama" in self.providers else None
        elif req in self.providers:
            primary = req
            fallback = None
        else:
            primary = self.default_primary
            fallback = self.default_fallback

        if fallback == primary:
            fallback = None
        return primary, fallback

    async def tailor(
        self,
        job: JobRequest,
        profile: CandidateProfile,
        requested_provider: str = "auto",
    ) -> WorkflowResponse:
        primary_name, fallback_name = self.resolve_chain(requested_provider)
        primary = self.providers.get(primary_name)
        if not primary:
            raise AIProviderError(f"Requested AI provider '{primary_name}' is not configured.")

        start_time = time.monotonic()

        def remaining_budget() -> float:
            elapsed = time.monotonic() - start_time
            return max(0.0, self.operation_budget_seconds - elapsed)

        # If primary is Gemini and has no key configured
        if primary_name == "gemini" and getattr(primary, "api_key", None) == "":
            if requested_provider.strip().lower() == "gemini":
                raise GeminiAuthError("Gemini API key is not configured. Set GEMINI_API_KEY in your environment.")
            # In auto mode, skip directly to fallback if available
            if fallback_name and fallback_name in self.providers:
                logger.info("Gemini is unconfigured in auto mode; routing directly to fallback '%s'", fallback_name)
                fallback = self.providers[fallback_name]
                rem = remaining_budget()
                if rem <= 5.0:
                    raise AIProviderError(
                        f"Operation budget ({self.operation_budget_seconds}s) exceeded before running fallback."
                    )
                response = await asyncio.wait_for(fallback.tailor(job, profile), timeout=rem)
                response.fallback_used = True
                response.fallback_reason = "Gemini API key not configured; used fallback provider."
                return response
            raise GeminiAuthError("Gemini API key is not configured. Set GEMINI_API_KEY in your environment.")

        # Attempt primary provider within remaining budget
        rem = remaining_budget()
        if rem <= 0.0:
            raise AIProviderError(f"Operation budget ({self.operation_budget_seconds}s) exceeded before starting operation.")

        try:
            response = await asyncio.wait_for(primary.tailor(job, profile), timeout=rem)
            response.provider_used = primary.name
            response.model_used = getattr(primary, "model", primary.name)
            response.fallback_used = False
            return response
        except GeminiAuthError as auth_err:
            # If user explicitly chose gemini, fail immediately
            if requested_provider.strip().lower() == "gemini" or not fallback_name or fallback_name not in self.providers:
                raise
            rem_fb = remaining_budget()
            if rem_fb <= 5.0:
                raise AIProviderError(
                    f"Primary ({primary_name}) failed auth ({auth_err}), and insufficient budget ({rem_fb:.1f}s) remains for fallback."
                ) from auth_err
            logger.warning(
                "Primary provider '%s' failed auth (%s). Attempting fallback to '%s' (budget left: %.1fs)",
                primary_name,
                auth_err,
                fallback_name,
                rem_fb,
            )
            fallback = self.providers[fallback_name]
            try:
                response = await asyncio.wait_for(fallback.tailor(job, profile), timeout=rem_fb)
                response.provider_used = fallback.name
                response.model_used = getattr(fallback, "model", fallback.name)
                response.fallback_used = True
                response.fallback_reason = f"Primary provider '{primary_name}' authentication failed: {auth_err}"
                return response
            except Exception as fb_err:
                raise AIProviderError(
                    f"Primary ({primary_name}) failed: {auth_err}; Fallback ({fallback_name}) also failed: {fb_err}"
                ) from fb_err

        except (TimeoutError, asyncio.TimeoutError) as timeout_err:
            elapsed = time.monotonic() - start_time
            primary_err = ProviderUnavailableError(
                f"Primary provider '{primary_name}' timed out after {elapsed:.1f}s (budget limit)."
            )
            if not fallback_name or fallback_name not in self.providers:
                raise primary_err from timeout_err

            rem_fb = remaining_budget()
            logger.warning(
                "Primary provider '%s' timed out after %.1fs. Remaining budget: %.1fs. Attempting fallback to '%s'",
                primary_name,
                elapsed,
                rem_fb,
                fallback_name,
            )
            if rem_fb <= 5.0:
                raise AIProviderError(
                    f"Primary provider '{primary_name}' timed out ({primary_err}), and remaining budget ({rem_fb:.1f}s) is insufficient for fallback."
                ) from timeout_err

            fallback = self.providers[fallback_name]
            if fallback_name == "gemini" and getattr(fallback, "api_key", None) == "":
                raise AIProviderError(
                    f"Primary provider '{primary_name}' timed out ({primary_err}), and fallback Gemini is not configured with GEMINI_API_KEY."
                ) from timeout_err

            try:
                response = await asyncio.wait_for(fallback.tailor(job, profile), timeout=rem_fb)
                response.provider_used = fallback.name
                response.model_used = getattr(fallback, "model", fallback.name)
                response.fallback_used = True
                response.fallback_reason = f"Primary '{primary_name}' timed out. Automatically recovered using '{fallback_name}'."
                return response
            except Exception as fallback_err:
                logger.error(
                    "Both providers failed! Primary '%s': %s. Fallback '%s': %s",
                    primary_name,
                    primary_err,
                    fallback_name,
                    fallback_err,
                )
                raise AIProviderError(
                    f"Both AI providers failed. {primary_name}: {primary_err}; {fallback_name}: {fallback_err}"
                ) from fallback_err

        except (ProviderUnavailableError, GeminiQuotaError, ProviderResponseError, AIProviderError) as primary_err:
            if not fallback_name or fallback_name not in self.providers:
                raise

            rem_fb = remaining_budget()
            logger.warning(
                "Primary provider '%s' failed (%s). Remaining budget: %.1fs. Attempting fallback to '%s'",
                primary_name,
                primary_err,
                rem_fb,
                fallback_name,
            )
            if rem_fb <= 5.0:
                raise AIProviderError(
                    f"Primary provider '{primary_name}' failed ({primary_err}), and remaining budget ({rem_fb:.1f}s) is insufficient for fallback."
                ) from primary_err

            fallback = self.providers[fallback_name]
            if fallback_name == "gemini" and getattr(fallback, "api_key", None) == "":
                raise AIProviderError(
                    f"Primary provider '{primary_name}' failed ({primary_err}), and fallback Gemini is not configured with GEMINI_API_KEY."
                ) from primary_err

            try:
                response = await asyncio.wait_for(fallback.tailor(job, profile), timeout=rem_fb)
                response.provider_used = fallback.name
                response.model_used = getattr(fallback, "model", fallback.name)
                response.fallback_used = True
                response.fallback_reason = f"Primary '{primary_name}' failed ({primary_err}). Automatically recovered using '{fallback_name}'."
                return response
            except Exception as fallback_err:
                logger.error(
                    "Both providers failed! Primary '%s': %s. Fallback '%s': %s",
                    primary_name,
                    primary_err,
                    fallback_name,
                    fallback_err,
                )
                raise AIProviderError(
                    f"Both AI providers failed. {primary_name}: {primary_err}; {fallback_name}: {fallback_err}"
                ) from fallback_err

    async def analyze_job(
        self,
        job: JobRequest,
        profile: CandidateProfile,
        requested_provider: str = "auto",
    ) -> JobAnalysis:
        response = await self.tailor(job, profile, requested_provider=requested_provider)
        return response.analysis

    async def tailor_resume(
        self,
        job: JobRequest,
        profile: CandidateProfile,
        analysis: JobAnalysis,
        requested_provider: str = "auto",
    ) -> TailoredResume:
        response = await self.tailor(job, profile, requested_provider=requested_provider)
        return response.resume

    async def health(self) -> dict[str, Any]:
        results = {}
        for name, provider in self.providers.items():
            try:
                results[name] = await provider.health()
            except Exception as exc:
                results[name] = {"status": "error", "error": str(exc), "provider": name}
        return {
            "status": "ok",
            "provider": self.name,
            "default_primary": self.default_primary,
            "default_fallback": self.default_fallback,
            "operation_budget_seconds": self.operation_budget_seconds,
            "providers": results,
        }
