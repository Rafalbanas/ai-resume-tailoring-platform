"""Conservative source-backed verification. Semantic ambiguity remains visible.

An LLM may suggest requirements, but cannot establish candidate competence or
silently omit literal requirements from a recognized requirements section.
"""
import re

from app.models.job import JobRequirement, MatchLevel, Recommendation, RequirementPriority, RequirementStatus

MANDATORY_HEAD = re.compile(r'^(?:.*?requirements\s*:|.*?wymagania.*|.*?what you bring.*|(?:we are looking for|what we are looking for)(?: you,? if you have)?\s*:?|.*?your profile.*|.*?qualifications.*|.*?must have.*|.*?nasze oczekiwania.*|.*?you bring.*)$', re.I)
PREFERRED_HEAD = re.compile(r'^(?:.*?nice.to.have.*|.*?mile widziane.*|.*?preferred qualifications.*|.*?optional.*)$', re.I)
END_HEAD = re.compile(r'^(?:.*?we offer.*|.*?oferujemy.*|.*?benefits.*|.*?tech stack.*|.*?responsibilities.*|.*?what you.ll.*)$', re.I)
INJECTION = re.compile(r'ignore.*instructions|system prompt|you are chatgpt|return.*json|mark.*(?:strong|apply)|reveal.*(?:secret|key)', re.I)


def source_lines(job_text):
    section = None
    lines = []
    for raw in job_text.splitlines():
        text = raw.strip().strip('•*- ').strip()
        if not text:
            continue
        if PREFERRED_HEAD.fullmatch(text) and len(text) < 100:
            section = RequirementPriority.PREFERRED
            continue
        if END_HEAD.fullmatch(text) and len(text) < 100:
            section = None
            continue
        if MANDATORY_HEAD.fullmatch(text) and len(text) < 100:
            section = RequirementPriority.MANDATORY
            continue
        if section and not INJECTION.search(text) and len(text) >= 2:
            lines.append((text, section))
    return lines


def boundary_contains(needle, text):
    return bool(re.search(r'(?<![\w])' + re.escape(needle.casefold()) + r'(?![\w])', text.casefold()))


