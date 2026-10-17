# Security follow-up: deployment evidence and AI export review

## Production inspection

Read-only inspection on 2026-10-17 found the live web process at revision `20f95b0faacfdf6db6b101dc2d28a76cb5c4bc70`, UID 10001. There were no owner/demo processing Deployments or NetworkPolicies in `cvtailor-prod`; the processing URLs and `PROCESSING_REQUIRED` were unset. The running web pod mounts both account directories and uses host networking. The protections merged in #37/#38 therefore must not be described as deployed production isolation.

Reproduce configuration inspection without reading Secrets, credentials, candidate files or logs:

```bash
python3 scripts/audit_processing_deployment.py
```

The command only performs Kubernetes GET operations. It outputs selected safety checks and image references, never environment values. Missing isolation gives a nonzero exit status. After migration it checks both ready Deployments, independent token references, restricted environments, scratch-only volumes, non-root/read-only settings, limits and named policy presence. This is configuration evidence; policy presence alone does not prove CNI enforcement, and this command does not run kernel/egress probes.

Production remains unchanged by this follow-up. Use the reviewed one-time migration and rollout/rollback procedure in [processing-security.md](processing-security.md). After migration, inspect the live configuration again, verify startup kernel-policy handshakes and perform synthetic owner/demo uploads/exports. Explicit egress probes from the worker network namespaces are still needed to establish CNI behavior; do not infer it from IaC alone.

## Controlled AI attack tests

`tests/test_summary_confirmation.py` exercises both real Gemini and Ollama transport adapters with controlled model responses. A malicious job asks for invented commercial use, years of experience, production use or reversal of a profile's explicit lack of commercial Kubernetes experience. The generator returns the invented summary; the judge falsely approves it with an existing fact ID. The actual review code signs this result and the existing FactValidator retains it.

This demonstrates an application consequence **conditional on a false model verdict**, not a jailbreak of a live model. No paid API, real candidate data or production account was used. The test deliberately controls both model replies so the export boundary remains testable regardless of model compliance.

The authenticated HTTP flow must now refuse first generation without explicit user confirmation of the displayed summary and source facts. Missing checkbox, missing token and forged token fail before rendering or application-file creation. Natural summaries remain available after confirmation. A further case creates and reads real PDF/DOCX exports after confirmation.

## Separate decisions

- Deterministic source composition: FactValidator signs its result with a dedicated `source-v1` purpose. This is distinct from model semantic approval and cannot be obtained by prefixing a model signature. It avoids extra confirmation for source-composed fallback summaries.
- AI semantic review: an existing model-review signature proves which text/profile was reviewed, not that the verdict was correct. A non-source summary requires user confirmation even when this signature is valid.
- User confirmation: a separate HMAC binds the exact summary, citations, professional profile snapshot and draft/document context to the account key. A source, text, professional-profile or document/account change invalidates it. Presentation changes do not.

Saved documents without a current receipt require confirmation before PDF/DOCX download when their summaries are not source-composed. The preview shows the text and citations. Browser download navigation returns to that review; API download requests receive 409. No existing CV is rewritten or deleted. Confirmation does not modify the profile or make a deliberately false claim true; it records the account user's decision. Source facts and model status are shown separately. Form CSRF and account isolation continue to apply.

The actual export functions remain usable by trusted local CLI code; the user-confirmation boundary applies to the authenticated web application.

## Environment consistency

`.python-version`, Docker, CI and Ruff target Python 3.14. Before relying on local results, run:

```bash
python scripts/check_environment.py --dev
python -m pip check
```

The checker compares the interpreter with Docker and all installed direct dependencies with exact requirements pins, including missing packages. Both CI and the built image check their environments. A Python 3.12 host is explicitly reported as mismatched; use Python 3.14 or the Docker image rather than weakening parser protections to support stale packages. Local Python 3.12 regression results are supplementary; Python 3.14 CI is the runtime-matching validation.

## Scope limits

This is not proof that all prompt injection, parser exploits or network-policy bypasses are impossible. Model accuracy still needs ongoing evaluation; live-model attack experiments are separate from the controlled transport regressions. Password paste, concurrent sessions, eight-hour session TTL, account-wide logout and the shared login URL are preserved. Encryption at rest remains deferred.
