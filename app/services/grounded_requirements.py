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
    from app.services.job_sections import extract_sections
    units, _ = extract_sections(job_text)
    return [(u.name, RequirementPriority(u.category)) for u in units if u.category in {"mandatory", "preferred"}]


def boundary_contains(needle, text):
    return bool(re.search(r'(?<![\w])' + re.escape(needle.casefold()) + r'(?![\w])', text.casefold()))


def verify_requirement(validator, name):
    catalog, bank = validator.catalog, validator.skills_bank
    # Optional modifiers remain in the source quote, but cannot strengthen a blocker.
    name = re.split(r",\s*preferably\b", name, maxsplit=1, flags=re.I)[0]
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
    if crm[0] and not re.search(r'\bkcs\b', cf):
        crm_confirmed = True
    else:
        crm_confirmed = False
    # Whole exact claims can be confirmed
    # Word similarity cannot confirm
    # seniority, scope, conjunctions, or a proficiency level.
    direct = catalog.direct_sources(name)
    ids.extend(direct)
    evidence.extend(catalog.get(i).text for i in direct)
    partial = bool(ids or evidence)
    status = RequirementStatus.PARTIAL if partial else RequirementStatus.MISSING
    reason = 'Evidence supports part of this requirement; verify its level, scope and remaining conditions.' if partial else 'Not confirmed in profile; this does not establish a lack of skill.'
    exact_skill = bank.find(name) if bank else None
    if crm_confirmed or direct or (exact_skill and bank.eligible(exact_skill) and exact_skill.level != 'basic'):
        status = RequirementStatus.STRONG
        reason = 'Confirmed in profile sources.'
    # OR is recognized only for explicit alternatives
    # Slash alone is ambiguous
    # (TCP/IP, CI/CD, AND/OR). Branch evidence does not prove a shared qualifier.
    or_match = validator._matches_or_alternatives(name) if re.search(r'\bor\b|\band/or\b', cf) else (False, '', [])
    constrained = bool(re.search(r'\d+\s*\+?\s*(?:years?|lat)|\b(?:advanced|expert|senior|strong|c1|c2|native|fluen\w*)\b', cf))
    if or_match[0] and re.search(r'install|configur|troubleshoot', cf):
        qualified = [i for i in or_match[2] if catalog.get(i) and re.search(r'install|configur|troubleshoot', catalog.get(i).text, re.I)]
        if not qualified:
            or_match = (False, "", [])
    if or_match[0] and not constrained and not re.search(r'\band\b(?!/or)', cf):
        status = RequirementStatus.STRONG
        evidence.append('Confirmed alternative: ' + or_match[1])
        ids.extend(or_match[2])
    # "Such as" introduces examples; any independently evidenced example suffices.
    example_parts = re.split(r'\bsuch as\b|\bfor example\b', name, maxsplit=1, flags=re.I)
    if len(example_parts) == 2 and not constrained:
        alternatives = re.split(r',\s*|\s+or\s+', example_parts[1].strip(' .'), flags=re.I)
        for alternative in alternatives:
            example_ids = catalog.direct_sources(alternative.strip(' .'))
            if example_ids:
                status = RequirementStatus.STRONG
                ids.extend(example_ids)
                evidence.extend(catalog.get(i).text for i in example_ids)
                reason = 'A source example is confirmed; the examples are not cumulative requirements.'
                break
    parts = re.split(r'\s+and\s+', name, flags=re.I)
    if len(parts) > 1 and not constrained:
        if all(catalog.direct_sources(p.strip(' .')) or (bank and (sk := bank.find(p.strip(' .'))) and bank.eligible(sk) and sk.level != 'basic') for p in parts):
            status = RequirementStatus.STRONG
    if degree[0] and not re.search(r'\band\b|ph\.?d|doctor|doktor', cf):
        status = RequirementStatus.STRONG
    # An explicit minimum B2 is supported by declared B2; daily use is not C1.
    if re.search(r'\benglish\b', cf):
        language_sources = [e for e in catalog.prompt_entries if 'english' in e.text.casefold() and re.search(r'\bb[12]\b|daily|every day|language', e.text, re.I)]
        if re.search(r'\bb[12]\b', cf) and not constrained and any('b2' in e.text.casefold() for e in language_sources):
            status = RequirementStatus.STRONG
            evidence.extend(e.text for e in language_sources)
            ids.extend(e.source_id for e in language_sources)
            reason = 'Required language level confirmed in profile.'
        elif language_sources:
            status = RequirementStatus.PARTIAL
            evidence.extend(e.text for e in language_sources)
            ids.extend(e.source_id for e in language_sources)
            reason = 'The profile confirms B2 and English usage; the required proficiency needs review.'
    partial = bool(ids or evidence)
    # All conjunctions must be satisfied. CRM does not prove KCS.
    if re.search(r'\bkcs\b|\bsap\b|\bc1\b|\bc2\b|\bph\.?d\b|\bdoctor', cf):
        if not catalog.direct_sources(name):
            status = RequirementStatus.PARTIAL if partial else RequirementStatus.MISSING
            reason = 'An essential condition is not confirmed (methodology, language level or degree); review the source quote.'
    if constrained and not direct:
        status = RequirementStatus.PARTIAL if partial else RequirementStatus.MISSING
        reason = 'Required proficiency or tenure in this role is not confirmed; familiarity with a technology alone is insufficient.'
    if re.search(r'hybrid|office|relocat|on.site|on.call|shift|travel|remote|lokaliz|wrocław|warszawa', cf):
        status = RequirementStatus.PARTIAL if partial else RequirementStatus.MISSING
        reason = 'Availability, location and working arrangements require personal confirmation.'
    for entry in catalog.prompt_entries:
        negative = re.search(r"(?:no (?:prior )?(?:experience|knowledge) (?:with|of|in)|never (?:used|worked with)|have not used)\s+([A-Za-z0-9 +#./-]+)", entry.text, re.I)
        if negative and boundary_contains(negative.group(1).strip(' .'), name):
            status = RequirementStatus.ABSENT
            evidence.append(entry.text)
            ids.append(entry.source_id)
            reason = "The profile explicitly records a lack of experience with this requirement."
    return status, list(dict.fromkeys(evidence)), list(dict.fromkeys(ids)), reason


