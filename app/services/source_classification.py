"""Resolve complete model classifications against literal source, independent of layout."""
from app.services.job_sections import SourceUnit, clean_source_line, extract_sections, normalize_source_layout
from app.services.semantic_requirements import resolve_source_quotes
from app.services.source_dispositions import known_source_context


def model_source_units(candidate, text):
    """Return verified dispositions, or explicit coverage/provenance errors.

    A complete disposition map supersedes section-parser hints. Sparse legacy
    responses retain the source-review path, never pretend to cover the source.
    """
    if not candidate.source_context and not candidate.responsibilities:
        return None, []
    claims = []
    parsed, _ = extract_sections(text)
    source_hints = {}
    portal_metadata = set()
    for unit in parsed:
        source_hints.setdefault(clean_source_line(unit.quote), set()).add(unit.category)
        if unit.category == 'competency':
            from app.services.ollama_analysis import needs_assessment
            # An unknown heading can leave real candidate conditions inside a
            # stack section. Metadata is not a blanket coverage exemption.
            if not needs_assessment({'text': unit.quote, 'hints': ['competency']}):
                portal_metadata.add(clean_source_line(unit.quote))
            portal_metadata.update(clean_source_line(quote) for quote in unit.supporting_quotes)
    for row in candidate.requirements:
        for quote in dict.fromkeys([row.source_quote, *row.source_quotes]):
            if quote:
                claims.append((quote, row.priority.value, row.name, row))
    for row in candidate.role_competencies:
        for quote in dict.fromkeys([row.source_quote, *row.source_quotes]):
            if quote:
                claims.append((quote, 'competency', row.name, row))
    for category, rows in [('responsibility', candidate.responsibilities), ('context', candidate.source_context)]:
        for row in rows:
            claims.append((row.get('source_quote', ''), category, row.get('name', row.get('text', '')), None))
    # A portal level is parser-owned presentation metadata, not a candidate
    # qualification. Some normalized rows retain it in required_level rather
    # than source_quotes; repeated validation must not lose its source coverage.
    claimed_quotes = {clean_source_line(quote) for quote, *_ in claims}
    for unit in parsed:
        if unit.category == 'competency':
            for quote in unit.supporting_quotes:
                if clean_source_line(quote) not in claimed_quotes:
                    claims.append((quote, 'context', quote, None))
                    claimed_quotes.add(clean_source_line(quote))
    units, issues = [], []
    for quote, category, name, row in claims:
        resolved = resolve_source_quotes(quote, text) if quote.strip() else []
        if not resolved:
            issues.append('A model source classification had no verifiable original source quote.')
            continue
        for literal in resolved:
            from app.services.ollama_analysis import assessment_priority, needs_assessment, needs_responsibility
            literal_category, literal_row, literal_name = category, row, name
            passage = {'text': literal, 'hints': list(source_hints.get(clean_source_line(literal), []))}
            if row is not None and clean_source_line(literal) not in portal_metadata:
                from app.services.source_scope import source_alignment_issue
                alignment_issue = source_alignment_issue(name, literal)
                if alignment_issue:
                    issues.append(alignment_issue)
            if clean_source_line(literal) in portal_metadata or known_source_context(passage):
                # Portal tags/levels and known administrative text have canonical
                # context dispositions. Preserve literal coverage without
                # allowing model labels to create scored qualifications.
                literal_category, literal_row, literal_name = 'context', None, literal
            elif literal_category in {'mandatory', 'preferred', 'nice_to_have'} and needs_responsibility(passage):
                issues.append(f'Explicit responsibility was scored as a qualification: {literal}')
            # Literal candidate-condition guards are independent of section names.
            # A complete context map cannot silently discard explicit conditions.
            if literal_category in {'context', 'responsibility', 'competency'}:
                if literal_category in {'context', 'responsibility'} and needs_assessment(passage):
                    issues.append(f'Candidate condition was classified as context: {literal}')
                elif literal_category == 'competency' and assessment_priority(passage) is not None:
                    issues.append(f'Explicit qualification was excluded from qualification scoring: {literal}')
                if literal_category == 'context' and needs_responsibility(passage):
                    issues.append(f'Explicit responsibility was classified as context: {literal}')
            units.append(SourceUnit(
                literal_name or literal, literal, literal_category, 'Model source classification; literal provenance verified',
                literal_row.source_section if literal_row else '', f'model_source_{len(units)+1}',
                level=literal_row.required_level if literal_row else '', operator=literal_row.operator if literal_row else 'single',
                alternatives=list(literal_row.alternatives) if literal_row else [],
                uncertain=literal_row.interpretation_uncertain if literal_row else False,
            ))
    # Normalize presentation only. Every line must occur in a verified quote;
    # an unknown heading or benefits paragraph is covered by a context disposition.
    covered = [' '.join(clean_source_line(line).split())
               for unit in units for line in unit.quote.splitlines() if clean_source_line(line)]
    for line in normalize_source_layout(text).splitlines():
        normalized = ' '.join(clean_source_line(line).split())
        if normalized and normalized != candidate.role and not any(normalized == value for value in covered):
            issues.append(f'Unclassified source passage needs review: {line.strip()}')
    for i, unit in enumerate(units):
        for other in units[:i]:
            from app.services.source_scope import AVAILABILITY
            arrangement_note = (AVAILABILITY.search(unit.quote)
                                and 'context' in {unit.category, other.category}
                                and bool({unit.category, other.category} & {'mandatory', 'preferred', 'nice_to_have'}))
            if (unit.quote == other.quote and unit.category != other.category
                    and {unit.category, other.category} != {'competency', 'responsibility'}
                    and not arrangement_note):
                issues.append(f'Conflicting model source classifications: {unit.quote}')
    unique = []
    for unit in units:
        if unit.category in {'context', 'responsibility'} and any(
                prior.quote == unit.quote and prior.category == unit.category for prior in unique):
            continue
        unique.append(unit)
    return unique, list(dict.fromkeys(issues))
