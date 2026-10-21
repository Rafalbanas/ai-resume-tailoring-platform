# Competency evidence and Ollama verification

## Causes and implementation

The existing semantic validator primarily checked that model-cited IDs existed. A missing model citation was not consistently reconciled with the deterministic matcher, so the same source could confirm a standalone capability and disappear from a compound condition. Broad, compound labels also bypassed directional matching. Entire negative-containing facts were excluded even when a separate statement described valid theoretical knowledge. Export eligibility (`allowed_in_cv`) incorrectly controlled whether explicitly verified manual evidence was visible to assessment.

`competency_scope.py` extends the existing EvidenceMatcher with scoped knowledge/practice checks for networking, security, backup, disaster recovery, Agile/Scrum, version control and infrastructure configuration management. Both source-review and model-validation paths use the same rules. Established compound scopes have visible components, retain their source modifiers and quote, and keep one parent scoring weight. Arbitrary occurrences of “and” are not automatically split. Existing model interpretation handles other semantic conditions and AND/OR cases.

`semantic_requirements.py` reconciles these scopes with saved facts even when the model initially reports missing evidence. Theory/training cannot confirm practical proficiency. Denials of practice do not deny theoretical knowledge; contradictory evidence remains partial and requires clarification. Employment facts can establish professional context, while project facts do not become employment automatically. Familiarity/awareness/basic knowledge/understanding use documented knowledge; practical knowledge/hands-on use require documented activity, and advanced/proficiency claims need evidence of that level. Required tenure still uses existing dated evidence checks.