def verify_requirement(validator, name):
    catalog, bank = validator.catalog, validator.skills_bank
    cf = name.casefold()
    evidence, ids, hits = [], [], []
    if bank:
        for skill in bank.skills:
            # Unix is related to Linux
            # Neither proves all Unix systems.
            aliases = [a for a in bank.aliases_for(skill) if a.casefold() not in {'unix', 'fortinet', 'containers', 'ad', 'ml'}]
            if not any(boundary_contains(a, name) for a in aliases):
                continue
            if bank.eligible(skill):
                hits.append(skill)
                evidence.extend(bank.evidence_labels(skill))
                ids.extend(e.source_id for e in skill.evidence if catalog.get(e.source_id))
    else:
        for entry in catalog.prompt_entries:
            if entry.kind == 'skill' and boundary_contains(entry.text.replace(' (basic)', ''), name):
                ids.append(entry.source_id)
                evidence.append(entry.text)
    degree = validator._matches_cs_education(name)
    if not degree[0] and re.search(r"higher education|wykształcenie wyższe|^bachelor(?:'s)? degree[.,]?$", cf):
        entry = next((e for e in catalog.prompt_entries if e.kind == "education" and re.search(r"msc|bachelor|master", e.text, re.I)), None)
        if entry:
            degree = (True, entry.text, [entry.source_id])
    if degree[0] and not re.search(r'ph\.?d|doctor|doktor', cf):
        evidence.append(degree[1])
        ids.extend(degree[2])
    crm = validator._matches_crm(name)
    if crm[0]:
        evidence.extend(catalog.get(i).text for i in crm[2] if catalog.get(i))
        ids.extend(crm[2])
    # Whole exact claims can be confirmed
    # Word similarity cannot confirm
    # seniority, scope, conjunctions, or a proficiency level.
    direct = catalog.direct_sources(name)
    ids.extend(direct)
    evidence.extend(catalog.get(i).text for i in direct)
    partial = bool(ids or evidence)
    status = RequirementStatus.PARTIAL if partial else RequirementStatus.MISSING
    reason = 'Dowody dotyczą części wymagania; poziom, zakres i pozostałe warunki wymagają sprawdzenia.' if partial else 'Brak potwierdzenia w profilu; nie oznacza to braku umiejętności.'
    exact_skill = bank.find(name) if bank else None
    if direct or (exact_skill and bank.eligible(exact_skill) and exact_skill.level != 'basic'):
        status = RequirementStatus.STRONG
        reason = 'Potwierdzone w źródłach profilu.'
    # OR is recognized only for explicit alternatives
    # Slash alone is ambiguous
    # (TCP/IP, CI/CD, AND/OR). Branch evidence does not prove a shared qualifier.
    or_match = validator._matches_or_alternatives(name) if re.search(r'\bor\b|\band/or\b', cf) else (False, '', [])
    constrained = bool(re.search(r'\d+\s*\+?\s*(?:years?|lat)|\b(?:advanced|expert|senior|strong|c1|c2|native|fluent)\b', cf))
    if or_match[0] and not constrained and not re.search(r'\band\b(?!/or)', cf):
        status = RequirementStatus.STRONG
        evidence.append('Potwierdzona alternatywa: ' + or_match[1])
        ids.extend(or_match[2])
    parts = re.split(r'\s+and\s+', name, flags=re.I)
    if len(parts) > 1 and not constrained:
        if all(catalog.direct_sources(p.strip(' .')) or (bank and (sk := bank.find(p.strip(' .'))) and bank.eligible(sk) and sk.level != 'basic') for p in parts):
            status = RequirementStatus.STRONG
    if degree[0] and not re.search(r'\band\b|ph\.?d|doctor|doktor', cf):
        status = RequirementStatus.STRONG
    # An explicit minimum B2 is supported by declared B2; daily use is not C1.
    if re.search(r'\benglish\b', cf) and not re.search(r'\band\b|\bc[12]\b|native|fluent', cf):
        language_sources = [e for e in catalog.prompt_entries if e.kind == 'skill' and 'english' in e.text.casefold()]
        if re.search(r'\bb[12]\b', cf) and any('b2' in e.text.casefold() for e in language_sources):
            status = RequirementStatus.STRONG
            evidence.extend(e.text for e in language_sources)
            ids.extend(e.source_id for e in language_sources)
            reason = 'Wymagany poziom języka potwierdzony w profilu.'
        elif language_sources:
            status = RequirementStatus.PARTIAL
            evidence.extend(e.text for e in language_sources)
            ids.extend(e.source_id for e in language_sources)
            reason = 'Profil potwierdza B2 i używanie angielskiego; jakościowy poziom z oferty wymaga oceny.'
    # All conjunctions must be satisfied. CRM does not prove KCS.
    if re.search(r'\bkcs\b|\bsap\b|\bc1\b|\bc2\b|\bph\.?d\b|\bdoctor', cf):
        if not catalog.direct_sources(name):
            status = RequirementStatus.PARTIAL if partial else RequirementStatus.MISSING
            reason = 'Niepotwierdzony kluczowy warunek (np. KCS/SAP, poziom języka lub stopień naukowy); patrz cytat.'
    if constrained and not direct:
        status = RequirementStatus.PARTIAL if partial else RequirementStatus.MISSING
        reason = 'Niepotwierdzony wymagany poziom lub staż w tej konkretnej roli; sama znajomość technologii nie wystarcza.'
    if re.search(r'hybrid|office|relocat|on.site|on.call|shift|travel|remote|lokaliz|wrocław|warszawa', cf):
        status = RequirementStatus.PARTIAL if partial else RequirementStatus.MISSING
        reason = 'Dostępność, lokalizacja i tryb pracy wymagają osobistego potwierdzenia.'
    return status, list(dict.fromkeys(evidence)), list(dict.fromkeys(ids)), reason


