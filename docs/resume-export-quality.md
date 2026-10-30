# Profile-driven CV export

PDF and DOCX share `resume_export.py`. Contacts come from the active profile, with visible email and readable URL labels. Unicode URL paths are encoded once; existing encoded separators remain unchanged. Email validation checks syntax without contacting a mail service. Invalid addresses or non-HTTP(S) website links stop export.

The authenticated **Profile → Contact details** form edits the single `personal.email` value in that account's private `master_profile.json`. Saving validates one address, persists it atomically and updates the active account's in-memory profile. Portfolio and other profile fields remain unchanged. Neither templates nor AI output supply a default email: the tailored-resume schema has no contact fields. Both layouts, paginated previews and PDF/DOCX exporters read the profile through the shared contact builder. Saving an email does not regenerate or overwrite saved CV files; previews continue to render with the active profile.

`languages.py` groups natural-language declarations, preserving explicitly stated CEFR levels and Native. Natural languages are excluded from technical skill selection and export. The skills bank preserves verified technology names and basic proficiency qualifiers, without automatically adding Hands-on. Selection recognizes scoped SQL/T-SQL and HTTPX/JSON integration evidence without selecting unrelated SQLite, JSON-LD or JWT skills merely because they share a generic token. Equivalent support/documentation labels do not occupy multiple slots.

`FactValidator` keeps the supported occupation as the headline and builds a short summary from attested employment, troubleshooting, SQL, integration and professional language facts. Only bounded composition of source clauses is allowed; arbitrary model wording still resolves to source text. Existing verified summary edits remain supported. Assistance with troubleshooting remains assistance, never administration. Relevant actual AI tool usage is shown in project descriptions. Employment dates, employers, education and skill eligibility remain profile-controlled.

Coverage checks compare confirmed employer requirements with the facts actually selected for the CV. Missing coverage creates an explicit review message; it does not create qualifications. Portal tags, partial requirements and missing evidence do not authorize new claims.

PDF exports retain the navy sidebar, current photo and standard sections. A real rendered-text check detects float sections silently omitted by WeasyPrint. Whole overflowing sections move into normal document flow, which can paginate. Interests move as a compact paragraph. No page-count rule removes employment, projects or facts. Text boxes are checked against the physical page and their column. The consent footer uses a reserved page margin and readable 8pt text. PDF has an English language declaration and tagged document structure. Preview and export use the same pagination engine.

DOCX keeps searchable text, profile-driven hyperlink relationships, the photo's proportions, employment dates, content and a real footer. Its existing simplified single-column layout is retained.

## Verification

Synthetic regressions cover visible/searchable contacts and link targets in both formats/layouts; long addresses; Unicode; encoded URL separators; invalid contacts; language/skill duplicates; scoped selection; summary source provenance; missing coverage; supported troubleshooting vs administration; sidebar overflow; photo preference and unchanged source models. Existing document, workflow and fact-boundary tests remain in the suite.

The saved control offer is regenerated once with the existing Ollama model. The raw output and validated CV remain private. PDF text and link annotations, DOCX XML and relationships, PDF page rendering, and LibreOffice DOCX-to-PDF conversion are checked before publication. ATS Classic uses one column for systems that infer reading order from page geometry. Modern Sidebar has coherent source/tag order, but geometry-based extractors can choose a different order for sidebar and main sections; no universal ATS guarantee or hiring prediction is made.

Candidate contacts, source profile, model output and exported files stay outside Git. Export changes require no profile migration or LLM configuration change.

Experience facts may define `cv_fact_conditions` in the private master profile:
map an exact fact sentence to a list of posting terms. At least one term must
appear as a complete word or phrase in the original role or description. An empty
list excludes the fact; an absent key keeps normal selection. These presentation
conditions apply before retrieval (including index failure) and again during
validation, including chronological fallbacks. Analysis can still assess the fact.

Model approval cannot bypass checks for internal evidence annotations, unrelated
citations, or new cited technologies/acronyms. Export also refuses visible internal
annotations in PDF and DOCX content. Evidence labels resolve to canonical profile
facts instead of administrative descriptions whenever a source is available.

CV generation and review distinguish static routes and network services from
routing protocols. A named routing-protocol list containing static routes, NAT,
DHCP or VPN is rejected at export, and a model summary approval cannot bypass the
check. Valid mentions of OSPF/BGP followed by separate NAT/DHCP configuration remain
allowed. This targeted check does not establish experience with any dynamic
routing protocol.

For integration-oriented offers, source-only fallback summaries introduce the
actual dated occupation before selecting technical details. Relevant networking
and collaboration/escalation facts from employment receive a small presentation
priority even when analysis cited only a global skill. Employer details always
come from that employer's own facts; global router configuration declarations
cannot become an employer claim. Conditional fact rules and manual-edit
preservation still apply, and one-page selection can omit optional details.

Concurrent document export forms use a per-account bounded queue (four admitted
requests including the active one). Forms are size-limited and CSRF-checked before
waiting up to 180 seconds for the account write lock, without holding upload
admission. Queue overflow/timeout returns browser users to their saved analysis
with a retry notice. Other account updates retain fail-fast write protection.
Document CPU operations, including previews, have a separate bounded queue of
four and a 60-second admission deadline; native work still has its existing
60-second execution budget. Cancellation and errors release queue admission.
