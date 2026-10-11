"""Contextual, directional evidence matching, independent of model suggestions.

These rules establish documented scope, never infer mastery from a technology
name. Matching does not change the stricter automatic CV export boundary.
"""
import calendar
import re
from dataclasses import dataclass
from datetime import date

from app.models.job import RequirementStatus as Status
from app.services.fact_catalog import FactEntry

FAMILIES = {
    'sql': r'\b(?:sql(?: server)?|ms sql|mssql|t-sql|transact-sql)\b',
    'api': r'\b(?:rest(?:ful)?\s+apis?|http\s+(?:apis?|endpoints?)|api integration|apis?)\b',
    'javascript': r'\b(?:javascript|vanilla js|client-side javascript|js)\b',
    'typescript': r'\btypescript\b',
    'ai_tools': r'\b(?:ai[- ](?:assisted|supported|powered)|ai coding|codex|coding assistants?|ai[- ]assisted tools)\b',
    'troubleshooting': r'\b(?:troubleshoot\w*|problem solving|technical diagnostics?|technical incidents?)\b',
    'support': r'\b(?:technical|it|application|product|user|l[12]|tier [12]) support\b',
    'incident': r'\bincident (?:handling|management|investigation)\b',
    'documentation': r'\b(?:technical documentation|runbooks?|knowledge base|support documentation)\b',
    'communication': r'\b(?:communication|non-technical audiences)\b',
}
NEGATIVE = re.compile(r'\b(?:no (?:prior )?(?:experience|knowledge)|never (?:used|worked with)|have not used|not proficient)\b', re.I)
SQL_ADVANCED = re.compile(r'\b(?:dba|database administration|cluster\w*|replication|performance tuning|query optimi[sz]ation)\b', re.I)
API_DEBUG = re.compile(r'\b(?:debug\w*|troubleshoot\w*|oauth|authentication flows?|auth)\b', re.I)
LEVEL = re.compile(r'\b(?:[ABC][12]\+?|native|advanced|expert|fluency|fluent|basic|working knowledge|hands.on)\b\+?', re.I)
YEARS = re.compile(r'\b(\d+(?:\.\d+)?)\s*(?:[–−-]\s*\d+(?:\.\d+)?)?\s*\+?\s*(?:years?|lat)\b', re.I)


def required_level(text: str) -> str:
    language_level = re.search(r'\b[ABC][12]\+?(?!\w)', text, re.I)
    if language_level:
        return language_level[0]
    match = LEVEL.search(text)
    return match[0] if match else ''


def required_years(text: str) -> float | None:
    match = YEARS.search(text)
    return float(match[1]) if match else None


def family(text: str) -> str:
    for key, pattern in FAMILIES.items():
        if re.search(pattern, text, re.I):
            return key
    return ''


def scoring_key(text: str) -> str:
    """Only equivalent scopes share weight; advanced and combined scopes stay separate."""
    if re.search(FAMILIES['sql'], text, re.I) and not SQL_ADVANCED.search(text) and not YEARS.search(text):
        if not re.search(r'\b(?:python|java|linux|windows|api|and/or|or)\b', text, re.I):
            product = 't_sql' if re.search(r'\b(?:t-sql|transact-sql)\b', text, re.I) else 'sql_server' if re.search(r'\b(?:sql server|ms sql|mssql)\b', text, re.I) else 'sql'
            return product + (':working' if not re.search(r'\badvanced|expert|strong\b', text, re.I) else ':advanced')
    from app.services.job_sections import semantic_key
    return '|'.join(semantic_key(text))


@dataclass
class EvidenceMatch:
    status: Status
    entries: list[FactEntry]
    reason: str
    observed_years: float | None = None

    def legacy_tuple(self):
        return self.status, [e.text for e in self.entries], [e.source_id for e in self.entries], self.reason


def _month(value: str, *, end: bool, as_of: date) -> date | None:
    if re.fullmatch(r'present|current|now|obecnie', value.strip(), re.I):
        return as_of if end else None
    # Year-only dates cannot establish precise tenure; never assume January.
    match = re.fullmatch(r'(\d{4})[-/](\d{1,2})', value.strip())
    if match:
        year, month = int(match[1]), int(match[2])
    else:
        match = re.fullmatch(r'([A-Za-z]+)\s+(\d{4})', value.strip())
        if not match:
            return None
        months = {name.casefold(): i for i in range(1, 13) for name in (calendar.month_abbr[i], calendar.month_name[i])}
        month, year = months.get(match[1].casefold(), 0), int(match[2])
    if not 1 <= month <= 12 or not 1900 <= year <= 2200:
        return None
    if end:
        month, year = (1, year + 1) if month == 12 else (month + 1, year)
    return date(year, month, 1)


