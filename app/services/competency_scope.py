"""Scoped evidence for knowledge and practice, shared by both analysis paths."""
import re

SCOPES = {
    'networking': (r'network(?:ing)? (?:concepts|principles)|networking', r'\b(?:tcp/ip|dns|dhcp|vpn|mikrotik|fortigate|network(?:ing)?)\b'),
    'security': (r'security (?:best practices|principles|practices)', r'security (?:best practices|principles|policies)|firewall|fortigate|\bvpn\b|access management|security updates'),
    'backup': (r'\bbackup\b', r'\b(?:backups?|veeam)\b'),
    'disaster recovery': (r'disaster recovery|\bDR\b', r'disaster recovery|\bDR\b'),
    'agile': (r'\b(?:agile|scrum)\b', r'\b(?:agile|scrum)\b'),
    'version control': (r'version control|\bgit\b', r'\bgit\b|version control|github.*repositor|repositor.*github'),
    'configuration management': (r'configuration management|\bansible\b', r'configuration management|\b(?:ansible|puppet|chef|saltstack)\b'),
}
THEORY = re.compile(r'awareness|familiarity|basic knowledge|understanding|theoret\w*|training|course|studied|rozumie|szkoleni', re.I)
PRACTICE = re.compile(r'hands.on|practical|professional|\bexperience\b|proficien\w*|working|administer|implement|deploy|perform', re.I)
ACTIVITY = re.compile(r'\b(?:used|uses|using|configured|managed|administered|performed|implemented|maintained|troubleshoot\w*|diagnos\w*|worked|practical|hands.on)\b', re.I)
NEGATIVE_SCOPE = re.compile(r'no (?:prior )?(?:practical |professional |hands.on )?(?:experience|knowledge)|never (?:used|performed|worked)|have not (?:used|performed)|without (?:practical |professional )?(?:experience|practice)', re.I)


def scope_key(name):
    keys = [key for key, (pattern, _) in SCOPES.items() if re.search(pattern, name, re.I)]
    return keys[0] if len(keys) == 1 else ''


def atomic_parts(name):
    """Split established semantic scopes only; never split arbitrary 'and'."""
    pairs = [
        (r'network(?:ing)? concepts and principles and security best practices', ['Networking concepts and principles', 'Security best practices']),
        (r'backup and disaster recovery', ['Backup strategies', 'Disaster recovery strategies']),
        (r'agile scrum experience and working in a ci/cd environment', ['Agile Scrum knowledge', 'Scrum team experience', 'Working in a CI/CD environment']),
        (r'configuration management and version control', ['Configuration management', 'Version control']),
    ]
    for pattern, parts in pairs:
        match = re.search(pattern, name, re.I)
        if match:
            # Keep every leading source modifier, including advanced levels and
            # tenure; do not manufacture weaker titles during atomization.
            prefix = name[:match.start()]
            return [prefix + part for part in parts]
    return []


def scoped_match(matcher, name):
    from app.models.job import RequirementStatus as Status
    from app.services.evidence_matching import EvidenceMatch
    key = scope_key(name)
    if not key or (key == 'security' and re.search(r'endpoint|compliance|monitoring|gpo|patch|identity', name, re.I)):
        return None
    pattern = SCOPES[key][1]
    relevant = [e for e in matcher.entries if re.search(pattern, e.text, re.I)]
    # Evaluate individual statements: a theory statement can coexist with a
    # separately scoped denial of practical experience in the same fact.
    positive, negative, practical = [], [], []
    needs_practice = bool(PRACTICE.search(name))
    for entry in relevant:
        statements = re.split(r'[.;\n]', entry.text)
        scoped = [s for s in statements if re.search(pattern, s, re.I)]
        for statement in scoped:
            if NEGATIVE_SCOPE.search(statement):
                practice_denial = bool(re.search(r'practical|professional|hands.on|performed|worked', statement, re.I))
                if needs_practice or not practice_denial:
                    negative.append(entry)
                continue
            positive.append(entry)
            if ACTIVITY.search(statement) and entry.kind != 'skill' and ':technology:' not in entry.source_id and not re.search(r'training|course|theoret\w*', statement, re.I):
                practical.append(entry)
    def unique(entries):
        return list({e.source_id: e for e in entries}.values())
    if negative and ((practical if needs_practice else positive)):
        return EvidenceMatch(Status.PARTIAL, unique(positive + negative), 'Conflicting evidence for this scope; confirm dates and current competence. Neither claim overrides the other.')
    if negative:
        return EvidenceMatch(Status.ABSENT, unique(positive + negative), 'An explicit denial covers the requested scope; theoretical knowledge does not establish practical experience.')
    if not positive:
        return EvidenceMatch(Status.MISSING, [], 'No documented evidence for this specific scope; this is an incomplete profile, not proof of absence.')
    complete = bool(practical) if needs_practice else True
    if key == 'disaster recovery' and re.search(r'strategies|planning|plan', name, re.I) and not any(re.search(r'strategies|strategy|recovery plan|\brto\b|\brpo\b|restore', e.text, re.I) for e in positive):
        complete = False
    if key == 'security' and not any(re.search(r'security (?:best practices|principles|policies)', e.text, re.I) for e in positive):
        complete = False
    if re.search(r'professional experience', name, re.I):
        complete = complete and any(e.kind == 'experience' or re.search(r'professional', e.text, re.I) for e in practical)
    if re.search(r'proficien\w*|advanced|expert', name, re.I):
        complete = complete and any(re.search(r'proficien\w*|advanced|expert', e.text, re.I) for e in positive)
    return EvidenceMatch(Status.STRONG if complete else Status.PARTIAL, unique(positive),
                         f'Documented {key} evidence evaluated against the requested scope: ' + ('practical use' if needs_practice else 'knowledge/familiarity') + '. Adjacent tools or theoretical training do not establish broader practice or proficiency.')
