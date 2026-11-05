"""Literal source contracts shared by indexed input and independent validation.

These bounded checks detect demonstrably different subjects, not arbitrary
semantic equivalence. Unknown paraphrases remain the model's responsibility.
"""
import re

AVAILABILITY = re.compile(
    r'gotowoś\w*\s+do\s+pracy|prac\w*\s+(?:zmianow\w*|stacjonarn\w*)|'
    r'work(?:ing)?\s+(?:on[ -]site|in\s+(?:the\s+)?office)|'
    r'(?:shift|on[ -]site|hybrid|remote)\s+(?:work|position|availability)|'
    r'(?:availability|willingness|available|willing)\b.*\b(?:shift|travel|relocat|office)|'
    r'hybrid\s+way\s+of\s+working', re.I)
AVAILABILITY_REASON = 'Availability, location and working arrangements require personal confirmation; technical skills do not establish consent or availability.'

SUBJECTS = {
    'availability': AVAILABILITY,
    'analytical thinking': re.compile(r'analytical\s+thinking|analityczn\w*\s+myślen\w*', re.I),
    'cyberattacks': re.compile(r'cyberattack\w*|cyberatak\w*', re.I),
    'cybersecurity': re.compile(r'cybersecurity|cyberbezpieczeństw\w*', re.I),
    'network fundamentals': re.compile(r'network(?:ing)?\s+(?:fundamentals|basics)|podstaw\w*\s+(?:działania\s+)?sieci', re.I),
}


def source_alignment_issue(name, quote):
    """Reject a shifted label when both source and label name different subjects."""
    source = {key for key, pattern in SUBJECTS.items() if pattern.search(quote)}
    label = {key for key, pattern in SUBJECTS.items() if pattern.search(name)}
    # General cyber-security can include attacks; no such equivalence exists
    # between availability, analytical ability and technical qualifications.
    if source and label and not source & label and not source | label <= {'cyberattacks', 'cybersecurity'}:
        return 'Capability label does not describe its literal source quote: ' + quote
    return ''


def apply_availability(item):
    """Personal decisions cannot be established by cited technical duties."""
    from app.models.job import RequirementStatus
    if not AVAILABILITY.search(getattr(item, 'source_quote', '') or item.name):
        return False
    item.name = getattr(item, 'source_quote', '') or item.name
    item.status = RequirementStatus.MISSING
    item.source_fact_ids = []
    item.evidence = []
    item.evidence_sources = []
    item.reason = AVAILABILITY_REASON
    item.clarification_needed = item.reason
    return True


def language_query(text):
    """Bind an explicit single-language condition, including Polish wording."""
    languages = {
        'English': r'\bEnglish\b|\bangielsk\w*',
        'Polish': r'\bPolish\b|\bpolski\w*',
        'German': r'\bGerman\b|\bniemieck\w*',
        'French': r'\bFrench\b|\bfrancusk\w*',
        'Spanish': r'\bSpanish\b|\bhiszpańsk\w*',
    }
    found = [name for name, pattern in languages.items() if re.search(pattern, text, re.I)]
    if len(found) != 1:
        return ''
    query = text + ' ' + found[0]
    if re.search(r'zaawansowan\w*|biegł\w*', text, re.I):
        query += ' advanced'
    return query
