"""Recover only explicit, general CS degree conditions from education records."""
import re


def degree_match(matcher, name):
    from app.models.job import RequirementStatus as Status
    from app.services.evidence_matching import EvidenceMatch

    # Full scope, not a keyword match: a doctorate, specialist field, minimum
    # grade or years of experience cannot be satisfied by a generic CS degree.
    if not re.fullmatch(
        r'(?:a\s+)?(?:university\s+)?(?:degree|bachelor(?:\x27s)? degree|master(?:\x27s)? degree)'
        r'\s+in\s+(?:IT\s*(?:/|or)\s*)?Computer Science'
        r'(?:\s+or equivalent experience)?[.]?', name.strip(), re.I
    ):
        return None
    masters = bool(re.search(r'\bmaster', name, re.I))
    for index, edu in enumerate(matcher.catalog.profile.education):
        title = edu.qualification + ' ' + edu.degree
        if not re.search(r'\bComputer Science\b', title, re.I):
            continue
        if not re.search(r'\b(?:MSc|BSc|Bachelor|Master)\b', title, re.I):
            continue
        if masters and not re.search(r'\b(?:MSc|Master)\b', title, re.I):
            continue
        record = ' '.join([title, edu.dates, *edu.facts])
        pending = re.search(r'\b(?:ongoing|in progress|expected|pursuing|studying|enrolled|pending|unfinished|not (?:yet )?completed|w trakcie)\b', record, re.I)
        pending = pending or re.search(r'\b(?:present|current|obecnie)\b', edu.dates, re.I)
        future = any(int(year) > matcher.as_of.year for year in re.findall(r'\b20\d{2}\b', edu.dates))
        if pending or future:
            continue
        entries = [e for e in matcher.entries if e.kind == 'education' and e.owner_index == index
                   and ':fact:' not in e.source_id and ':thesis:' not in e.source_id]
        if entries:
            return EvidenceMatch(Status.STRONG, entries, 'Documented completed Computer Science degree satisfies the general degree condition; project work is not substituted for education.')
    return None
