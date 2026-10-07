# n8n setup

1. In the existing n8n instance, import `n8n/cv-tailoring-workflow.json` from file.
2. Open both **Gemini Model** nodes and select the existing **Google Gemini(PaLM) API** credential. Credentials are intentionally not embedded in the export.
3. If `models/gemini-2.5-flash` is unavailable in your installed n8n version or account, choose the current Flash model from the node dropdown.
4. Set `N8N_WEBHOOK_SECRET` in the n8n container/environment to the same long random value used by FastAPI, then restart n8n. n8n blocks `$env` access in some hardened configurations; in that case, create an n8n Header Auth credential or replace the comparison value in **Validate Webhook Secret** with an n8n-managed secret.
5. Activate the workflow and copy its production webhook URL into the FastAPI `.env` as `N8N_WEBHOOK_URL`.
6. Execute once with a small real job description. Confirm that both chain nodes return structured objects and the final response contains top-level `analysis` and `resume` keys.

The workflow does not start another n8n instance and contains no API key.