def validate_grounded(validator, candidate, job_text):
    result = candidate.model_copy(deep=True)
    from app.services.job_sections import ORGANIZATION_SIGNAL, REQUIREMENT_SIGNAL, extract_sections
    units, sections = extract_sections(job_text)
    source = source_lines(job_text)
    result.source_sections = sections
    result.analysis_language = "en"
    result.responsibilities = [{"name": u.name, "source_quote": u.quote, "classification_basis": u.basis} for u in units if u.category == "responsibility"]
    result.organization_context = [{"name": u.name, "source_quote": u.quote, "classification_basis": u.basis} for u in units if u.category == "organization"]
    unit_by_name = {u.name: u for u in units if u.category in {"mandatory", "preferred"}}
    result.completeness_issues = []
    suggestions = candidate.strong_matches + candidate.partial_matches + candidate.missing_requirements
    suggestions += [r.name for r in candidate.requirements]
    # Use model phrasing only if it occurs verbatim in the job
    # Otherwise prefer
    # an exact supplied quote, preserving all modifiers from that quote.
    if not source:
        for claim in suggestions:
            if validator._is_candidate_only_fact(claim, job_text) or INJECTION.search(claim) or ORGANIZATION_SIGNAL.search(claim):
                continue
            if boundary_contains(claim, job_text):
                source.append((claim, RequirementPriority.MANDATORY))
            elif not re.search(r"(?:skill|summary|experience|project|education):|^skill_|^[a-f0-9]{12,64}$", claim):
                from app.services.analysis_validator import extract_source_quote
                quote = extract_source_quote(claim, job_text)
                if quote and quote in job_text and not INJECTION.search(quote) and not ORGANIZATION_SIGNAL.search(quote):
                    source.append((quote, RequirementPriority.MANDATORY))
        for req in candidate.requirements:
            if req.source_quote and req.source_quote in job_text and not INJECTION.search(req.source_quote) and not ORGANIZATION_SIGNAL.search(req.source_quote):
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
        unit = unit_by_name.get(name)
        requirements.append(JobRequirement(classification_basis=unit.basis if unit else "Literal requirement in source; section not identified", source_section=unit.section if unit else "Unsectioned source", group_id=unit.group if unit else f"source_{len(requirements)+1}", id=f'req_{len(requirements)+1}', name=name, source_quote=unit.quote if unit else name, priority=priority, status=status, evidence=evidence, reason=reason))
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
    expected = {u.name for u in units if u.category in {"mandatory", "preferred"}}
    omitted = expected - {r.name for r in requirements}
    if omitted:
        result.completeness_issues.append("Some source requirements were not assessed.")
    # Cover source passages even when some headings were successfully recognized.
    # Organization context and duties are represented separately, not scored.
    covered_quotes = [u.quote for u in units] + [r.source_quote for r in requirements]
    uncovered = [line.strip() for line in job_text.splitlines()
                 if REQUIREMENT_SIGNAL.search(line) and not ORGANIZATION_SIGNAL.search(line)
                 and line.strip().rstrip(':') not in sections
                 and not re.search(r'knowledge with:\s*$', line, re.I)
                 and not any(quote in line or line.strip() in quote for quote in covered_quotes)]
    if uncovered:
        result.completeness_issues.append("Requirement-bearing source passages are not covered by the analysis.")
    if sections and not source:
        result.completeness_issues.append("No candidate requirements were identified in the recognized source sections.")
    if visibly_truncated:
        result.completeness_issues.append("The source ends in an unfinished sentence.")
    result.is_reliable = bool(requirements) and not result.completeness_issues
    result.requirement_counts = {"mandatory": sum(r.priority == RequirementPriority.MANDATORY for r in requirements),
                                 "preferred": sum(r.priority != RequirementPriority.MANDATORY for r in requirements),
                                 "confirmed": len(result.strong_matches), "partial": len(result.partial_matches),
                                 "not_confirmed": len(result.missing_requirements),
                                 "confirmed_absence": sum(r.status == RequirementStatus.ABSENT for r in requirements)}
    if not result.is_reliable:
        result.match_level, result.recommendation = MatchLevel.UNRELIABLE, Recommendation.RETRY
        result.reasoning_summary = "Incomplete analysis — review required. " + " ".join(result.completeness_issues or ["No requirements with a verifiable source were identified."])
        return result
    # Score each source requirement once, even when independent clauses are displayed separately.
    mandatory = [r for r in requirements if r.priority == RequirementPriority.MANDATORY]
    groups = {}
    for r in mandatory or requirements:
        groups.setdefault(r.group_id, []).append({RequirementStatus.STRONG: 1, RequirementStatus.PARTIAL: .5, RequirementStatus.MISSING: 0, RequirementStatus.ABSENT: 0}[r.status])
    score = sum(sum(values)/len(values) for values in groups.values()) / len(groups)
    blockers = [r for r in mandatory if r.status != RequirementStatus.STRONG]
    if score >= .7 and not blockers:
        result.match_level, result.recommendation = MatchLevel.HIGH, Recommendation.APPLY
    elif score >= .4:
        result.match_level, result.recommendation = MatchLevel.MEDIUM, Recommendation.REASONABLE_STRETCH
    else:
        # Silence in the profile is not a confirmed inability or an automatic rejection.
        result.match_level = MatchLevel.LOW
        result.recommendation = Recommendation.SKIP if any(r.status == RequirementStatus.ABSENT for r in mandatory) else Recommendation.REASONABLE_STRETCH
    result.reasoning_summary = f"Source review: {len(result.strong_matches)} confirmed, {len(result.partial_matches)} partial matches, {len(result.missing_requirements)} not confirmed in the profile. Mandatory conditions requiring review: {len(blockers)}. Preferred requirements are shown separately and do not create mandatory blockers. This evaluates documented evidence, not hiring probability or an ATS score."
    return result
