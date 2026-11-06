# Daily AI budgets and batch admission

The application daily call budget is a local resource safeguard, including when
Ollama runs on the owner's hardware. It is not a billing limit imposed by Ollama.
One offer can consume several calls for analysis, bounded recovery and summary
review. Existing concurrency, per-offer deadlines and storage quotas still apply.

When enabled, the budget resets at **00:00 UTC**. Submission checks availability without charging
or reserving calls. Actual inference admission remains atomic in SQLite.

- New JSON and TXT batches return **429** with `Retry-After` if today's budget is
  already exhausted. No batch is queued and no offer is fetched.
- Identical idempotency-key lookups still return the existing task. Conflicting
  payloads still return 409. A new key is required for an intentional new run.
- If another task uses the last call after submission, the running batch stops
  when the authoritative budget check rejects a call. Completed results remain
  intact; later URLs are not fetched and no additional child tasks are created.
- Budget-affected items retain the existing `failed` status for compatibility,
  with `error_code=daily_ai_budget` and positive `retry_after_seconds`. Their
  messages distinguish the interrupted offer from offers not started. The child
  that reached the limit has error status 429, not a provider/network failure.
- Parent `completed` still means iteration ended, not that all CVs exported.

The budget is never silently raised or reset. These checks do not enable paid
fallback, weaken source/evidence validation, confirm summaries or rewrite old
CVs. The owner's manual review remains necessary where requested.

## Additional quality checks from the batch review

SQL/relational database work does not establish the separate unstructured-data
or knowledge-base scope. Jira use does not establish Microsoft Teams or Office
application proficiency; Microsoft 365 support is not Office application use.
Explicitly documented suite-member use can support the appropriate Office scope.
These source ceilings still preserve alternatives/examples and the distinction
between academic knowledge and practical/independent use. They are bounded
safeguards, not a guarantee for arbitrary technologies or model paraphrases.

Repeated validation no longer appends identical deterministic tenure/language
explanations to the same requirement. This changes report presentation only,
not candidate facts, tenure arithmetic or exact-text summary confirmation.

Revalidation also keeps parser-owned portal tags out of mandatory qualification
scoring, while retaining their independent role/proficiency assessment. An
explicit qualification sentence naming the same technology remains assessed.
A working-arrangement context note may coexist with a derived personal
clarification without creating a false source-classification conflict; the
arrangement still remains unconfirmed, never inferred from technical facts.

Explicit skill predicates such as "Strong Python skills" and "Good SQL skills"
must be assessed as qualifications even under an unfamiliar heading. They cannot
be hidden as duties while claiming reliable source coverage. Bare technology
tags still require semantic interpretation; headings alone do not force them
into mandatory scoring.

## Daily call limits and private-owner opt-out

The application enforces daily limits on AI calls to manage resource usage across all providers (including Gemini, which carries cost risks).

- **AI_DAILY_CALL_LIMIT**: Default is 300. Positive values range from 1 to 10,000. A value of 0 explicitly disables the owner's daily cap for private use. It does not make an exposed application private or change authentication. This is an application-level limit, not an Ollama limit.
    - The SQLite counter continues to track all calls performed.
    - If a positive limit is restored on the same day, the system takes into account the consumption already incurred.
    - This setting applies to all providers for the account.
    - This does not enable fallback, weaken Truth Lock, bypass rate limits, ignore timeouts, affect concurrency, or bypass storage quotas.
- **DEMO_AI_DAILY_CALL_LIMIT**: Default is 60. Valid values are 1 to 10,000 (0 is forbidden).

Changing these limits requires a process restart or redeployment. Do not reset the database. Before publication, it is recommended to set AI_DAILY_CALL_LIMIT to 300 (or another positive value) and ensure a finite demo limit is set.

For private, single-owner use after deploying a version supporting zero:

```dotenv
AI_DAILY_CALL_LIMIT=0
DEMO_AI_DAILY_CALL_LIMIT=60
```

Before public access, restore a positive owner limit (for example
`AI_DAILY_CALL_LIMIT=300`) and restart or redeploy. Do not use zero as a spending
control: an explicitly selected cloud provider can still incur charges. Existing
failed batches do not automatically resume after changing the setting; submit
only the failed URLs with a new idempotency key when ready.
