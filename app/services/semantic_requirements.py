"""Validate model interpretations without replacing semantic reasoning with rules.

Literal source provenance, cited facts, AND/OR arithmetic and objective date /
language contradictions are checked here. Unknown technologies, unusual headings
and semantic paraphrases remain available to the model. CV export has its own,
stricter fact boundary.
"""

import re

from app.models.job import RequirementStatus as Status
from app.services.evidence_matching import NEGATIVE, required_level, required_years, scoring_key
from app.services.fact_catalog import normalized_tokens


def source_components(text):
    """Parse short named lists; retain qualifiers and leave mixed logic for review."""
    examples = re.search(r'\b(?:such as|for example|e\.g\.|takich jak|np\.)\s*:?', text, re.I)
    prefix = re.match(r'^(?:(?:.*?\b(?:of|with|in|using|handling))|znajomość|doświadczenie w)\s+', text, re.I)
    body = text[examples.end():] if examples else text[prefix.end():] if prefix else text
    body = body.strip(' .;()')
    has_and = bool(re.search(r'\band\b|\boraz\b|\bi\b|\s[+&]\s', body, re.I))
    has_or = bool(re.search(r'\bor\b|\blub\b', body, re.I))
    if not (has_and or has_or or examples):
        return [], 'single'
    parts = re.split(r'\s*(?:,|\s[+&]\s|\b(?:and|oraz|i|or|lub)\b)\s*', body, flags=re.I)
    if len(parts) < 2 or any(not re.fullmatch(r'[A-Z][\w+#.-]*(?: [A-Z0-9][\w+#.-]*){0,3}', p) for p in parts):
        return [], 'single'
    operator = 'any' if examples or has_or and not has_and else 'all' if not has_or else 'ambiguous'
    shared = text[:prefix.end()] if prefix and not examples else ''
    # Plain knowledge labels add no level; practical/advanced/tenure modifiers do.
    if re.fullmatch(r'(?:Knowledge of|Familiarity with|Znajomość)\s+', shared, re.I):
        shared = ''
    return [shared + p for p in parts], operator


def explicit_list(text):
    """Existing grammatical lists remain available even with lower-case labels."""
    if ',' not in text:
        return []
    match = re.search(r'(?:\bof\b|\bwith\b|\busing\b|\bhandling\b|takich jak:)\s+(.+)$', text, re.I)
    if not match:
        return []
    parts = [re.sub(r'^(?:and|oraz|or|lub)\s+', '', p.strip(' .;'), flags=re.I)
             for p in re.split(r',\s*|\s+(?:and|oraz|or|lub)\s+', match[1], flags=re.I)]
    return parts if len(parts) >= 3 and all(0 < len(p.split()) <= 4 and '(' not in p for p in parts) else []


def resolve_source_quotes(quote, job_text):
    """Recover only literal spans; normalize whitespace and final punctuation.

    Several quoted sentences may refer to distinct source passages. Never use
    fuzzy similarity or replace candidate facts with an invented job fragment.
    """

    def resolve(value):
        value = value.strip().rstrip(".;")
        if not value:
            return None
        pattern = r"\s+".join(re.escape(v) for v in value.split())
        match = re.search(pattern, job_text)
        return match[0] if match else None

    if quote in job_text:
        return [quote]
    if resolved := resolve(quote):
        return [resolved]
    parts = re.split(r"(?<=[.;])\s+(?=[A-Z])", quote.strip())
    resolved = [resolve(part) for part in parts]
    return resolved if resolved and all(resolved) else []