class EvidenceMatcher:
    def __init__(self, catalog, bank=None, *, as_of: date | None = None):
        self.catalog, self.bank, self.as_of = catalog, bank, as_of or date.today()
        self.entries = [e for e in catalog.prompt_entries if e.kind != 'interest']
        # A manual verification is an explicit, saved attestation. Its description
        # is evidence, not a license to infer all activities associated with a tool.
        if bank:
            for skill in bank.skills:
                if bank.eligible(skill):
                    for ev in skill.evidence:
                        if ev.source_type == 'manual_verified' and bank.evidence_supports(skill, ev):
                            self.entries.append(FactEntry(ev.source_id, 'verified_skill', f'{skill.name}: {ev.description}', owner_name=skill.name))
        self.entries = list({e.source_id: e for e in self.entries}.values())

    def sources(self, ids: list[str]) -> list[dict[str, str]]:
        lookup = {e.source_id: e for e in self.entries}
        return [dict(source_id=i, type=lookup[i].kind, owner=lookup[i].owner_name, fact=lookup[i].text)
                for i in dict.fromkeys(ids) if i in lookup]

    def _find(self, pattern: str, *, practical=False) -> list[FactEntry]:
        return [e for e in self.entries if re.search(pattern, e.text, re.I) and not NEGATIVE.search(e.text)
                and (not practical or e.kind in {'experience', 'project', 'summary', 'verified_skill'})]

    def _result(self, entries, complete, reason, *, observed=None):
        entries = list({e.source_id: e for e in entries}.values())
        status = Status.STRONG if complete and entries else Status.PARTIAL if entries else Status.MISSING
        if not entries:
            reason = 'No sufficient evidence in the profile; this does not establish a lack of skill. ' + reason
        return EvidenceMatch(status, entries, reason, observed)

    def _qualified(self, name, entries, complete, reason):
        if re.search(r'\b(?:advanced|expert|strong|independen\w*|autonom\w*)\b', name, re.I):
            # Every level/scope modifier must have evidence; a hands-on skill is
            # not advanced proficiency and experience is not proof of autonomy.
            for condition in re.findall(r'\b(?:advanced|expert|strong|independen\w*|autonom\w*)\b', name, re.I):
                declared_advanced = condition.casefold() == 'advanced' and self.bank and any(
                    s.level == 'advanced' and self.bank.eligible(s) and self.bank.mentioned(s, name)
                    for s in self.bank.skills)
                if not declared_advanced and not any(re.search(r'\b' + re.escape(condition) + r'\b', e.text, re.I) for e in entries):
                    complete = False
                    reason += f' Required {condition} scope/level needs confirmation.'
        return self._result(entries, complete, reason)

    def _language(self, name):
        languages = [lang for lang in ('English', 'Polish', 'German', 'French', 'Spanish') if re.search(r'\b' + lang + r'\b', name, re.I)]
        if not languages:
            return None
        entries, confirmations, reasons = [], [], []
        rank = {'A1': 1, 'A2': 2, 'B1': 3, 'B2': 4, 'C1': 5, 'C2': 6, 'NATIVE': 7}
        global_level = re.search(r'\b([ABC][12]\+?|native)(?!\w)', name, re.I)
        for lang in languages:
            sources = [e for e in self._find(r'\b' + lang + r'\b')
                       if re.search(r'\b[ABC][12]\+?|native|daily|professional|communicat\w*|speak\w*|spoken|written', e.text, re.I)
                       or (e.kind == 'skill' and e.text.strip().casefold() == lang.casefold())]
            entries.extend(sources)
            # Resolve the level attached to this language before falling back to
            # a shared trailing qualifier (English & Polish ... B2+).
            local = re.search(r'\b' + lang + r'\s*[-—:]?\s*([ABC][12]\+?|native)(?!\w)', name, re.I)
            required = (local or global_level)[1].upper() if (local or global_level) else ''
            declared = []
            for e in sources:
                m = re.search(r'\b' + lang + r'\s*[-—:]?\s*(?:at\s+)?(?:level\s+)?([ABC][12]\+?|native)(?!\w)', e.text, re.I)
                if m:
                    declared.append(m[1].upper())
                else:
                    reverse = re.search(r'\b(native|[ABC][12]\+?)\s+' + lang + r'\b', e.text, re.I)
                    if reverse:
                        declared.append(reverse[1].upper())
            # Strip '+' only for ranking and then compare it explicitly.
            met = bool(sources) and (not required or any(rank.get(v.rstrip('+'), 0) >= rank.get(required.rstrip('+'), 9)
                and (not required.endswith('+') or v.endswith('+') or rank.get(v.rstrip('+'), 0) > rank.get(required.rstrip('+'), 9)) for v in declared))
            if not required and re.search(r'\badvanced|fluen\w*|fluency\b', name, re.I):
                met = any(rank.get(v.rstrip('+'), 0) >= 5 for v in declared)
            if re.search(r'written.*(?:spoken|verbal|oral)|(?:spoken|verbal|oral).*written', name, re.I):
                met = met and any(re.search(r'written|writing', e.text, re.I) for e in sources) and any(re.search(r'spoken|speaking|verbal|oral', e.text, re.I) for e in sources)
            confirmations.append(met)
            reasons.append(f'{lang}: documented {", ".join(dict.fromkeys(declared)) or "use only"}; required {required or required_level(name) or "language knowledge"}.')
        return self._result(entries, all(confirmations), ' '.join(reasons))

    def _tenure(self, name):
        minimum = required_years(name)
        if minimum is None:
            return None
        support_role = bool(re.search(r'technical support|product support|customer.facing technical|software development', name, re.I))
        intervals, entries = [], []
        for index, exp in enumerate(self.catalog.profile.experience):
            facts = [e for e in self.entries if e.kind == 'experience' and e.owner_index == index and not NEGATIVE.search(e.text)]
            if support_role:
                relevant = [e for e in facts if re.search(r'\b(?:technical|it|user|product|application|l[12]|tier [12]) support\b|(?:support.*(?:users?|applications?|windows|partners?)|(?:developed|built|implemented).*software)', e.text, re.I)]
                scopes = [v for v in ('SaaS', 'TypeScript', 'SAP', 'Kubernetes', 'Azure') if re.search(r'\b' + v + r'\b', name, re.I)]
                if scopes:
                    relevant = [e for e in relevant if all(re.search(r'\b' + v + r'\b', e.text, re.I) for v in scopes)]
            else:
                terms = [v for v in ('Python', 'SQL', 'SAP', 'JavaScript', 'Linux', 'Windows', 'Kubernetes') if re.search(r'\b' + v + r'\b', name, re.I)]
                relevant = [e for e in facts if terms and all(re.search(r'\b' + v + r'\b', e.text, re.I) for v in terms)]
            entries.extend(relevant)
            start, end = _month(exp.start, end=False, as_of=self.as_of), _month(exp.end, end=True, as_of=self.as_of)
            if relevant and start and end and start < min(end, self.as_of):
                intervals.append((start, min(end, self.as_of)))
        merged = []
        for start, end in sorted(intervals):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        observed = sum((end - start).days for start, end in merged) / 365.2425
        reason = f'Dated, relevant employment facts support {observed:.2f} years against minimum {minimum:g}; overlapping periods are counted once. Titles and undated project work are not counted.'
        return self._result(entries, observed >= minimum, reason, observed=round(observed, 2))

    def match(self, name: str, *, alternatives: list[str] | None = None, operator='single') -> EvidenceMatch | None:
        if alternatives:
            branches = [self.match(branch) for branch in alternatives]
            if all(branch is not None for branch in branches):
                if operator == 'any':
                    best = max(branches, key=lambda b: {Status.STRONG: 3, Status.PARTIAL: 2, Status.MISSING: 1, Status.ABSENT: 0}[b.status])
                    return EvidenceMatch(best.status, best.entries, 'OR alternatives: ' + '; '.join(f'{n}: {b.status.value}' for n, b in zip(alternatives, branches, strict=True)) + '. ' + best.reason, best.observed_years)
                complete = all(b.status == Status.STRONG for b in branches)
                if any(b.status == Status.ABSENT for b in branches):
                    return EvidenceMatch(Status.ABSENT, [e for b in branches for e in b.entries], 'An AND condition has an explicitly documented gap; every condition is required.')
                return self._result([e for b in branches for e in b.entries], complete, 'AND requires every condition: ' + '; '.join(f'{n}: {b.status.value}' for n, b in zip(alternatives, branches, strict=True)))
        for e in self.entries:
            if NEGATIVE.search(e.text):
                subject = re.split(NEGATIVE, e.text, maxsplit=1)[-1].strip(' .:')
                subject = re.sub(r'^(?:with|of|in)\s+', '', subject, flags=re.I)
                if subject and re.search(r'(?<!\w)' + re.escape(subject) + r'(?!\w)', name, re.I):
                    return EvidenceMatch(Status.ABSENT, [e], 'The profile explicitly records a lack of this competence.')
        # A technology appearing alongside a language does not become confirmed
        # simply because the language alone is known.
        tenure = self._tenure(name)
        if tenure is not None:
            return tenure
        language = self._language(name)
        if language is not None:
            return language
        key = family(name)
        entries = self._find(FAMILIES[key]) if key else []
        practical = [e for e in entries if e.kind != 'skill' and ':technology:' not in e.source_id]
        if key == 'sql':
            product_pattern = r'\b(?:t-sql|transact-sql)\b' if re.search(r'\b(?:t-sql|transact-sql)\b', name, re.I) else r'\b(?:sql server|ms sql|mssql)\b' if re.search(r'\b(?:sql server|ms sql|mssql)\b', name, re.I) else ''
            if product_pattern:
                specific = [e for e in entries if re.search(product_pattern, e.text, re.I)]
                if not specific:
                    return self._result(entries, False, 'Generic SQL knowledge does not confirm this specific dialect or database product.')
                entries = specific
                practical = [e for e in entries if e.kind != 'skill' and ':technology:' not in e.source_id]
            queries = [e for e in practical if re.search(r'quer\w*|investigat\w*|data verification|operational', e.text, re.I)]
            if SQL_ADVANCED.search(name):
                scoped = [e for e in practical if all(re.search(re.escape(m[0]), e.text, re.I) for m in SQL_ADVANCED.finditer(name))]
                return self._qualified(name, scoped or queries or entries, bool(scoped), 'Operational SQL queries do not establish DBA, tuning or cluster administration scope.')
            needs_practice = bool(re.search(r'working knowledge|investigat\w*|validat\w*|queries|query', name, re.I))
            return self._qualified(name, queries or entries, bool(queries) if needs_practice else bool(entries), 'T-SQL / SQL Server queries support working SQL knowledge; advanced database duties are not inferred.')
        if key == 'api':
            integration = [e for e in practical if re.search(r'integrat\w*|httpx|requests?|endpoints?', e.text, re.I)]
            if API_DEBUG.search(name):
                debugging = [e for e in integration if re.search(r'debug\w*|troubleshoot\w*', e.text, re.I)]
                scope = [term for term in ('requests', 'responses', 'auth', 'payloads', 'status codes', 'OAuth', 'production') if re.search(r'\b' + term + r'\b', name, re.I)]
                complete = bool(debugging) and all(any(re.search(r'\b' + term + r'\b', e.text, re.I) for e in debugging) for term in scope)
                return self._qualified(name, debugging or integration or entries, complete, 'API integration is evidenced; API debugging requires evidence of debugging and each listed scope (auth, payloads, status codes, production).')
            return self._qualified(name, integration or entries, bool(integration), 'Documented REST/HTTP integration supports API integration, without inferring advanced debugging or production ownership.')
        if key in {'javascript', 'typescript'}:
            needs_usage = bool(re.search(r'read|understand.*code|develop\w*|implement\w*', name, re.I))
            return self._qualified(name, practical or entries, bool(practical) if needs_usage else bool(entries), f'{key.title()} evidence is evaluated separately; other programming languages do not prove it.')
        if key == 'ai_tools':
            usage = [e for e in practical if re.search(r'uses?|used|debug\w*|code|development|refactor\w*', e.text, re.I)]
            return self._qualified(name, usage or entries, bool(usage), 'Documented use of AI coding tools supports AI-assisted development; this does not establish AI Engineer experience or measured productivity.')
        if re.search(r'\b(?:read|understand)\b.*\bcode\b', name, re.I):
            code = self._find(r'(?:built|implemented|developed|automated|debugging|code analysis|code review).*(?:python|code|pipeline|application|script)|(?:python|javascript).*(?:pipeline|script|development|implementation)', practical=True)
            return self._qualified(name, code, bool(code), 'Documented implementation/debugging in a programming language supports reading basic code; no TypeScript or advanced software experience is inferred.')
        if re.search(r'tickets?|support cases', name, re.I):
            tickets = self._find(r'tickets?|support cases|technical cases', practical=True)
            ownership = bool(re.search(r'own\w*|end.to.end|intake.*resolution', name, re.I))
            end_to_end = [e for e in tickets if re.search(r'end.to.end|intake.*(?:resolution|clos)|(?:own|manag)\w*.*(?:through|from).*clos', e.text, re.I)]
            return self._qualified(name, end_to_end or tickets, bool(end_to_end) if ownership else bool(tickets), 'Ticket work is evidenced; independent ownership from intake through closure needs an explicit source.' if ownership else 'Documented investigation or handling of tickets supports ticket work.')
        if re.search(r'collaborat\w*.*(?:engineering|product)|(?:engineering|product).*teams?', name, re.I):
            team_names = [v for v in ('Engineering', 'Product') if re.search(r'\b' + v + r'\b', name, re.I)]
            teams = self._find(r'collaborat\w*|escalat\w*', practical=True)
            relevant = [e for e in teams if any(re.search(r'\b' + v + r'\b', e.text, re.I) for v in team_names)]
            complete = all(any(re.search(r'\b' + v + r'\b', e.text, re.I) for e in relevant) for v in team_names)
            return self._qualified(name, relevant, complete, 'Each named team needs documented collaboration; escalation to engineering does not prove Product collaboration.')
        if key == 'communication':
            communication = self._find(r'communicat\w*|explain\w*.*(?:issues?|technical)', practical=True)
            conditions = [v for v in ('written', 'verbal', 'non-technical') if v in name.casefold()]
            complete = bool(communication) and all(any(re.search(re.escape(v), e.text, re.I) for e in communication) for v in conditions)
            return self._qualified(name, communication, complete, 'Professional partner communication is evidenced; written/verbal scope and explaining issues to non-technical audiences require specific evidence.')
        if re.search(r'\bSaaS\b', name, re.I):
            saas = self._find(r'\bSaaS\b', practical=True)
            return self._qualified(name, saas, bool(saas), 'Application support does not by itself establish SaaS product experience.')
        if key in {'troubleshooting', 'support', 'incident', 'documentation'}:
            if key == 'support':
                entries = self._find(r'(?:support\w*.*(?:users?|partners?|application|windows|technical)|(?:technical|it|application|user|l[12]|tier [12]) support)', practical=True)
            if key == 'troubleshooting':
                entries = self._find(r'troubleshoot\w*|investigat\w*.*incidents?|resolv\w*.*(?:incidents?|issues?|problems?)', practical=True)
                scopes = [v for v in ('network', 'Windows', 'Linux', 'application') if re.search(r'\b' + v + r'\b', name, re.I)]
                if scopes and not all(any(re.search(r'\b' + v + r'\b', e.text, re.I) for e in entries) for v in scopes):
                    return self._result(entries, False, 'General troubleshooting evidence does not establish every named system or network scope.')
            if key == 'documentation':
                entries = self._find(r'\bdocumentation|\brunbooks?|knowledge base', practical=False)
            return self._qualified(name, entries, bool(entries), 'Documented activity facts support this capability; titles alone are not evidence of duties or autonomy.')
        # Simple technology branches still support AND/OR without needing a
        # contextual family rule. Longer unrelated conditions use legacy checks.
        if re.fullmatch(r'(?:experience (?:with|in)|knowledge of)?\s*[A-Za-z0-9+#-]+(?:\s+Server)?\.?', name, re.I):
            term = re.sub(r'^(?:experience (?:with|in)|knowledge of)\s+', '', name, flags=re.I).strip(' .')
            simple = self._find(r'(?<!\w)' + re.escape(term) + r'(?!\w)')
            if simple:
                return self._result(simple, True, 'Technology knowledge is documented; a name alone does not verify advanced scope.')
        return None
