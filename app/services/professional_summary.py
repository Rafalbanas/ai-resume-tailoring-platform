"""Select concise source sentences; job text influences order, never candidate facts."""
import re

from app.services.fact_catalog import FactCatalog, normalized_tokens

_ACTIVITY_VERBS = {
    'integrated': 'integrating', 'integrates': 'integrating',
    'used': 'using', 'uses': 'using', 'automated': 'automating', 'automates': 'automating',
    'implemented': 'implementing', 'implements': 'implementing',
    'developed': 'developing', 'develops': 'developing',
    'supported': 'supporting', 'supports': 'supporting',
    'provided': 'providing', 'provides': 'providing',
    'analyzed': 'analyzing', 'analyzes': 'analyzing',
    'built': 'building', 'maintained': 'maintaining', 'maintains': 'maintaining',
}


def activity_clause(text: str) -> str | None:
    """Only inflect a known initial verb; never infer tense, scope or a result.

    Unknown subjects, negations, plans and conditional clauses remain verbatim.
    """
    text = text.strip().rstrip('.!?')
    verb, separator, rest = text.partition(' ')
    if (separator and verb.casefold() in _ACTIVITY_VERBS
            and not re.match(r'(?:to|by)\b', rest, re.I)):
        return _ACTIVITY_VERBS[verb.casefold()] + ' ' + rest
    return None


def summary_contains_clause(summary: str, text: str) -> bool:
    """Compare complete literal/activity clauses, not fuzzy semantic overlap."""
    variants = [text.strip().rstrip('.!?'), activity_clause(text)]
    activities = '|'.join(sorted(set(_ACTIVITY_VERBS.values())))
    start = r'(?:^|[.!?;:]\s*|\b(?:includes|involved|and)\s+)'
    end = r'(?=[.!?;]|$| and (?:' + activities + r')\b)'
    return any(value and re.search(start + re.escape(value) + end, summary, re.I)
               for value in variants)


def employment_scope_issue(value: str, entries, profile) -> bool:
    """An employer introduction cannot borrow another employer's cited duties.

    This is a conservative presentation check, not a semantic entailment judge.
    General background without a named current employer is left to normal review.
    """
    if not profile.experience:
        return False
    current = profile.experience[0]
    if current.end.casefold() not in {'present', 'current', 'now', 'obecnie'}:
        return False
    if not re.search(r'(?<!\w)' + re.escape(current.company) + r'(?!\w)', value, re.I):
        return False
    if re.search(r'\b(?:previous(?:ly)?|earlier|former|prior|past roles|poprzedni\w*|wcześniej)\b', value, re.I):
        return False
    for entry in entries:
        if entry.kind != 'experience' or entry.owner_index in {None, 0}:
            continue
        owner = profile.experience[entry.owner_index]
        if not re.search(r'(?<!\w)' + re.escape(owner.company) + r'(?!\w)', value, re.I):
            return True
    return False


def deduplicate_summary(value: str, catalog: FactCatalog) -> str:
    """Fuse repeated verified clauses; preserve the identity and every detail.

    Only verbatim source sentences qualify. Similar model paraphrases, negations,
    differing numbers and unknown wording remain subject to normal Truth Lock.
    """
    verified = {e.text.strip().rstrip(".!?") for e in catalog.prompt_entries}
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", value.strip())
    result: list[str] = []
    for sentence in sentences:
        raw = sentence.rstrip(".!?")
        merged = False
        if raw in verified:
            prefix, separator, detail = raw.partition(", ")
            tokens = normalized_tokens(prefix) - {"technical"}
            for index, previous in enumerate(result):
                prior = previous.rstrip(".!?")
                if prior not in verified or ", " in prior:
                    continue
                prior_tokens = normalized_tokens(prior) - {"technical"}
                # Additional identity information in the shorter source is kept.
                # No fuzzy threshold: every token of the repeated clause must exist.
                if (tokens and tokens <= prior_tokens
                        and re.findall(r"\d+", prefix) == re.findall(r"\d+", prior)
                        and re.findall(r"\b(?:not|never|no|without)\b", prefix, re.I)
                        == re.findall(r"\b(?:not|never|no|without)\b", prior, re.I)):
                    if "technical support" in prefix and "technical support" not in prior:
                        prior = prior.replace("support", "technical support", 1)
                    result[index] = prior + (separator + detail if separator else "") + "."
                    merged = True
                    break
        if not merged:
            result.append(sentence)
    return " ".join(result)


