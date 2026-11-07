"""Narrow objective ceilings for explicit advanced Python/ML qualifications.

Practical project use and an intermediate skill are not an advanced attestation.
Other semantic scopes retain their existing validators; language has its own guard.
"""
import re

from app.services.evidence_matching import NEGATIVE

ADVANCED = re.compile(
    r'^(?:(?:very good|advanced|expert|excellent)\s+(?:knowledge|proficiency|command|understanding)\b|'
    r'(?:bardzo dobr\w*|zaawansowan\w*|eksperck\w*)\s+znajomoś\w*\b)', re.I)
DECLARED = re.compile(r'\b(?:advanced|expert)\b|zaawansowan\w*|eksperck\w*', re.I)
SUBJECTS = {
    'Python': r'\bPython(?:a|em|ie)?\b',
    'Machine Learning': r'\b(?:Machine Learning|ML|scikit-learn|XGBoost)\b|uczeni\w* maszynow\w*',
}


def proficiency_ceiling(text, entries, bank=None):
    text = re.split(r',\s*(?:preferably|najlepiej)\b', text, maxsplit=1, flags=re.I)[0]
    if not ADVANCED.search(text):
        return None
    missing = []
    for name, pattern in SUBJECTS.items():
        if not re.search(pattern, text, re.I):
            continue
        denial = (r'\b(?:no|not|without)\s+(?:advanced|expert)\s+'
                  r'(?:(?:knowledge|proficiency)\s+(?:of|in)\s+|in\s+)?(?:' + pattern + ')')
        statements = [statement for entry in entries for statement in re.split(r'[.;\n]', entry.text)]
        declared = any(re.search(pattern, statement, re.I) and DECLARED.search(statement)
                       and not NEGATIVE.search(statement) and not re.search(denial, statement, re.I)
                       and not re.search(r'\b(?:basic|intermediate|beginner|currently learning)\b|podstawow\w*', statement, re.I)
                       for statement in statements)
        bank_verified = bank and any(skill.name.casefold() == name.casefold()
                                    and skill.level == 'advanced' and bank.eligible(skill)
                                    for skill in bank.skills)
        if not (declared or bank_verified):
            missing.append(name)
    if not missing:
        return None
    note = ('Required advanced proficiency is not established for: ' + ', '.join(missing)
            + '. Practical/academic project use does not establish this level.')
    return 'partial' if entries else 'missing', note


def apply_proficiency_ceiling(item, entries, bank=None):
    from app.models.job import RequirementStatus
    if item.status != RequirementStatus.STRONG:
        return False
    ceiling = proficiency_ceiling(getattr(item, 'source_quote', '') or item.name, entries, bank)
    if not ceiling:
        return False
    item.status = RequirementStatus(ceiling[0])
    if ceiling[1] not in item.reason:
        item.reason += ' ' + ceiling[1]
    return True
