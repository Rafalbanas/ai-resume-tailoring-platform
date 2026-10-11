import json

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.models.candidate import CandidateProfile
from app.models.job import JobRequest
from app.models.resume import WorkflowResponse
from app.services.ai_provider import AIProvider, ProviderResponseError, ProviderUnavailableError
from app.services.fact_catalog import FactCatalog
from app.services.skills_bank import SkillsBank


class N8NGeminiProvider(AIProvider):
    name = "n8n"

    def __init__(self, settings: Settings, skills_bank: SkillsBank | None = None):
        if not settings.n8n_webhook_url or not settings.n8n_webhook_secret:
            raise RuntimeError("N8N_WEBHOOK_URL and N8N_WEBHOOK_SECRET are required for the n8n provider")
        self.url = settings.n8n_webhook_url
        self.secret = settings.n8n_webhook_secret
        self.timeout = settings.request_timeout_seconds
        self.skills_bank = skills_bank

    async def tailor(self, job: JobRequest, profile: CandidateProfile) -> WorkflowResponse:
        payload = {
            "job": job.model_dump(mode="json"),
            "master_profile": profile.model_dump(mode="json"),
            "source_catalog": FactCatalog(profile).for_prompt(),
            "skills_bank": self.skills_bank.for_prompt() if self.skills_bank else [],
            "schemas": {
                "analysis": WorkflowResponse.model_json_schema()["$defs"]["JobAnalysis"],
                "response": WorkflowResponse.model_json_schema(),
            },
        }
        headers = {"X-Webhook-Secret": self.secret, "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                response = await client.post(self.url, json=payload, headers=headers)
                response.raise_for_status()
            data = response.json()
            if isinstance(data, list) and len(data) == 1:
                data = data[0]
            if isinstance(data, dict) and "output" in data:
                data = data["output"]
            if isinstance(data, str):
                data = json.loads(data.strip().removeprefix("```json").removesuffix("```").strip())
            return WorkflowResponse.model_validate(data)
        except httpx.HTTPError as exc:
            raise ProviderUnavailableError("The n8n provider request failed. Check availability and configuration.") from exc
        except (ValueError, ValidationError) as exc:
            raise ProviderResponseError("The n8n provider returned invalid structured data.") from exc