def quoted_language_level(name, quote):
    # Bind explicit CEFR/native/fluency labels to their named subject; do not infer a
    # level from adjectives or turn a model's compound scope into one language.
    forward = re.findall(r"\b([A-Za-z]+)\s*[-:–—(]?\s*([ABC][12]\+?|native|fluent|fluency)(?!\w)", quote, re.I)
    reverse = [
        (subject, level)
        for level, subject in re.findall(
            r"\b([ABC][12]\+?|native|fluent|fluency)\s+(?:in\s+)?([A-Za-z]+)\b", quote, re.I
        )
    ]
    values = [
        level for subject, level in forward + reverse if re.search(r"\b" + re.escape(subject) + r"\b", name, re.I)
    ]
    return values[0] if len(set(v.upper() for v in values)) == 1 else ""


def language_only(name):
    return bool(
        re.fullmatch(
            r"(?:native |fluent )?(?:English|Polish|German|French|Spanish)(?:\s+(?:language|proficiency|[ABC][12]\+?|native))*",
            name.strip(),
            re.I,
        )
    )


def language_check_name(name, level):
    # A model title saying B2 must not shadow a quoted B2+ minimum.
    if level:
        name = re.sub(r"\b(?:[ABC][12]\+?|native|fluent|fluency)(?!\w)", "", name, flags=re.I)
    return name + " " + level


def _facts(validator, item, *, practical_scope=False, ml_context=""):
    from app.services.competency_scope import scoped_match
    scoped = scoped_match(validator.matcher, item.name)
    from app.services.evidence_strength import CI
    if scoped is None and (CI.search(item.name) or re.search(r'\b(?:IT support|M365|Microsoft 365|Entra ID|Intune)\b', item.name, re.I)):
        scoped = validator.matcher.match(item.name)
    original_status, original_ids = item.status, list(item.source_fact_ids)
    if scoped is not None:
        item.status = scoped.status
        item.source_fact_ids = [e.source_id for e in scoped.entries]
        item.reason = scoped.reason
    lookup = {e.source_id: e for e in validator.matcher.entries}
    entries = [lookup[i] for i in dict.fromkeys(item.source_fact_ids) if i in lookup and lookup[i].kind != "interest"]
    item.source_fact_ids = [e.source_id for e in entries]
    item.evidence = [e.text for e in entries]
    item.evidence_sources = validator.matcher.sources(item.source_fact_ids)
    if scoped is None and item.status in {Status.STRONG, Status.PARTIAL} and not any(not NEGATIVE.search(e.text) for e in entries):
        item.status = Status.MISSING
        item.reason += " Cited evidence is missing or invalid; this does not establish a lack of competence."
    scoped_gap = (
        validator.matcher.match(item.name + " " + getattr(item, "source_quote", ""))
        if item.status == Status.ABSENT
        else None
    )
    if item.status == Status.ABSENT and (not scoped_gap or scoped_gap.status != Status.ABSENT):
        item.status = Status.MISSING
        item.reason += " No explicit negative evidence supports a confirmed gap."
    from app.services.evidence_strength import ci_ceiling, evidence_strength

    practical = practical_scope or bool(
        re.search(
            r"\bexperience\b|\bpractical\b|hands.on|\bproficien\w*|\b(?:install|configur|develop|implement|deploy|troubleshoot|script)\w*|working|production",
            item.name + " " + getattr(item, "source_quote", ""),
            re.I,
        )
    )
    if (
        item.status == Status.STRONG
        and entries
        and practical
        and all(evidence_strength(e) in {"declaration", "theoretical_knowledge", "academic_knowledge"} for e in entries)
    ):
        item.status = Status.PARTIAL
        item.reason += " Declared knowledge is documented; practical use and the requested scope/level are not established by a technology name alone."

    from app.services.academic_ml import COMMERCIAL, LIBRARIES, TRAINING, ml_ceiling
    ml_scope = item.name + ' ' + getattr(item, 'source_quote', '') + ' ' + getattr(item, 'required_level', '')
    if (LIBRARIES.search(item.name) or TRAINING.search(item.name)) and COMMERCIAL.search(ml_context):
        ml_scope += " commercial experience"
    if LIBRARIES.search(item.name) and TRAINING.search(ml_context):
        ml_scope += " training models"
    ml_limit = ml_ceiling(ml_scope, entries, validator.skills_bank, operator=getattr(item, 'operator', 'all'))
    if ml_limit and item.status == Status.STRONG and ml_limit[0] != 'strong':
        item.status = Status(ml_limit[0])
        item.reason += ' ' + ml_limit[1]

    ceiling = ci_ceiling(item.name, entries)
    if ceiling and item.status == Status.STRONG and ceiling[0] != "strong":
        item.status = Status(ceiling[0])
        item.reason += " " + ceiling[1]
    if hasattr(item, "required_level"):
        language_name = language_check_name(item.name, item.required_level)
        language = validator.matcher._language(language_name)
        if language and re.search(r"\b[ABC][12]\+?|\bnative\b|\bfluent\b|\bfluency\b", language_name, re.I):
            if language.status != Status.STRONG or language_only(item.name):
                item.status = language.status
            item.source_fact_ids = list(dict.fromkeys(item.source_fact_ids + [e.source_id for e in language.entries]))
            item.evidence_sources = validator.matcher.sources(item.source_fact_ids)
            item.evidence = [e["fact"] for e in item.evidence_sources]
            item.reason += " " + language.reason
    if original_status == Status.STRONG and item.status != Status.STRONG:
        validator._evidence_issues.append(f'Unsupported model confirmation corrected: {item.name}.')
    if set(original_ids) - set(item.source_fact_ids):
        validator._evidence_issues.append(f'Invalid or irrelevant evidence removed: {item.name}.')
    return entries


