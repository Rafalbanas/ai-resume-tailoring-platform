import json

import httpx

from app.core.config import Settings
from app.models.candidate import CandidateProfile
from app.models.job import JobRequest
from app.models.resume import WorkflowResponse
from app.services.ai_provider import AIProvider


class N8NGeminiProvider(AIProvider):
    def __init__(self, settings: Settings):
        if not settings.n8n_webhook_url or not settings.n8n_webhook_secret:
            raise RuntimeError("N8N_WEBHOOK_URL and N8N_WEBHOOK_SECRET are required for the n8n provider")
        self.url = settings.n8n_webhook_url
        self.secret = settings.n8n_webhook_secret
        self.timeout = settings.request_timeout_seconds

    async def tailor(self, job: JobRequest, profile: CandidateProfile) -> WorkflowResponse:
        payload = {
            "job": job.model_dump(mode="json"),
            "master_profile": profile.model_dump(mode="json"),
            "schemas": {
                "analysis": WorkflowResponse.model_json_schema()["$defs"]["JobAnalysis"],
                "response": WorkflowResponse.model_json_schema(),
            },
        }
        headers = {"X-Webhook-Secret": self.secret, "Content-Type": "application/json"}
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
