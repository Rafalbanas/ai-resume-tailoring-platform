"""Small literal source guards shared by model input and final validation.

These recognize presentation/administration and explicit candidate predicates,
not candidate competence or arbitrary semantic equivalence.
"""
import re

from app.services.job_sections import (
    CONTEXT_HEADINGS,
    DUTY,
    END,
    MANDATORY,
    NEEDED,
    ORG,
    PREFERRED,
    QUALIFICATION_HEADING,
    STACK,
    clean_source_line,
)

_POLISH_CANDIDATE = re.compile(
    r'^(?:(?:masz|posiadasz)\s+(?:praktyczn\w*\s+)?'
    r'(?:doświadczeni\w*|wiedz\w*|umiejętnoś\w*|znajomoś\w*)\b|'
    r'(?:znasz|potrafisz|umiesz)\s+\S|pracujesz\s+z\s+\S|'
    r'posługujesz\s+się\s+(?:językiem|językami)\b)', re.I)
_ADMIN = re.compile(
    r'^(?:skontaktuj\s+się\s+(?:z\s+nami|ze\s+mną|z\s+(?:naszym\s+)?rekruterem)\b|'
    r'skontaktujemy\s+się\s+(?:tylko\s+)?z\s+wybranymi\b|'
    r'contact\s+(?:us|our\s+recruiter)\b|only\s+(?:selected|shortlisted)\s+candidates\s+will\s+be\s+contacted\b)', re.I)


def polish_candidate_condition(text: str) -> bool:
    return bool(_POLISH_CANDIDATE.match(clean_source_line(text)))


def source_heading(text: str) -> bool:
    line = clean_source_line(text)
    return any(pattern.fullmatch(line.rstrip(':').strip())
               for pattern in [MANDATORY, NEEDED, QUALIFICATION_HEADING, PREFERRED,
                               DUTY, ORG, STACK, END, *CONTEXT_HEADINGS.values()])


def known_source_context(passage) -> bool:
    """A real candidate condition wins over an inherited administrative section."""
    if source_heading(passage['text']):
        return True
    from app.services.ollama_analysis import needs_assessment
    if needs_assessment(passage):
        return False
    if set(passage.get('hints', [])) & {'recruitment', 'benefits', 'employment', 'keywords'}:
        return True
    line = clean_source_line(passage['text'])
    return bool(_ADMIN.match(line) or re.fullmatch(r'[\w.+-]+@[\w.-]+\.\w{2,}', line))
