"""Conservative presentation cleanup; similarity alone never deletes evidence."""
import re

from app.services.fact_catalog import STOP_WORDS

_FORMS = {
    'deploys': 'deploy', 'deployed': 'deploy', 'deploying': 'deploy', 'deployment': 'deploy',
    'maintains': 'maintain', 'maintained': 'maintain', 'maintenance': 'maintain',
    'builds': 'build', 'built': 'build', 'building': 'build',
    'creates': 'create', 'created': 'create', 'creation': 'create',
    'implements': 'implement', 'implemented': 'implement',
    'monitors': 'monitor', 'monitored': 'monitor', 'monitoring': 'monitor',
    'tests': 'test', 'tested': 'test', 'testing': 'test',
    'services': 'service', 'models': 'model', 'workflows': 'workflow',
    'applications': 'application', 'systems': 'system', 'containers': 'container',
    'automates': 'automate', 'automated': 'automate', 'automation': 'automate',
}
_ACTIONS = {'deploy', 'maintain', 'build', 'create', 'implement', 'monitor', 'test', 'support', 'administer', 'analyse', 'resolve', 'integrate', 'automate'}
_CREATION = {'build', 'create', 'implement'}
_QUALIFIER = re.compile(r'\b(?:using|including|via|with)\s+.+?(?=\s+(?:on|for|in)\b|[.;]|$)', re.I)
_SENTENCES = re.compile(r'(?<=[.!?])\s+(?=[A-Z])')


def concept_sequence(text):
    values = []
    for match in re.finditer(r'[\w+#]+', text):
        raw, word = match[0], match[0].casefold()
        identifier = len(raw) == 1 and raw.isupper() and match.start() > 0
        if word not in STOP_WORDS or identifier:
            values.append(_FORMS.get(word, word))
    return values


def concepts(text):
    return set(concept_sequence(text))


def _subsumed(short, long):
    small, large = concepts(short), concepts(long)
    if not small or not large:
        return False
    protected = {'no', 'not', 'never', 'without', 'basic', 'junior', 'advanced', 'expert', 'theoretical', 'planned', 'experimental', 'production', 'local', 'locally'}
    if (small & protected != large & protected
            or re.findall(r'(?<!\w)\d+(?:\.\d+)?(?!\w)', short) != re.findall(r'(?<!\w)\d+(?:\.\d+)?(?!\w)', long)):
        return False
    actions, other_actions = small & _ACTIONS, large & _ACTIONS
    # Nominal artifact descriptions already express the artifact's existence;
    # testing/monitoring/administration are separate activities, never boilerplate.
    if actions <= _CREATION and not other_actions:
        small -= _CREATION
    elif actions != other_actions:
        return False
    if not small <= large:
        return False
    # Preserve action/object binding, not just a bag of words. Swapping actors
    # or what they acted on must not turn a different proposition into a repeat.
    short_sequence = [v for v in concept_sequence(short) if v in small]
    remaining = iter(concept_sequence(long))
    return all(any(v == expected for v in remaining) for expected in short_sequence)


def _merge_qualifiers(first, second):
    if re.findall(r'(?<!\w)\d+(?:\.\d+)?(?!\w)', first) != re.findall(r'(?<!\w)\d+(?:\.\d+)?(?!\w)', second):
        return None
    base_a, base_b = concepts(_QUALIFIER.sub('', first)), concepts(_QUALIFIER.sub('', second))
    if (base_a != base_b or not (base_a & _ACTIONS)
            or concept_sequence(_QUALIFIER.sub('', first)) != concept_sequence(_QUALIFIER.sub('', second))):
        return None
    # Same action/object core; attach only literal, distinct source qualifiers.
    # Negation, levels, numbers and production/local scope remain in the core.
    additions = [m[0].strip(' ,;') for m in _QUALIFIER.finditer(second) if not concepts(m[0]) <= concepts(first)]
    if not additions:
        return first
    return first.rstrip('.!?') + ', ' + ', '.join(additions) + '.'


def deduplicate_text(value):
    sentences = _SENTENCES.split(value.strip()) if value.strip() else []
    result = []
    for sentence in sentences:
        for index, prior in enumerate(result):
            if _subsumed(sentence, prior):
                break
            if _subsumed(prior, sentence):
                result[index] = sentence
                break
            merged = _merge_qualifiers(prior, sentence)
            if merged:
                result[index] = merged
                break
        else:
            result.append(sentence)
    return ' '.join(result)