def validated_model_requirements(validator, candidate, job_text, units, fallback):
    from app.services.job_sections import clean_source_line, extract_sections

    def heading_key(value):
        return clean_source_line(value).strip(" #:\t\r\n").casefold()

    headings = {heading_key(s) for s in extract_sections(job_text)[1]}
    requirements, issues = [], []
    excluded = {"benefits", "employment", "recruitment", "organization", "responsibility", "competency"}
    context_text = " ".join(" ".join(u.quote.split()) for u in units if u.category in excluded)
    for original in candidate.requirements:
        req = original.model_copy(deep=True)
        quotes = resolve_source_quotes(req.source_quote, job_text) if req.source_quote.strip() else []
        if not quotes:
            issues.append("A model requirement had no verifiable original source quote.")
            continue
        if all(heading_key(quote) in headings for quote in quotes):
            # A recognized section title has no qualification content itself.
            # Keep its body available for the model instead of scoring the title.
            continue
        qualification_categories = {"mandatory", "preferred", "nice_to_have"}
        if all(
            (any(u.category in excluded and quote in u.quote for u in units) or " ".join(quote.split()) in context_text)
            and not any(u.category in qualification_categories and quote in u.quote for u in units)
            for quote in quotes
        ):
            validator._classification_issues.append(f'Model qualification rejected: context passage {quotes[0]}')
            # Preserve the passage in source_context; it cannot enter qualification
            # arithmetic just because an earlier section was preferred.
            continue
        if all(quote.strip() == candidate.role.strip() for quote in quotes):
            continue
        req.source_quote = quotes[0]
        req.source_quotes = list(dict.fromkeys(quotes))
        req.interpretation_origin = "llm"
        req.source_section = req.source_section or next(
            (u.section for u in units if req.source_quote in u.quote), "Unsectioned source"
        )
        req.required_level = quoted_language_level(req.name, " ".join(quotes)) or req.required_level
        from app.models.job import RequirementComponent
        from app.services.competency_scope import atomic_parts
        parts = atomic_parts(req.source_quote) or atomic_parts(req.name)
        list_parts, list_operator = source_components(req.source_quote)
        parts = parts or list_parts
        if parts:
            req.operator = list_operator if list_parts else "all"
            # Preserve claims for validation when their scope is identical.
            old = {re.sub(r'^(?:(?:knowledge|experience|familiarity|proficiency) (?:of|in|with)|znajomość)\s+', '', c.name, flags=re.I).casefold(): c for c in req.components}
            req.components = []
            for part in parts:
                key = re.sub(r'^(?:(?:knowledge|experience|familiarity|proficiency) (?:of|in|with)|znajomość)\s+', '', part, flags=re.I).casefold()
                component = old[key].model_copy(update={'name': part}) if key in old else RequirementComponent(name=part)
                req.components.append(component)
        if req.operator == 'ambiguous':
            req.interpretation_uncertain = True
        for component in req.components:
            if not component.reason and not component.source_fact_ids:
                from app.services.grounded_requirements import verify_requirement
                component.status, component.evidence, component.source_fact_ids, component.reason = verify_requirement(validator, component.name)
        entries = _facts(validator, req)
        if not req.reason.strip():
            req.interpretation_uncertain = True
            req.reason = "Model interpretation requires an explanation of scope and evidence."
            if req.status == Status.STRONG:
                req.status = Status.PARTIAL if entries else Status.MISSING
        source_units = [u for u in units if any(quote in u.quote for quote in quotes)]
        qualifications = [u for u in source_units if u.category in {"mandatory", "preferred", "nice_to_have"}]
        preferred = [u for u in qualifications if u.category in {"preferred", "nice_to_have"}]
        boilerplate = {
            "knowledge",
            "familiarity",
            "experience",
            "basic",
            "working",
            "preferred",
            "skill",
            "skills",
            "of",
            "with",
            "in",
            "or",
            "and",
        }
        scoped_name = normalized_tokens(req.name) - boilerplate
        exact_preference_scope = [
            u for u in preferred if scoped_name and scoped_name <= (normalized_tokens(u.name) - boilerplate)
        ]
        if (
            req.priority == "mandatory"
            and preferred
            and (len(preferred) == len(qualifications) or exact_preference_scope)
            and not re.search(r"\bmust\b|\brequired\b|\bmandatory\b", " ".join(quotes), re.I)
        ):
            selected = exact_preference_scope or preferred
            clear = any(u.section.casefold().strip(" :") != "desired experience" for u in selected)
            if clear:
                req.priority = "nice_to_have" if all(u.category == "nice_to_have" for u in selected) else "preferred"
                req.reason += (
                    " Explicit optional/preferred source wording corrected an inconsistent mandatory priority."
                )
            else:
                req.interpretation_uncertain = True
                req.reason += " Source heading suggests a preference while the model inferred a mandatory condition; confirm employer priority."
        if (
            req.operator == "any"
            and explicit_list(" ".join(quotes))
            and re.search(r"\b(?:and|oraz)\b", " ".join(quotes), re.I)
            and not re.search(r"\b(?:or|lub)\b|such as|for example|takich jak|e\.g\.|np\.", " ".join(quotes), re.I)
        ):
            req.operator = "all"
            req.interpretation_uncertain = True
            req.reason += (
                " The explicit source list uses AND; OR output was inconsistent. All component results are retained."
            )
        for component in req.components:
            component.required_level = (
                quoted_language_level(component.name, " ".join(quotes)) or component.required_level
            )
            _facts(
                validator,
                component,
                ml_context=req.name + " " + " ".join(quotes),
                practical_scope=bool(
                    re.search(
                        r"(?m)^(?:practical|hands.on|professional|experience|proficien\w*|(?:install|configur|develop|implement|deploy|troubleshoot|script)\w*|working|production)\b",
                        req.name + "\n" + " ".join(quotes),
                        re.I,
                    )
                ),
            )
        if req.components and req.operator in {"all", "any"}:
            req.alternatives = [c.name for c in req.components] if req.operator == "any" else req.alternatives
            statuses = [c.status for c in req.components]
            if req.operator == "any":
                req.status = max(
                    statuses,
                    key=lambda s: {Status.STRONG: 3, Status.PARTIAL: 2, Status.MISSING: 1, Status.ABSENT: 0}[s],
                )
            elif all(s == Status.STRONG for s in statuses):
                req.status = Status.STRONG
            elif Status.ABSENT in statuses:
                req.status = Status.ABSENT
            else:
                req.status = (
                    Status.PARTIAL if any(s in {Status.STRONG, Status.PARTIAL} for s in statuses) else Status.MISSING
                )
            req.source_fact_ids = list(dict.fromkeys(i for c in req.components for i in c.source_fact_ids))
            req.evidence_sources = validator.matcher.sources(req.source_fact_ids)
            req.evidence = [s["fact"] for s in req.evidence_sources]
        elif explicit_list(req.name) and req.status == Status.STRONG:
            # A whole AND condition cannot be proved by citing only one item.
            req.interpretation_uncertain = True
            req.status = Status.PARTIAL if entries else Status.MISSING
            req.reason += " Item-level assessment of this combined list is required."
        from app.services.academic_ml import ml_ceiling
        lookup = {entry.source_id: entry for entry in validator.matcher.entries}
        ml_limit = ml_ceiling(req.name + ' ' + req.source_quote + ' ' + req.required_level,
                              [lookup[i] for i in req.source_fact_ids if i in lookup], validator.skills_bank, operator=req.operator)
        if ml_limit and req.status == Status.STRONG and ml_limit[0] != 'strong':
            req.status = Status(ml_limit[0])
            req.reason += ' ' + ml_limit[1]
        minimum = required_years(req.source_quote) or required_years(req.name) or req.required_years
        if minimum is not None:
            # The model chooses which employment duties/roles are relevant;
            # dates and overlap are calculated exclusively from cited records.
            from app.services.academic_ml import ACTIVITY, LIBRARIES, TRAINING, academic_entry, ml_entries
            scope = req.name + " " + req.source_quote
            tenure_ids = req.source_fact_ids
            if LIBRARIES.search(scope) or TRAINING.search(scope):
                relevant = ml_entries(scope, [lookup[i] for i in tenure_ids if i in lookup])
                tenure_ids = [entry.source_id for entry in relevant if entry.kind == 'experience'
                              and not academic_entry(entry) and ACTIVITY.search(entry.text)
                              and (not TRAINING.search(scope) or TRAINING.search(entry.text))]
            tenure = validator.matcher.cited_tenure(tenure_ids, minimum)
            req.required_years, req.observed_years = minimum, tenure.observed_years
            req.status = tenure.status
            req.reason += " " + tenure.reason
            duration_free = re.sub(r"\b\d+(?:\.\d+)?\s*\+?\s*(?:years?|lat(?:a)?|rok(?:u)?)\b", "", scope + " " + req.required_level, flags=re.I)
            scope_limit = ml_ceiling(duration_free, [lookup[i] for i in req.source_fact_ids if i in lookup], validator.skills_bank, operator=req.operator)
            if scope_limit and req.status == Status.STRONG and scope_limit[0] != 'strong':
                req.status = Status(scope_limit[0])
                req.reason += ' ' + scope_limit[1]
        req.required_level = req.required_level or required_level(req.name) or required_level(req.source_quote)
        language_name = language_check_name(req.name, req.required_level)
        if not validator.matcher._language(req.name):
            language_name += " " + " ".join(quotes)
        language = validator.matcher._language(language_name)
        if (
            language
            and not req.components
            and re.search(r"\b[ABC][12]\+?|\bnative\b|\bfluent\b|\bfluency\b", language_name, re.I)
        ):
            if language.status != Status.STRONG or language_only(req.name):
                req.status = language.status
            req.source_fact_ids = list(dict.fromkeys(req.source_fact_ids + [e.source_id for e in language.entries]))
            req.evidence_sources = validator.matcher.sources(req.source_fact_ids)
            req.evidence = [e["fact"] for e in req.evidence_sources]
            req.reason += " " + language.reason
        req.required_level = req.required_level or required_level(req.name)
        req.scoring_key = scoring_key(req.name)
        req.source_quotes = list(dict.fromkeys([req.source_quote, *req.source_quotes]))
        if any(u.uncertain and u.category != 'unknown' for u in source_units):
            req.interpretation_uncertain = True
        req.classification_basis = (
            req.classification_basis or "Model semantic interpretation; original source and cited facts verified"
        )
        req.clarification_needed = req.reason if req.status != Status.STRONG or req.interpretation_uncertain else ""
        requirements.append(req)
    # Missing model passages remain visible and are explicitly identified as
    # source review. They do not silently replace the model's valid interpretation.
    for req in fallback:
        if any(req.source_quote == model.source_quote or req.name == model.name for model in requirements):
            continue
        req.interpretation_origin = "source_review"
        requirements.append(req)
    for index, req in enumerate(requirements):
        req.id = f"req_{index + 1}"
        req.group_id = req.group_id or req.id
    return requirements, issues


