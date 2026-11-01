# Exploratory Gemma benchmark — not an optimization approval

Run `57dc3c206b4745c191da78da48e613fc` used the staging REST API, live URL
import, frozen candidate data, `gemma4:12b-it-q4_K_M`, context 65536,
one permitted repair per variant and a 90-second per-variant wall budget.
The worker finished the experiment in 311.9 seconds. Eight calls were attempted;
one was cancelled without complete provider usage. Private profiles, evidence,
model responses and the full report are deliberately not published here.

| Offer / variant | Result | Input tokens | Output tokens | Calls | Wall time |
|---|---|---:|---:|---:|---:|
| BEST / full | Timeout; incomplete usage | unknown | unknown | 3 | 97.4 s |
| BEST / cleaned | Review: 2 original qualifications missing | 19,036 | 2,346 | 2 | 76.6 s |
| CLOUDATUS | Live extraction failed; no AI calls | — | — | 0 | — |
| CGI / full | Review: 17 original qualifications missing | 10,890 | 241 | 1 | 30.7 s |
| CGI / cleaned | Passed coverage checks | 20,876 | 1,831 | 2 | 90.1 s |

Counts include completed repair/batch calls. Deadlines initiate cancellation;
observed wall time includes cleanup and is not a precise real-time ceiling.
The completed portions of BEST/full reported 19,975 input tokens, but a third
call had unknown usage. Comparing that partial sum to BEST/cleaned as a 4.7%
saving would be invalid. CGI's cleaned path consumed 9,986 more input tokens,
but the shorter full path omitted qualifications: neither is a valid savings pair.
There are **no pairs where both variants passed**, so cleaning is not approved
for the normal workflow.

## Findings and corrective work

- CGI has inline bullet lists/headings. A single huge passage could be classified
  as context, falsely allowing an apparently reliable HIGH analysis. The
  benchmark's independent original-qualification check exposed the omission.
  Presentation segmentation must apply to normal analysis too, while retaining
  the unchanged raw offer and literal source spans.
- BEST's two missed source conditions concern responsibility/organization and
  business-continuity knowledge. These are qualifications even without the
  previously recognized opening words. Add bounded source guards and regressions.
- BEST removed 944 characters of non-qualification context. CGI removed no
  lines: its experimental difference was presentation splitting, not removal of
  requirements or benefits. These effects must not be conflated.
- Repeated candidate evidence dominates the measured request payload. In the
  two-call BEST/cleaned case, serialized `evidence` was 43,534 characters, versus
  5,252 for repeated `job_source` and 3,907 for `passages`; instructions added
  another 9,362 characters. These are **characters, not per-field token counts**.
  Prioritize measured evidence repetition/batching and schema repair before
  assuming benefit removal is the main optimization.

The earlier URL run `5648e4b739144bb7b8157afe52a38e93` failed extraction for
all three offers with zero model calls. A later saved-snapshot attempt was
refused because the account was busy. Neither is presented as a measurement.
The follow-up below measures saved original offers after the segmentation
corrections, including CLOUDATUS. Sequential full-then-cleaned runs are
exploratory and do not establish statistically significant latency gains.

## Follow-up on verified saved offers after source guards

Run `268edb35b84e40bcb9624f15db84f9b3` used the same model/context, one
permitted repair, and a 120-second per-variant budget. Its source adapter read
only the original offer text from previously verified drafts: this validates
the model experiment through staging API admission/queue/reporting, **not live
URL extraction**. Private snapshots are not included in the repository.

| Offer / variant | Result | Input tokens | Output tokens | Calls | Wall time |
|---|---|---:|---:|---:|---:|
| BEST / full | Timeout; incomplete usage | unknown | unknown | 2 | 140.3 s |
| BEST / cleaned | Timeout; incomplete usage | unknown | unknown | 1 | 126.0 s |
| CLOUDATUS / full | Source coverage rejected | 28,256 | 2,317 | 3 | 108.5 s |
| CLOUDATUS / cleaned | Unsupported language confirmation rejected | 18,857 | 2,085 | 2 | 86.2 s |

The first call also reported 41.3 seconds of model loading. Do not compare these
cold/load-affected wall times to earlier warmed cases as a speed improvement.
No pair passed both validation paths. CLOUDATUS/cleaned's smaller token count
does not authorize cleaning or demonstrate a safe optimization. The safeguards
correctly rejected incomplete coverage and unsupported confirmation instead of
silently awarding a successful recommendation.

Run `0c1459dbb3844e6fb4ad35d29c6f01e7` applied the same saved-source/model/
context/repair/120-second settings to CGI after segmentation corrections:

| Offer / variant | Result | Input tokens | Output tokens | Calls | Wall time |
|---|---|---:|---:|---:|---:|
| CGI / full | Timeout; incomplete usage | unknown | unknown | 3 | 126.3 s |
| CGI / cleaned | Timeout; incomplete usage | unknown | unknown | 3 | 123.3 s |

The two completed calls before cancellation reported 20,895 input / 1,853 output
tokens for full and 20,563 / 1,964 for cleaned. Those are **partial sums**, not
complete totals. Both third calls lacked complete usage, so no savings percentage
is reported. This follow-up no longer reproduces the short, falsely complete
one-call CGI result; it still fails to finish within the chosen budget.

### Decision

Keep cleaning benchmark-only. Across all three saved original offers, the
follow-up produced no fully validated pair. Optimize repetition of evidence,
batching/repair and model latency only with additional bounded experiments and
independent coverage gates; do not deploy a purported token-saving source filter.
These findings are an explicit limitation, not a successful optimization result.