def validate_grounded(validator, candidate, job_text):
    result = candidate.model_copy(deep=True)
    source = source_lines(job_text)
    suggestions = candidate.strong_matches + candidate.partial_matches + candidate.missing_requirements
    suggestions += [r.name for r in candidate.requirements]
    # Use model phrasing only if it occurs verbatim in the job
    # Otherwise prefer
    # an exact supplied quote, preserving all modifiers from that quote.
    if not source:
        for claim in suggestions:
            if validator._is_candidate_only_fact(claim, job_text) or INJECTION.search(claim):
                continue
            if boundary_contains(claim, job_text):
                source.append((claim, RequirementPriority.MANDATORY))
            elif not re.search(r"(?:skill|summary|experience|project|education):|^skill_|^[a-f0-9]{12,64}$", claim):
                from app.services.analysis_validator import extract_source_quote
                quote = extract_source_quote(claim, job_text)
                if quote and quote in job_text and not INJECTION.search(quote):
                    source.append((quote, RequirementPriority.MANDATORY))
        for req in candidate.requirements:
            if req.source_quote and req.source_quote in job_text and not INJECTION.search(req.source_quote):
                source.append((req.source_quote, req.priority))
    # Location outside the requirement section is still a real constraint.
    job_lines = job_text.splitlines()
    for index, raw in enumerate(job_lines):
        if re.fullmatch(r'\s*(?:B[12]|C[12]|Advanced|Expert|Intermediate|Basic)\s*', raw, re.I) and index:
            previous = job_lines[index-1].strip()
            if previous:
                source.append((previous + '\n' + raw.strip(), RequirementPriority.MANDATORY))
        elif re.search(r'hybrid.*(?:office|days)|(?:days|dni).*office|on.site|\bc[12]\b', raw, re.I) and raw.strip():
            source.append((raw.strip(), RequirementPriority.MANDATORY))
    seen, requirements, sources = set(), [], {}
    for name, priority in source:
        if name.casefold() in seen or re.search(r'(?:skill|summary|experience|project|education):|\b[a-f0-9]{12,64}\b', name):
            continue
        seen.add(name.casefold())
        if re.search(r'^(?:preferred|nice.to.have|mile widziane|optional)\b|valued, not required', name, re.I):
            priority = RequirementPriority.PREFERRED
        status, evidence, ids, reason = verify_requirement(validator, name)
        requirements.append(JobRequirement(id=f'req_{len(requirements)+1}', name=name, source_quote=name, priority=priority, status=status, evidence=evidence, reason=reason))
        sources[name] = ids
    result.requirements = requirements
    result.strong_matches = [r.name for r in requirements if r.status == RequirementStatus.STRONG]
    result.partial_matches = [r.name for r in requirements if r.status == RequirementStatus.PARTIAL]
    result.missing_requirements = [r.name for r in requirements if r.status == RequirementStatus.MISSING]
    result.match_sources = sources
    result.match_evidence = {r.name:r.evidence for r in requirements}
    result.strong_skill_ids = []
    result.partial_skill_ids = []
    result.learning_skill_ids = []
    result.learning_matches = []
    result.supported_keywords = [k for k in candidate.supported_keywords if boundary_contains(k, job_text) and validator.catalog.direct_sources(k)]
    result.unsupported_keywords = [k for k in candidate.unsupported_keywords if boundary_contains(k, job_text) and not validator.catalog.direct_sources(k)]
    visibly_truncated = bool(re.search(r"\b(?:and|or|i|oraz)\s*$", job_text.strip(), re.I))
    result.is_reliable = bool(requirements) and not visibly_truncated
    if not result.is_reliable:
        result.match_level, result.recommendation = MatchLevel.UNRELIABLE, Recommendation.RETRY
        result.reasoning_summary = ('Analiza niewiarygodna — ogłoszenie urywa się w połowie zdania. Wklej kompletną treść.' if visibly_truncated else 'Analiza niewiarygodna — brak wymagań z potwierdzonym źródłem. Wymaga ponowienia.')
        return result
    weights = {RequirementPriority.MANDATORY: 3, RequirementPriority.PREFERRED: 1, RequirementPriority.NICE_TO_HAVE: 1}
    score = sum(weights[r.priority] * {RequirementStatus.STRONG:1, RequirementStatus.PARTIAL:0.5, RequirementStatus.MISSING:0}[r.status] for r in requirements) / sum(weights[r.priority] for r in requirements)
    blockers = [r for r in requirements if r.priority == RequirementPriority.MANDATORY and r.status != RequirementStatus.STRONG]
    if score >= .7 and not blockers:
        result.match_level, result.recommendation = MatchLevel.HIGH, Recommendation.APPLY
    elif score >= .4:
        result.match_level, result.recommendation = MatchLevel.MEDIUM, Recommendation.REASONABLE_STRETCH
    else:
        result.match_level, result.recommendation = MatchLevel.LOW, Recommendation.SKIP
    critical = [r for r in blockers if re.search(r'\d+\+?\s*years|\bc[12]\b|\bsap\b', r.name, re.I)]
    if critical:
        result.match_level, result.recommendation = MatchLevel.LOW, Recommendation.SKIP
    result.reasoning_summary = f'Weryfikacja źródłowa: {len(result.strong_matches)} potwierdzonych, {len(result.partial_matches)} częściowych, {len(result.missing_requirements)} bez potwierdzenia. Niespełnione lub niepotwierdzone obowiązkowe warunki: {len(blockers)}. To wskazówka do przeglądu, nie prawdopodobieństwo zatrudnienia ani wynik ATS. Sprawdź pełne cytaty, dostępność i poziomy kompetencji przed aplikowaniem.'
    return result
