from abc import ABC, abstractmethod

from app.models.candidate import CandidateProfile
from app.models.job import JobRequest
from app.models.resume import WorkflowResponse


class AIProvider(ABC):
    @abstractmethod
    async def tailor(self, job: JobRequest, profile: CandidateProfile) -> WorkflowResponse:
        """Analyze a job and return a source-referenced resume draft."""