A verified manual description naming `.github/workflows/ci.yml test and lint` exposed an additional bug: the word “Verified” near “workflow” was interpreted as successful execution. Execution now requires an actual run/pass/success assertion. A successful repository CI run was independently checked: [main CI run](https://github.com/Rafalbanas/ai-resume-tailoring-platform/actions/runs/38292820063). This external check does not silently rewrite a saved profile attestation.

Role-context counts are explicitly labeled as excluded from qualification scoring. The UI no longer simultaneously labels a role capability confirmed and states its listed level is necessarily unverified. Reasons and evidence explain the actual scope.

## Evidence gap answers

The analysis view proposes at most five deterministic, deduplicated questions from missing/partial requirements or their components, skipping confirmed gaps and duplicate scoring rows. Questions have stable IDs tied to the saved report. An authenticated, CSRF-protected POST verifies the question against that report and requires explicit consent, an answer, knowledge/practice scope, education/project/employment/personal context, and a concrete description.

Only an actual confirmed answer is saved through the existing enrichment transaction, with rollback backup and in-memory profile/catalog refresh. No model calls are needed to ask or save questions. Employer tenure, proficiency modifiers and CEFR labels are removed from the question subject before constructing a candidate assertion; the candidate's actual details must supply any such evidence. Answers are not automatically approved for CV export. Old reports preserve their original assessment; future analyses use saved facts.

The user explicitly confirmed three scoped additions during this task. They were saved privately with a rollback backup: backup practice, basic DR understanding with an explicit practice limitation, and Agile education with an explicit Scrum-practice limitation. No private profile, passwords, or raw model responses are included in this document or repository.

## Runtime and token diagnosis

The running container initially reported build `a84af3901ac56e9382142feab2a6a4e3dc60cb56`, and `/app/app/services/ollama_analysis.py` was absent. The compact-analysis PR was already merged on main (`af5c5af`), but its image had not been deployed. A repository merge alone had therefore not fixed the running instance.

Observed local model: `qwen3.5:9b`, Qwen35 9.0B Q4_K_M, completion/vision/tools/thinking capabilities, model context metadata 262144. Application allocation remains `num_ctx=32768`, `num_predict=8192`, temperature 0, one concurrent Ollama request, `stream=false`, `think=false`. Loaded VRAM allocation was 6,558,444,420 bytes. No model, GPU, memory allocation, default provider or global budget change was made.

The original verbose contract repeated evidence, source quotes and reasoning. Two failing Ollama calls consumed 57,877 tokens and 674.660 s of provider time; the entire old workflow including Gemini fallback took 699.408 s. The previous compact-reference implementation is retained: source/evidence IDs, bounded output, adaptive batches, successful-row retention, two local recovery calls maximum, typed failure reasons and privacy-safe call telemetry.

A new actual trial with the explicitly enriched profile demonstrated a remaining *coverage* problem: all three calls ended with `stop`, but list-based recovery still omitted one source passage. It was rejected after 135.05 s, rather than silently accepting missing source dispositions. A subsequent keyed trial exposed an invalid empty capability label for a heading; it too was rejected. Context dispositions were restricted and category grammar definitions shared to bound schema size. Captured responses then established that all candidate qualifications were assessed initially; the missing passages were source headings, organization text and portal tags. Those exact parser-backed metadata categories are now retained as source context without another model call. Portal tags continue through the existing independent role matcher. Unknown candidate passages cannot be completed this way. For actual missing assessments, final local recovery uses required passage IDs as object keys (`assessments`), preventing the grammar from substituting repeated list rows for missing IDs. The internal decoder expands these entries into the existing compact assessment model; public analysis/export contracts stay unchanged. Truncated final recovery remains an error, never a complete report. The two-recovery-call limit is unchanged.

## Measured thinking comparison

A small synthetic three-competence diagnostic used the same schema, facts and 1024-token output allowance. Without thinking: complete JSON, 3/3 expected scoped classifications, 161 input / 68 output tokens, 1.99 s. With thinking: 159 input / 1024 output tokens, `done_reason=length`, no complete JSON, 19.25 s. This is a bounded diagnostic, not a general accuracy benchmark or a full-offer experiment. The pre-existing production setting `think=false` was retained. The API does not provide a separately measured reasoning-token count; it is reported as unavailable rather than zero.

## Source coverage and evaluation

A real analysis before the approved additions used the same job hash and existing profile: complete JSON, all 22 old source qualifications covered plus six previously omitted source conditions (28 unique scoring rows), 3 Ollama calls / 31,979 tokens / 173.73 s, zero Gemini calls. This run's native result was LOW / REASONABLE_STRETCH. The earlier original 22-row report was MEDIUM / REVIEW; preserving evidence and source conditions is the goal, not forcing the score upward.

A local revalidation after the approved additions, using the same generated source interpretation and no further inference, shows:

| Source scope | Evidence assessment |
|---|---|
| Networking and security | Networking confirmed at understanding level; security best practices partial; combined partial |
| Backup and disaster recovery | Backup practice confirmed; basic DR purpose known but strategies only partial; combined partial |
| Agile/Scrum and CI/CD | Agile theory confirmed; Scrum-team practice explicitly absent; CI/CD implementation partial; existing AND policy retains the practice gap |
| Configuration management and version control | Git/version control confirmed at familiarity level; infrastructure configuration management missing; combined partial |
| CI/CD tooling | Implementation artifact partial; file verification is not execution verification |

No requirement is counted again because it has more components. These are scope assessments, not claims of proficiency beyond the profile or an employer's hiring decision. The explicit Scrum practice denial can produce a confirmed AND gap while theoretical Agile knowledge remains visible.

## Final accepted end-to-end run

The final code was run against the same Motorola job (SHA-256 `8016f0fbc6ab5ce2ebe873ae8e2743294f7ddd587a0110db8a839418efce32cd`) and the profile containing only the explicitly approved additions. **One Ollama call, zero local retries, zero Gemini calls, complete JSON and no fallback.** Actual counts: **9,444 input + 3,018 output = 12,462 tokens**, `done_reason=stop`; **64.738 s provider time / 69.47 s analysis wall time**. Compare with the old two failed Ollama calls: **57,877 tokens / 674.660 s provider time**. The old whole workflow including Gemini took 699.408 s; these different timing boundaries are not conflated.

Source audit: **22/22 original qualification quotes retained**, plus the additional hands-on condition, **23 unique qualification rows (9 mandatory / 14 preferred)** and eight separate role-context competencies. Five soft skills are represented as role context in this accepted model interpretation, rather than added as mandatory scoring conditions. All 43 supplied passages are retained: the model covered 32 and the source parser resolved 11 metadata passages. No scoring duplicates. Final whole-requirement counts: **0 confirmed / 16 partial / 6 not confirmed / 1 confirmed gap**; **LOW / REASONABLE_STRETCH**. Atomic confirmations remain visible inside partial/AND-gap parents. No HIGH/MEDIUM floor or score inflation was introduced.

There were five full analysis trials during this task (13 Ollama calls total) and two small thinking-comparison calls. The list-coverage and invalid-heading-disposition trials were explicitly rejected. The final accepted run alone is used for the final before/after measurements; earlier trials and the different profile boundaries are disclosed above. No Gemini inference was used. Raw private requests, results and audits remain outside the repository in a protected local directory.

## Automated checks and deployment

Final full suite: **466 passed, 2 skipped**, 50 deprecation warnings, in 158.64 s. The relevant scope/provider tests also passed (**68 tests**). Ruff and `git diff --check` passed. Tests include compound networking/security, backup/DR knowledge versus practice, Agile training/Scrum practice, Git versus infrastructure configuration management, conflicting/absent evidence, saved-answer consent/CSRF/forged-question rejection, employer-level/tenure removal, source coverage, AND/OR/deduplication, output truncation, schema rejection, batching and required-key recovery. Existing PDF/DOCX and other application regression tests remain in the passing full suite.

The running container was updated to the tested branch code at **`217e47aaa941ee4007f9935f516977bb578d4bef`** using image `cvtailor:competency-final`. An old-image rollback tag was retained; no active application tasks were interrupted. The current port, original private data mount, environment/provider settings, authentication and Cloudflare routing were preserved. No automatic main merge was performed.

Verification: all **12 changed application/template files** inside the container exactly match branch SHA-256 hashes; compact analysis and evidence-question modules are present; `/health` returns OK; both `https://cv.banas.dev/login` and `https://cv.banas.dev/demo/login` return HTTP 200. Runtime reports Ollama / qwen3.5:9b / 8192 output / 32768 context. The private profile additions were consented to separately and retain a rollback backup.

Limitations: the final native analysis confirms this offer/profile, not universal model success. Gemini remains an enabled recovery option for genuine unavailable/timeout/schema/coverage failures; it was not invoked in the accepted trial. Unknown semantic scopes still use the existing model interpretation and source/evidence checks rather than an invented exhaustive skill ontology. The enriched and original profiles are explicitly distinguished in measurements. Protected raw diagnostic artifacts are not committed.
