from abc import ABC, abstractmethod

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


class AIProvider(ABC):
    name: str = "unknown"
    model: str = "unknown"

    @abstractmethod
    async def tailor(self, job: JobRequest, profile: CandidateProfile) -> WorkflowResponse:
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