def unfinished(value):
    return bool(value.strip() and (re.search(r'\b(?:and|or|including|such as|using|with|to)[.!?]?$', value.strip(), re.I)
                                 or value.count('(') != value.count(')')))


def deduplicate_bullets(bullets):
    kept = []
    for original in bullets:
        bullet = original.model_copy(deep=True)
        bullet.text = deduplicate_text(bullet.text)
        for prior in kept:
            combined = deduplicate_text(prior.text + ' ' + bullet.text)
            if len(_SENTENCES.split(combined)) == 1:
                prior.text = combined
                prior.source_fact_ids = list(dict.fromkeys([*prior.source_fact_ids, *bullet.source_fact_ids]))
                break
        else:
            kept.append(bullet)
    return kept


def quality_issues(resume, profile):
    issues = []
    blocks = [('summary', resume.professional_summary)]
    blocks += [(f'experience: {e.company}', b.text) for e in resume.experience for b in e.bullets]
    blocks += [(f'project: {p.name}', p.description) for p in resume.projects]
    for name, text in blocks:
        if name.startswith('experience:') and not text.strip():
            issues.append(f'Empty fragment in {name}.')
        if unfinished(text):
            issues.append(f'Unfinished fragment in {name}.')
        if text and deduplicate_text(text) != text.strip():
            issues.append(f'Repeated source statement in {name}.')
    for experience in resume.experience:
        if len(deduplicate_bullets(experience.bullets)) < len(experience.bullets):
            issues.append(f'Repeated evidence within experience: {experience.company}.')
        for index, left in enumerate(experience.bullets):
            for right in experience.bullets[index+1:]:
                shared_evidence = set(left.source_fact_ids) & set(right.source_fact_ids)
                if shared_evidence and concepts(left.text) == concepts(right.text) and left.text != right.text:
                    issues.append(f'Similar wording cites the same evidence in {experience.company}; distinct scope retained for review.')
    # Cross-section overlap is a review hint, not a deletion instruction. Repeating
    # a key qualification in summary/experience can be useful and truthful.
    for i, (name, text) in enumerate(blocks):
        for other_name, other in blocks[i+1:]:
            if name != other_name and text and other and concepts(text) == concepts(other):
                issues.append(f'Repeated evidence across {name} and {other_name}; review emphasis.')
    for values in profile.skills.values():
        for source in values:
            match = re.fullmatch(r'(?:Basic|Junior|Theoretical)\s+(.+)|(.+?)\s*\((?:basic|junior|theoretical)\)', source, re.I)
            if not match:
                continue
            name = (match[1] or match[2]).strip()
            for value in [*resume.core_skills, resume.professional_summary, resume.headline]:
                if re.search(r'\b(?:expert|advanced|senior)\s+(?:(?:knowledge|experience|expertise)\s+(?:of|in|with)\s+)?' + re.escape(name) + r'\b|\b' + re.escape(name) + r'\s+(?:expert|expertise|advanced)\b', value, re.I):
                    issues.append(f'Unsupported proficiency increase for {name}.')
    from app.services.languages import profile_languages
    ranks = {'A1': 1, 'A2': 2, 'B1': 3, 'B2': 4, 'C1': 5, 'C2': 6, 'NATIVE': 7}
    for declaration in profile_languages(profile):
        name = declaration.split()[0]
        level = re.search(r'\b([ABC][12]\+?|Native)(?!\w)', declaration, re.I)
        if not level:
            continue
        observed = level[1].upper()
        for value in [resume.professional_summary, *resume.core_skills]:
            claims = re.findall(r'\b' + re.escape(name) + r'\s*(?:at\s+)?(?:level\s+)?([ABC][12]\+?|native)(?!\w)', value, re.I)
            claims += re.findall(r'\b([ABC][12]\+?|native)\s+' + re.escape(name) + r'\b', value, re.I)
            if re.search(r'\bfluen\w*\s+(?:in\s+)?' + re.escape(name) + r'\b', value, re.I):
                claims.append('C1')
            if any(ranks.get(c.upper().rstrip('+'), 9) > ranks[observed.rstrip('+')]
                   or (c.endswith('+') and c.rstrip('+').upper() == observed and not observed.endswith('+')) for c in claims):
                issues.append(f'Unsupported proficiency increase for {name}.')
    return list(dict.fromkeys(issues))