def build_summary(catalog: FactCatalog, role: str, *, compact: bool = False, priorities: dict[str, float] | None = None) -> tuple[str, list[str]]:
    """Build concise, provenance-scoped sentences from attested clauses.

    Only punctuation/capitalization and provenance labels are composed. The one L1/L2 historical clause
    is extracted from an explicit employment support statement, never a title.
    Projects can supply integration evidence, but cannot become job experience.
    """
    entries = [e for e in catalog.prompt_entries
               if e.kind == "summary" or (e.kind in {"experience", "project"} and ":fact:" in e.source_id)]
    entries = [e for e in entries if not re.search(r"\byears?\b|\blat\b", e.text, re.I)]
    from app.services.job_sections import relevance_text
    tokens = normalized_tokens(relevance_text(role))
    # A support duty mentioned in a different job must not force a support-first
    # summary. Legacy support composition is retained for actual support roles.
    support = bool(normalized_tokens(role.splitlines()[0] if role.splitlines() else role) & {"support", "troubleshooting", "incident"})
    if support:
        tokens |= {"support", "troubleshooting", "incident", "sql", "api", "automation", "english", "logs"}
    selected_ids: list[str] = []
    used = set()
    groups: list[list[str]] = [[], [], [], []]

    def compose(values):
        # Keep projects in one dedicated block: never repeat the label and never
        # let a following employment fact inherit the project's scope.
        def clauses(parts):
            return '; '.join(part[0].lower() + part[1:]
                             if i and part.startswith(('Analyzes ', 'Integrates ', 'Integrated ', 'Automates ', 'Used ', 'Provided '))
                             else part for i, part in enumerate(parts))

        sentences = []
        def scoped(label, parts):
            activities = [activity_clause(part) for part in parts]
            lead = {'Project work: ': 'Project work includes ',
                    'Previous roles: ': 'Previous roles involved ',
                    'Background: ': 'Broader experience includes '}[label]
            # Keep one scope block. A clause outside this small inflection map
            # retains its original wording and scope rather than being guessed.
            return ((lead + ' and '.join(activities)) if all(activities)
                    else label + clauses(parts)) + '.'

        for index, group in enumerate(values):
            if not group:
                continue
            if index == 1:
                scopes = {'': [], 'Previous roles: ': [], 'Background: ': []}
                for clause in group:
                    label = next((prefix for prefix in scopes if prefix and clause.startswith(prefix)), '')
                    scopes[label].append(clause[len(label):])
                sentences.extend(scoped(label, parts) if label else clauses(parts) + '.'
                                 for label, parts in scopes.items() if parts)
            else:
                sentences.append(scoped('Project work: ', group) if index == 2 else clauses(group) + '.')
        return ' '.join(sentences)

    def add(index, entry, text=None, *, reuse=False):
        if not entry or (entry.source_id in used and not reuse):
            return
        clause = (text or entry.text).strip().rstrip(".!?")
        if entry.kind == 'project':
            index = 2
        elif index and entry.kind == 'experience':
            index = 1
            current = catalog.profile.experience[0] if catalog.profile.experience else None
            if entry.owner_index != 0 or not current or current.end.casefold() not in {'present', 'current', 'now', 'obecnie'}:
                clause = 'Previous roles: ' + clause
        elif index in {1, 2} and entry.kind == 'summary':
            index = 1
            # A global profile sentence does not establish a current-employer duty.
            clause = 'Background: ' + clause
        candidate = [list(g) for g in groups]
        candidate[index].append(clause)
        result = compose(candidate)
        if len(result) <= 700:
            groups[index].append(clause)
            selected_ids.append(entry.source_id)
            used.add(entry.source_id)

    def first(pattern, *, kinds=None):
        return next((e for e in entries if e.source_id not in used
                     and (not kinds or e.kind in kinds) and re.search(pattern, e.text, re.I)), None)

    # A current employer must be explicitly named in an attested summary, or its
    # identity comes directly from the dated employment record.
    identity = first(r"(?:provides|providing).*support", kinds={"summary"}) if support else None
    if identity:
        add(0, identity)
        # Merge only repeated verbatim, attested identity clauses. Keep the
        # additional detail and both original evidence IDs.
        for entry in ([] if compact else entries):
            if entry.kind != "experience" or entry.owner_index != 0 or entry.source_id in used:
                continue
            merged = deduplicate_summary(identity.text + " " + entry.text, catalog)
            if len(merged) < len(identity.text + " " + entry.text) and merged != identity.text:
                groups[0][0] = merged.rstrip(".!?")
                selected_ids.append(entry.source_id)
                used.add(entry.source_id)
                break
    elif catalog.profile.experience and support:
        current = catalog.profile.experience[0]
        fact = next((e for e in entries if e.kind == "experience" and e.owner_index == 0), None)
        if fact:
            add(0, fact, f"{current.title} at {current.company}" if current.end.casefold() in {"present", "current", "now", "obecnie"} else f"Experience as {current.title} at {current.company}")
    elif support:
        add(0, next(iter(entries), None))
    if support:
        historical = next((e for e in entries if e.kind == 'experience' and e.owner_index != 0
                           and e.source_id not in used and re.search(r'\bL1\s*(?:and|/)\s*L2\s+(?:user\s+)?support', e.text, re.I)), None)
        if historical and not compact:
            add(0, historical, "previous roles included L1 and L2 support")
        elif not compact:
            # The same duty at the current employer stays current, rather than
            # being dropped or relabelled as historical experience.
            add(1, next((e for e in entries if e.kind == 'experience' and e.owner_index == 0
                         and e.source_id not in used and re.search(
                             r'\bL1\s*(?:and|/)\s*L2\s+(?:user\s+)?support', e.text, re.I)), None))
        add(1, first(r"(?:application.*network|network.*application).*troubleshoot|troubleshoot.*(?:application.*network|network.*application)"))
        if not groups[1]:
            add(1, first(r"troubleshoot|incident", kinds={"summary", "experience"}))
        if not compact:
            add(1, first(r"(?:analy[sz].*logs|logs.*root causes)", kinds={"summary", "experience"}))
        # English has its own last sentence; avoid incident clauses taking all room.
        add(3, first(r"English.*(?:B2|professional|daily)|(?:documentation|communication).*English", kinds={"summary", "experience"}))
        add(2, first(r"(?:SQL|T-SQL).*(?:queries|troubleshooting|verification)", kinds={"experience"}))
        add(2, first(r"(?:REST.*(?:HTTPX|JSON)|HTTPX.*(?:REST|JSON))", kinds={"project"}))
        if not compact:
            add(2, first(r"(?:automates|automated).*Python", kinds={"summary", "experience"}))
    else:
        if tokens & {"degree", "education", "science", "bachelor", "master"}:
            education = next((e for e in catalog.prompt_entries if e.kind == "education"
                              and "computer science" in e.text.casefold() and ":fact:" not in e.source_id
                              and ":thesis:" not in e.source_id), None)
            if education:
                source = catalog.profile.education[education.owner_index]
                add(3, education, f"{source.qualification}, {source.institution} ({source.dates})")
        # Introduce the actual dated occupation before technical details. The
        # advertised title cannot confer a new occupation, even in a fallback.
        if catalog.profile.experience:
            current = catalog.profile.experience[0]
            fact = next((e for e in entries if e.kind == 'experience' and e.owner_index == 0), None)
            if fact:
                identity = f'{current.title} at {current.company}' if current.end.casefold() in {'present', 'current', 'now', 'obecnie'} else f'Experience as {current.title} at {current.company}'
                add(0, fact, identity)
        ranked = sorted(entries, key=lambda e: ((priorities or {}).get(e.source_id, 0), len(normalized_tokens(e.text) & tokens)), reverse=True)
        used_priorities = set()
        details = 0
        for entry in ranked:
            if entry.source_id in used:
                continue
            if details >= (2 if groups[0] else 3):
                break
            priority = (priorities or {}).get(entry.source_id, 0)
            if priority and priority in used_priorities:
                # Several sentences citing the same leading requirement should
                # not consume the summary at the expense of other evidence.
                continue
            add(min(details + 1, 2), entry)
            if entry.source_id in used:
                details += 1
                if priority:
                    used_priorities.add(priority)
    text = compose(groups)
    return deduplicate_summary(text, catalog), list(dict.fromkeys(selected_ids))
