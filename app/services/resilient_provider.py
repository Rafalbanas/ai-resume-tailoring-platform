import asyncio
import json
import logging
import os
import tempfile
import time
from typing import Any, Callable

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
        self.fallback_enabled = True
        self.settings_path = None
        self.providers = providers
        self.default_primary = default_primary
        self.default_fallback = default_fallback if default_fallback != "none" else None
        self.operation_budget_seconds = operation_budget_seconds
        self.name = "resilient"
        self.model = f"primary:{default_primary}"

    def load_settings(self):
        if self.settings_path and self.settings_path.exists():
            value = json.loads(self.settings_path.read_text())["automatic_fallback"]
            if not isinstance(value, bool):
                raise ValueError("Invalid automatic fallback setting")
            self.fallback_enabled = value

    def save_settings(self, enabled):
        fd, path = tempfile.mkstemp(dir=self.settings_path.parent, prefix=".ai-settings-")
        try:
            with os.fdopen(fd, "w") as handle:
                json.dump({"automatic_fallback": enabled}, handle)
            os.replace(path, self.settings_path)
            self.fallback_enabled = enabled
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def resolve_chain(self, requested: str | None = None) -> tuple[str, str | None]:
        req = (requested or "auto").strip().lower()
        if req == "auto" and self.default_primary in {"mock", "n8n"}:
            return self.default_primary, None
        primary = "gemini" if req == "gemini" else "ollama" if req in {"auto", "ollama"} else req
        fallback = ("ollama" if primary == "gemini" else "gemini") if primary in {"ollama", "gemini"} else None
        return primary, fallback if self.fallback_enabled and fallback in self.providers else None

    async def tailor(
        self,
        job: JobRequest,
        profile: CandidateProfile,
        requested_provider: str = "auto",
        on_stage: Callable[[str], None] | None = None,
    ) -> WorkflowResponse:
        primary_name, fallback_name = self.resolve_chain(requested_provider)
        primary = self.providers.get(primary_name)
        if not primary:
            raise AIProviderError(f"Requested AI provider '{primary_name}' is not configured.")

        start_time = time.monotonic()

        def remaining_budget() -> float:
            elapsed = time.monotonic() - start_time
            return max(0.0, self.operation_budget_seconds - elapsed)

        async def _call(target: AIProvider, reason: str | None = None) -> WorkflowResponse:
            try:
                return await target.tailor(job, profile, on_stage=on_stage)
            except TypeError:
                return await target.tailor(job, profile)

        # If primary is Gemini and has no key configured
        if primary_name == "gemini" and getattr(primary, "api_key", None) == "":
            if not fallback_name:
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
                if on_stage:
                    on_stage(f"Switching to provider '{fallback_name}'...")
                response = await asyncio.wait_for(_call(fallback), timeout=rem)
                response.provider_used = fallback.name
                response.model_used = getattr(fallback, "model", fallback.name)
                response.fallback_used = True
                response.fallback_reason = "Gemini API key not configured; used fallback provider."
                return response
            raise GeminiAuthError("Gemini API key is not configured. Set GEMINI_API_KEY in your environment.")

        # Attempt primary provider within remaining budget
        rem = remaining_budget()
        if rem <= 0.0:
            raise AIProviderError(f"Operation budget ({self.operation_budget_seconds}s) exceeded before starting operation.")

        try:
            response = await asyncio.wait_for(_call(primary), timeout=rem)
            response.provider_used = primary.name
            response.model_used = getattr(primary, "model", primary.name)
            response.fallback_used = False
            return response
        except GeminiAuthError as auth_err:
            # If user explicitly chose gemini, fail immediately
            if not fallback_name or fallback_name not in self.providers:
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
            if on_stage:
                on_stage(f"Switching to fallback provider ({fallback_name})...")
            try:
                response = await asyncio.wait_for(_call(fallback), timeout=rem_fb)
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

            if on_stage:
                on_stage(f"Switching after timeout to ({fallback_name})...")
            try:
                response = await asyncio.wait_for(_call(fallback), timeout=rem_fb)
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

            if on_stage:
                on_stage(f"Switching to fallback provider ({fallback_name})...")
            try:
                response = await asyncio.wait_for(_call(fallback), timeout=rem_fb)
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
        selected_primary, selected_fallback = self.resolve_chain("auto")
        active = [selected_primary, selected_fallback]
        ready = any(results.get(name, {}).get("status") == "ok" for name in active if name in results)
        primary_ready = results.get(self.default_primary, {}).get("status") == "ok"
        return {
            "status": "ok" if primary_ready else "degraded" if ready else "unavailable",
            "provider": self.name,
            "default_primary": self.default_primary,
            "default_fallback": selected_fallback,
            "automatic_fallback": self.fallback_enabled,
            "operation_budget_seconds": self.operation_budget_seconds,
            "providers": results,
        }
