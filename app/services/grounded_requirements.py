"""Conservative source-backed verification. Semantic ambiguity remains visible.

An LLM may suggest requirements, but cannot establish candidate competence or
silently omit literal requirements from a recognized requirements section.
"""
import re

from app.models.job import JobRequirement, MatchLevel, Recommendation, RequirementPriority, RequirementStatus
from app.services.evidence_matching import required_level, required_years, scoring_key
from app.services.fact_catalog import normalized_tokens

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


def verify_requirement(validator, name, unit=None):
    contextual = validator.matcher.match(name, alternatives=unit.alternatives if unit else None,
                                         operator=unit.operator if unit else 'single')
    if contextual is not None:
        if unit and unit.operator == 'all' and not unit.alternatives:
            names = list(dict.fromkeys(re.findall(r'(?<![\w-])(?:JavaScript|TypeScript|Python|PowerShell|Bash|SQL|APIs?|Kubernetes|Azure|Terraform|Docker|SaaS)(?![\w-])', name, re.I)))
            if len(names) > 1:
                branch_results = [verify_requirement(validator, part) for part in names]
                if any(branch[0] != RequirementStatus.STRONG for branch in branch_results):
                    contextual.status = RequirementStatus.PARTIAL if contextual.entries or any(b[1] for b in branch_results) else RequirementStatus.MISSING
                    contextual.reason += ' Every named technology is required: ' + '; '.join(f'{part}: {b[0].value}' for part, b in zip(names, branch_results, strict=True)) + '.'
                elif contextual.status == RequirementStatus.STRONG and not validator.catalog.direct_sources(name):
                    contextual.status = RequirementStatus.PARTIAL
                    contextual.reason += ' The distinct action scopes in this combined technical condition need confirmation.'
        if unit and unit.uncertain and contextual.status == RequirementStatus.STRONG:
            contextual.status = RequirementStatus.PARTIAL
            contextual.reason += ' The combined source condition needs interpretation; verify every scope in the original quote.'
        return contextual.legacy_tuple()
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
                ids.extend(e.source_id for e in skill.evidence if catalog.get(e.source_id) and bank.evidence_supports(skill, e))
    else:
        for entry in catalog.prompt_entries:
            if entry.kind == 'skill' and boundary_contains(entry.text.replace(' (basic)', ''), name):
                ids.append(entry.source_id)
                evidence.append(entry.text)
    # Semantic equivalents must resolve to existing content facts, never job titles.
    semantic_patterns = {
        'customer support': r'(?:(?:support|assist|help)\w*.*(?:customers?|partners?|users?)|(?:customers?|partners?|users?).*support)',
        'customer service': r'(?:(?:support|assist|help)\w*.*(?:customers?|partners?|users?)|(?:customers?|partners?|users?).*support)',
        'problem solving': r'troubleshoot\w*|resolv\w*.*(?:incidents?|issues?|problems?)',
        'troubleshooting': r'troubleshoot\w*|resolv\w*.*(?:incidents?|issues?|problems?)',
        'incident management': r'(?:handl|manag|resolv)\w*.*incidents?|incident.*(?:handl|manag|resolv)',
        'it support': r'(?:technical|it|user|partner|customer).*support|support.*(?:technical|users?|partners?|customers?)',
    }
    semantic_ids = []
    semantic_name = re.sub(r"^(?:(?:experience|knowledge|skills?|ability)\s+(?:in|with|of|to)\s+)", "", cf.strip(' .'))
    semantic_name = re.sub(r"\s+(?:experience|skills?|knowledge)$", "", semantic_name)
    if semantic_name in semantic_patterns:
        for entry in catalog.prompt_entries:
            if entry.kind == 'experience' and ':fact:' in entry.source_id and re.search(semantic_patterns[semantic_name], entry.text, re.I) and not re.search(r'\b(?:no|never|not)\b', entry.text, re.I):
                semantic_ids.append(entry.source_id)
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
    # General CRM evidence does not prove an extra product, methodology, level
    # or configuration condition. Keep every additional condition visible.
    crm_scope = normalized_tokens(name) - {
        "crm", "system", "systems", "platform", "platforms", "software", "tools",
        "experience", "knowledge", "familiarity", "understanding", "using", "working",
    }
    crm_confirmed = crm[0] and not crm_scope
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
    if semantic_ids or crm_confirmed or direct or (exact_skill and bank.eligible(exact_skill) and exact_skill.level != 'basic'):
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
    from app.services.job_sections import (
        ORGANIZATION_SIGNAL,
        REQUIREMENT_SIGNAL,
        extract_sections,
        role_competency_units,
        semantic_key,
    )
    units, sections = extract_sections(job_text)
    source = source_lines(job_text)
    result.source_sections = sections
    result.analysis_language = "en"
    result.responsibilities = [{"name": u.name, "source_quote": u.quote, "classification_basis": u.basis} for u in units if u.category == "responsibility"]
    # Responsibility overlap is indicative, not proof of the full duty or an
    # implicit prerequisite. Only content facts can support these scope notes.
    for duty in result.responsibilities:
        tokens = normalized_tokens(duty["name"]) - {"support", "work", "using", "customer", "service"}
        facts = [e for e in validator.catalog.prompt_entries
                 if e.kind == 'experience' and ':fact:' in e.source_id
                 and len(tokens & normalized_tokens(e.text)) >= 2
                 and not re.search(r'\b(?:no|never|not)\b', e.text, re.I)]
        duty["evidence"] = "; ".join(e.text for e in facts)
        duty["status"] = "partial" if facts else "missing"
        duty["reason"] = "Related documented experience; full duty scope needs review." if facts else "Not confirmed in profile; not a mandatory blocker."
    result.organization_context = [{"name": u.name, "source_quote": u.quote, "classification_basis": u.basis} for u in units if u.category == "organization"]
    result.role_competencies = []
    for unit in role_competency_units(units):
        if unit.category == "competency":
            match_name = unit.name + ' ' + unit.level if unit.level and not boundary_contains(unit.level, unit.name) else unit.name
            status, evidence, ids, reason = verify_requirement(validator, match_name, unit)
            result.role_competencies.append(JobRequirement(name=unit.name, source_quote=unit.quote, source_quotes=[unit.quote, *unit.supporting_quotes], required_level=unit.level, source_section=unit.section, classification_basis="Role skill or portal tag; employer priority unspecified. Excluded from mandatory scoring; any listed proficiency requires separate verification", priority=RequirementPriority.UNSPECIFIED, status=status, evidence=evidence, source_fact_ids=ids, evidence_sources=validator.matcher.sources(ids), reason=reason))
    unit_by_name = {u.name: u for u in units if u.category in {"mandatory", "preferred"}}
    result.completeness_issues = []
    suggestions = candidate.strong_matches + candidate.partial_matches + candidate.missing_requirements
    suggestions += [r.name for r in candidate.requirements]
    # Use model phrasing only if it occurs verbatim in the job
    # Otherwise prefer
    # an exact supplied quote, preserving all modifiers from that quote.
    if not source and not sections:
        for claim in suggestions:
            if validator._is_candidate_only_fact(claim, job_text) or INJECTION.search(claim) or ORGANIZATION_SIGNAL.search(claim):
                continue
            if boundary_contains(claim, job_text) and REQUIREMENT_SIGNAL.search(claim):
                source.append((claim, RequirementPriority.MANDATORY))
            elif not re.search(r"(?:skill|summary|experience|project|education):|^skill_|^[a-f0-9]{12,64}$", claim):
                from app.services.analysis_validator import extract_source_quote
                quote = extract_source_quote(claim, job_text)
                if quote and REQUIREMENT_SIGNAL.search(quote) and quote in job_text and not INJECTION.search(quote) and not ORGANIZATION_SIGNAL.search(quote):
                    source.append((quote, RequirementPriority.MANDATORY))
        for req in candidate.requirements:
            if req.source_quote and REQUIREMENT_SIGNAL.search(req.source_quote) and req.source_quote in job_text and not INJECTION.search(req.source_quote) and not ORGANIZATION_SIGNAL.search(req.source_quote):
                source.append((req.source_quote, req.priority))
    # Location outside the requirement section is still a real constraint.
    job_lines = job_text.splitlines()
    for index, raw in enumerate(job_lines):
        if any(u.category in {"responsibility", "organization", "preferred", "competency"}
               and (raw.strip() == u.quote or raw.strip() in u.supporting_quotes) for u in units):
            continue
        if re.fullmatch(r'\s*(?:B[12]|C[12]|Advanced|Expert|Intermediate|Basic)\s*', raw, re.I) and index and not any(u.level == raw.strip() and u.name == job_lines[index-1].strip() for u in units):
            previous = job_lines[index-1].strip()
            if previous:
                source.append((previous + '\n' + raw.strip(), RequirementPriority.MANDATORY))
        elif re.search(r'hybrid.*(?:office|days)|(?:days|dni).*office|on.site|\bc[12]\b', raw, re.I) and raw.strip():
            source.append((raw.strip(), RequirementPriority.MANDATORY))
    seen, requirements, sources = {}, [], {}
    for name, priority in source:
        key = (priority, semantic_key(name))
        if key in seen:
            existing = seen[key]
            existing.source_quotes.append(unit_by_name[name].quote if name in unit_by_name else name)
            continue
        if re.search(r'(?:skill|summary|experience|project|education):|\b[a-f0-9]{12,64}\b', name):
            continue
        if INJECTION.search(name):
            continue
        if re.search(r'^(?:preferred|nice.to.have|mile widziane|optional)\b|valued, not required', name, re.I):
            priority = RequirementPriority.PREFERRED
        unit = unit_by_name.get(name)
        status, evidence, ids, reason = verify_requirement(validator, name, unit)
        requirements.append(JobRequirement(classification_basis=unit.basis if unit else "Literal requirement in source; section not identified", source_section=unit.section if unit else "Unsectioned source", group_id=unit.group if unit else f"source_{len(requirements)+1}", id=f'req_{len(requirements)+1}', name=name, source_quote=unit.quote if unit else name, priority=priority, status=status, evidence=evidence, source_fact_ids=ids, reason=reason))
        requirements[-1].source_quotes = [requirements[-1].source_quote]
        requirement = requirements[-1]
        requirement.required_level = unit.level if unit and unit.level else required_level(name)
        requirement.required_years = required_years(name)
        requirement.operator = unit.operator if unit else 'single'
        requirement.alternatives = unit.alternatives if unit else []
        requirement.accepted_alternatives = unit.accepted_alternatives if unit else []
        requirement.interpretation_uncertain = bool(unit and unit.uncertain)
        requirement.evidence_sources = validator.matcher.sources(ids)
        requirement.scoring_key = scoring_key(name)
        if requirement.required_years is not None:
            tenure = validator.matcher.match(name, alternatives=unit.alternatives if unit else None,
                                            operator=unit.operator if unit else 'single')
            requirement.observed_years = tenure.observed_years if tenure else None
        if status != RequirementStatus.STRONG or requirement.interpretation_uncertain:
            requirement.clarification_needed = reason
        seen[key] = requirements[-1]
        sources[name] = ids
    result.requirements = requirements
    scoring_seen = {}
    for req in requirements:
        key = (req.priority, req.scoring_key)
        if key in scoring_seen:
            req.duplicate_of = scoring_seen[key].id
        else:
            scoring_seen[key] = req
    result.profile_clarifications = [r.name + ': ' + r.clarification_needed for r in requirements if r.clarification_needed]
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
    omitted = {semantic_key(n) for n in expected} - {semantic_key(r.name) for r in requirements}
    if omitted:
        result.completeness_issues.append("Some source requirements were not assessed.")
    # Cover source passages even when some headings were successfully recognized.
    # Organization context and duties are represented separately, not scored.
    covered_quotes = [u.quote for u in units] + [r.source_quote for r in requirements]
    uncovered = [line.strip() for line in job_text.splitlines()
                 if REQUIREMENT_SIGNAL.search(line) and not ORGANIZATION_SIGNAL.search(line) and not INJECTION.search(line)
                 and line.strip().rstrip(':') not in sections
                 and not re.search(r'knowledge with:\s*$', line, re.I)
                 and not any(quote in line or line.strip() in quote for quote in covered_quotes)]
    if uncovered:
        result.completeness_issues.append("Requirement-bearing source passages are not covered by the analysis.")
    if visibly_truncated:
        result.completeness_issues.append("The source ends in an unfinished sentence.")
    result.is_reliable = bool(requirements or result.role_competencies or result.responsibilities) and not result.completeness_issues
    result.qualification_assessment = (
        "Explicit qualification requirements assessed against documented profile evidence."
        if requirements else
        "Qualification requirements are not specified. Assessment is based on listed role competencies and responsibilities."
    )
    result.role_competency_counts = {
        status.value: sum(r.status == status for r in result.role_competencies)
        for status in RequirementStatus
    }
    result.role_alignment_summary = (
        f"Role evidence: {result.role_competency_counts['strong']} confirmed competencies, "
        f"{result.role_competency_counts['partial']} partial matches, "
        f"{result.role_competency_counts['missing']} not confirmed in profile, "
        f"{result.role_competency_counts['absent']} confirmed gaps. "
        "This assesses the supplied text only, not completeness of the original webpage. This compares documented experience only; it does not establish proficiency at an unknown required level. "
        f"{len(result.responsibilities)} responsibility source passages are available for scope review and do not create mandatory blockers."
    )
    result.requirement_counts = {"mandatory": sum(r.priority == RequirementPriority.MANDATORY for r in requirements),
                                 "preferred": sum(r.priority != RequirementPriority.MANDATORY for r in requirements),
                                 "confirmed": len(result.strong_matches), "partial": len(result.partial_matches),
                                 "not_confirmed": len(result.missing_requirements),
                                 "confirmed_absence": sum(r.status == RequirementStatus.ABSENT for r in requirements)}
    if not result.is_reliable:
        result.match_level, result.recommendation = MatchLevel.UNRELIABLE, Recommendation.RETRY
        result.reasoning_summary = "Incomplete analysis — review required. " + " ".join(result.completeness_issues or ["No requirements with a verifiable source were identified."])
        return result
    if not requirements:
        result.match_level, result.recommendation = MatchLevel.LIMITED, Recommendation.REVIEW
        result.reasoning_summary = result.qualification_assessment + " " + result.role_alignment_summary
        return result
    # Equivalent clauses share one weight while all source rows remain reviewable.
    # AND groups use their weakest condition; OR is verified before scoring.
    mandatory = [r for r in requirements if r.priority == RequirementPriority.MANDATORY]
    if not mandatory:
        result.match_level, result.recommendation = MatchLevel.LIMITED, Recommendation.REVIEW
        result.scoring_counts = {'mandatory_groups': 0, 'confirmed': 0, 'partial': 0, 'not_confirmed_or_gap': 0, 'duplicate_rows': 0}
        result.qualification_assessment = 'Only preferred qualifications are specified; mandatory qualification requirements need source review.'
        result.reasoning_summary = result.qualification_assessment + ' Preferred matches do not establish full qualification for the role.'
        return result
    groups = {}
    for r in mandatory:
        conjunctive_group = r.operator == 'all' and sum(other.group_id == r.group_id for other in mandatory) > 1
        key = r.group_id if conjunctive_group else r.scoring_key
        groups.setdefault(key, []).append({RequirementStatus.STRONG: 1, RequirementStatus.PARTIAL: .5, RequirementStatus.MISSING: 0, RequirementStatus.ABSENT: 0}[r.status])
    score = sum(min(values) for values in groups.values()) / len(groups)
    result.scoring_counts = {'mandatory_groups': len(groups) if mandatory else 0,
                             'confirmed': sum(min(v) == 1 for v in groups.values()),
                             'partial': sum(min(v) == .5 for v in groups.values()),
                             'not_confirmed_or_gap': sum(min(v) == 0 for v in groups.values()),
                             'duplicate_rows': sum(bool(r.duplicate_of) for r in mandatory)}
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