def merge_equivalent_source_rows(requirements):
    """Merge alias labels for the same assessed source scope, not AND children.

    A shared quote alone is insufficient: source, priority, tenure, proficiency
    and substantive labels must agree. Single-token branches remain independent.
    """
    boilerplate = {
        "experience",
        "knowledge",
        "familiarity",
        "understanding",
        "proficiency",
        "working",
        "tools",
        "tool",
        "technology",
        "technologies",
        "skill",
        "skills",
        "e.g",
    }

    def terms(req):
        values = normalized_tokens(re.sub(r"\be\.g\.\s*", "", req.name, flags=re.I)) - boilerplate
        actions = {"troubleshooting": "troubleshoot", "debugging": "debug", "deployments": "deployment"}
        return {actions.get(v, v) for v in values}

    def source_title(req):
        name = req.name.strip(" .;")
        quote = req.source_quote.strip(" .;")
        return name == quote or (len(name) >= 80 and quote.startswith(name))

    result = []
    for req in requirements:
        match = None
        for previous in result:
            same_scope = (
                previous.source_quote == req.source_quote
                and previous.priority == req.priority
                and previous.required_level == req.required_level
                and previous.required_years == req.required_years
            )
            left, right = terms(previous), terms(req)
            overlap = len(left & right)
            equivalent = left == right or (
                min(len(left), len(right)) >= 2
                and (
                    overlap / len(left | right) >= 0.8
                    or (
                        (source_title(previous) or source_title(req))
                        and (
                            overlap / min(len(left), len(right)) >= 0.8
                            or (overlap >= 3 and not re.search(r"\band\b|\boraz\b", req.source_quote, re.I))
                        )
                    )
                )
            )
            if same_scope and equivalent:
                match = previous
                break
        if match is None:
            result.append(req)
            continue
        match.source_fact_ids = list(dict.fromkeys(match.source_fact_ids + req.source_fact_ids))
        match.evidence_sources = list(
            {e["source_id"]: e for e in match.evidence_sources + req.evidence_sources}.values()
        )
        match.evidence = list(dict.fromkeys(match.evidence + req.evidence))
        match.source_quotes = list(dict.fromkeys(match.source_quotes + req.source_quotes))
        if len(req.components) > len(match.components):
            match.components = req.components
            match.operator = req.operator
        if match.status != req.status:
            match.interpretation_uncertain = True
            # Conflicting duplicate claims cannot improve a match without proof.
            order = {Status.STRONG: 3, Status.PARTIAL: 2, Status.MISSING: 1, Status.ABSENT: 0}
            match.status = min([match.status, req.status], key=order.get)
            match.reason += (
                " Duplicate interpretations disagree; the conservative source-backed status is retained for review."
            )
        match.interpretation_uncertain |= req.interpretation_uncertain
    for i, req in enumerate(result):
        req.id = f"req_{i + 1}"
        req.group_id = req.id
        req.duplicate_of = ""
    return result
