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
    r'(?:(?:co\s+najmniej|minimum|min\.?)\s+\d+(?:[–-]\d+)?\s+(?:lat|lata|rok|roku)\s+)?'
    r'(?:doświadczeni\w*|wiedz\w*|umiejętnoś\w*|znajomoś\w*)\b|'
    r'(?:znasz|potrafisz|umiesz)\s+\S|pracujesz\s+z\s+\S|'
    r'(?:bardzo\s+)?dobrze\s+(?:znasz|rozumiesz)\b|'
    r'(?:pracowałeś|pracowałaś|współpracowałeś|współpracowałaś)(?:\(-aś\))?\s+z\b|'
    r'posługujesz\s+się\s+(?:językiem|językami)\b)', re.I)
_ADMIN = re.compile(
    r'^(?:skontaktuj\s+się\s+(?:z\s+nami|ze\s+mną|z\s+(?:naszym\s+)?rekruterem)\b|'
    r'skontaktujemy\s+się\s+(?:tylko\s+)?z\s+wybranymi\b|'
    r'contact\s+(?:us|our\s+recruiter)\b|only\s+(?:selected|shortlisted)\s+candidates\s+will\s+be\s+contacted\b)', re.I)
_ORGANIZATION = re.compile(
    r'^(?:what else sets us apart\?|jesteśmy\b|nasza\s+(?:firma|spółka|organizacja)\b|marka\s+obecna\b|'
    r'we\s+(?:are\s+(?!looking\s+for|seeking)|have\b|believe\b|build\b|operate\b)|'
    r'our\s+(?:company|team|business)\b)', re.I)
_SKILL_CONDITION = re.compile(
    r'^(?:(?:English|Polish|German|French|Spanish)\s+(?:proficiency|fluency|language skills)\b|'
    r'(?:very\s+)?(?:good|strong|solid|advanced|excellent|basic)\s+'
    r'(?:(?!(?:requires?|provides?|enables?|allows?|is|are|has|have)\b)[\w+#./-]+\s+){1,5}'
    r'(?:skills?|knowledge|proficiency)\b|'
    r'(?:podstawow\w*|dobr\w*|praktyczn\w*|zaawansowan\w*)\s+umiejętnoś\w*\b|'
    r'drive\s+and\s+a\s+proactive\s+approach\b)', re.I)
_POLISH_QUALIFICATION = re.compile(
    r'^(?:(?:(?:praktyczn|dobr|bardzo\s+dobr|wysok|podstawow|zaawansowan)\w*\s+)*'
    r'(?:doświadczeni\w*|rozumieni\w*|zrozumieni\w*|umiejętnoś\w*|wiedz\w*|zdolnoś\w*)\s+\S)', re.I)
_POLISH_LANGUAGE = re.compile(
    r'język\s+(?:angielski|niemiecki|polski|francuski|hiszpański)'
    r'(?:\s*\(?[ABC][12]\+?\)?|\s+na\s+poziomie\s+(?:[ABC][12]\+?|zaawansowan\w*|komunikatywn\w*|biegł\w*))?'
    r'(?:\s*[-–—:]?\s*mile\s+widzian\w*)?[.,]?', re.I)

_ENGLISH_CANDIDATE = re.compile(
    r'^(?:(?:you\s+)?have\s+'
    r'(?:(?:(?:at\s+least|minimum(?:\s+of)?)\s+)?\d+(?:\.\d+)?\+?\s+years?\s+(?:of\s+)?)?'
    r'(?:(?:prior|practical|hands.on|commercial|professional|proven|relevant)\s+)?experience\b|'
    r'you\s+have\s+(?:a\s+)?(?:(?:good|solid|strong|deep|basic|working)\s+)?(?:knowledge|understanding)\b|'
    r'you\s+have\s+a\s+process.oriented\s+mindset\b|'
    r'(?:you(?:[’\x27]re|\s+are)|are)\s+(?:proficient\s+in|familiar\s+with|self.reliant\b|accountable\b|eager\s+to\s+share\s+knowledge\b)|'
    r'you\s+(?:know\s+how\s+to\b|understand\s+\S|can\s+(?:communicate|explain|recommend)\b|'
    r'take\s+a\s+critical\s+approach\b|must\s+\S|need\s+to\s+\S))', re.I)


def polish_candidate_condition(text: str) -> bool:
    return bool(_POLISH_CANDIDATE.match(clean_source_line(text)))


def english_candidate_condition(text: str) -> bool:
    """Explicit current candidate capabilities, not future duties or offered perks."""
    return bool(_ENGLISH_CANDIDATE.match(clean_source_line(text)))


def english_qualification_condition(text: str) -> bool:
    """Experience/knowledge predicates, not an inferred priority for soft traits."""
    line = clean_source_line(text)
    return english_candidate_condition(line) and bool(re.match(
        r'^(?:(?:you\s+)?have\s+(?!a\s+process.oriented\b)|'
        r'(?:you(?:[’\x27]re|\s+are)|are)\s+(?:proficient|familiar)\b|'
        r'you\s+(?:must\b|need\s+to\b))', line, re.I))


def explicit_skill_condition(text: str) -> bool:
    """An explicit skill predicate is not an action duty or a bare technology tag."""
    line = clean_source_line(text)
    return bool(_SKILL_CONDITION.match(line) or _POLISH_QUALIFICATION.match(line)
                or re.match(r'^(?:deep\s+(?:understanding|knowledge)|demonstrated\s+ability|'
                            r'codzienn\w*,?\s+(?:praktyczn\w*\s+)?prac\w*\s+z\s+agentami)\b', line, re.I)
                or _POLISH_LANGUAGE.fullmatch(line))


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
    return bool(_ADMIN.match(line) or ('organization' in passage.get('hints', []) and _ORGANIZATION.match(line))
                or re.fullmatch(r'[\w.+-]+@[\w.-]+\.\w{2,}', line))
