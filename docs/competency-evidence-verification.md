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

A new actual trial with the explicitly enriched profile demonstrated a remaining *coverage* problem: all three calls ended with `stop`, but list-based recovery still omitted one source passage. It was rejected after 135.05 s, rather than silently accepting an incomplete report. The final local recovery now uses required passage IDs as object keys (`assessments`), preventing the grammar from substituting repeated list rows for missing IDs. The internal decoder expands these entries into the existing compact assessment model; public analysis/export contracts stay unchanged. Truncated final recovery remains an error, never a complete report. The two-recovery-call limit is unchanged.

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
