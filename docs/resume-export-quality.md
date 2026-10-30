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
