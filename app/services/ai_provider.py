from abc import ABC, abstractmethod

from app.models.candidate import CandidateProfile
from app.models.job import JobRequest
from app.models.resume import WorkflowResponse


class AIProviderError(RuntimeError):
    """An AI provider failure that is safe to show to the user."""


class AIProvider(ABC):
    name = "unknown"

    @abstractmethod
    async def tailor(self, job: JobRequest, profile: CandidateProfile) -> WorkflowResponse:
        """Analyze a job and return a source-referenced resume draft."""

    async def health(self) -> dict[str, str]:
        """Return provider readiness without processing private candidate data."""
        return {"status": "ok", "provider": self.name}
