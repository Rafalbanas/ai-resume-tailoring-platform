# CVTailor — canonical project description

Implementation scope: repository code, not a claim that the new retrieval feature has been deployed to production. CVTailor is a personal project; these statements do not imply commercial employment, advanced ML expertise or measured performance gains.

## Polski

CVTailor to aplikacja w Pythonie i FastAPI, która analizuje oferty pracy i generuje CV w PDF/DOCX na podstawie potwierdzonych danych kandydata. Lokalny RAG z rankingiem BM25 wybiera fakty z profilu przed generowaniem przez Ollama lub Gemini. Identyfikatory i typy źródeł pozwalają prześledzić dobór informacji, a niezależny Truth Lock kontroluje zgodność treści z profilem, poziomami kompetencji i charakterem doświadczenia.

## English

CVTailor is a Python and FastAPI application that analyzes job postings and generates PDF/DOCX resumes from attested candidate data. Local RAG with BM25 ranking selects profile facts before generation through Ollama or Gemini. Source IDs and types make fact selection traceable, while an independent Truth Lock validates claims against profile evidence, skill levels and experience scope.

## English CV bullets

- Implemented local lexical RAG with BM25 ranking to select candidate facts for job-specific CV generation through Ollama and Gemini.
- Preserved source IDs and employment, project and education scope, with independent Truth Lock validation of generated claims and skill eligibility.
- Added regression tests for offer-specific retrieval, profile updates, candidate isolation, retrieval failures and unsupported technology claims.

## Technologies and methods supported by this change

Python; FastAPI; Pydantic; BM25 lexical search; Retrieval-Augmented Generation (RAG); Ollama API; Gemini API integration; JSON; pytest; pytest-asyncio; Ruff. The existing application also uses HTTPX, Jinja2, WeasyPrint, python-docx, Docker and GitHub Actions (see README and dependency files). List a personal skill level only if it reflects the owner's actual contribution and knowledge. API integration does not imply training LLMs.

Retrieval uses the Python standard library and a per-request in-memory index. It does not use embeddings, a vector database or an agent framework. The legacy n8n webhook path is outside the new retrieval flow. There is no measured quality, speed or memory improvement claim.

## Profile maintenance

The private `data/master_profile.json` contains the owner's canonical `AI Resume Tailoring Platform` project. The following implementation facts were appended to that project in the local private profile, preserving its existing description/facts and IDs referenced by the private skills bank:

1. Implemented local lexical RAG with BM25 ranking over attested candidate facts before CV generation through Ollama and Gemini, preserving source IDs and employment, project and education scope.
2. Rebuilds the retrieval index from the current candidate profile for each generation request without a shared cache, with identity anchors on no matches and canonical-catalog fallback on search failures.
3. Added synthetic regression tests for offer-specific fact selection, profile updates, candidate isolation, retrieval fallback and unsupported technology claims while retaining independent Truth Lock validation.

These are implementation statements, not evidence of production deployment. Do not modify generated CVs or saved application history to apply them. The fictional example profile is deliberately kept fictional and is not a record of the owner's work.
