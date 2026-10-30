"""Resolve complete model classifications against literal source, independent of layout."""
from app.services.job_sections import SourceUnit, clean_source_line
from app.services.semantic_requirements import resolve_source_quotes


def model_source_units(candidate, text):
    """Return verified dispositions, or explicit coverage/provenance errors.

    A complete disposition map supersedes section-parser hints. Sparse legacy
    responses retain the source-review path, never pretend to cover the source.
    """
    if not candidate.source_context and not candidate.responsibilities:
        return None, []
    claims = []
    for row in candidate.requirements:
        claims.append((row.source_quote, row.priority.value, row.name, row))
    for row in candidate.role_competencies:
        claims.append((row.source_quote, 'competency', row.name, row))
    for category, rows in [('responsibility', candidate.responsibilities), ('context', candidate.source_context)]:
        for row in rows:
            claims.append((row.get('source_quote', ''), category, row.get('name', row.get('text', '')), None))
    units, issues = [], []
    for quote, category, name, row in claims:
        resolved = resolve_source_quotes(quote, text) if quote.strip() else []
        if not resolved:
            issues.append('A model source classification had no verifiable original source quote.')
            continue
        for literal in resolved:
            # Literal candidate-condition guards are independent of section names.
            # A complete context map cannot silently discard explicit conditions.
            if category in {'context', 'responsibility'}:
                from app.services.ollama_analysis import needs_assessment
                if needs_assessment({'text': literal, 'hints': []}):
                    issues.append(f'Candidate condition was classified as context: {literal}')
            units.append(SourceUnit(
                name or literal, literal, category, 'Model source classification; literal provenance verified',
                row.source_section if row else '', f'model_source_{len(units)+1}',
                level=row.required_level if row else '', operator=row.operator if row else 'single',
                alternatives=list(row.alternatives) if row else [],
                uncertain=row.interpretation_uncertain if row else False,
            ))
    # Normalize presentation only. Every line must occur in a verified quote;
    # an unknown heading or benefits paragraph is covered by a context disposition.
    covered = [' '.join(clean_source_line(line).split())
               for unit in units for line in unit.quote.splitlines() if clean_source_line(line)]
    for line in text.splitlines():
        normalized = ' '.join(clean_source_line(line).split())
        if normalized and normalized != candidate.role and not any(normalized == value for value in covered):
            issues.append(f'Unclassified source passage needs review: {line.strip()}')
    for i, unit in enumerate(units):
        for other in units[:i]:
            if (unit.quote == other.quote and unit.category != other.category
                    and {unit.category, other.category} != {'competency', 'responsibility'}):
                issues.append(f'Conflicting model source classifications: {unit.quote}')
    return units, list(dict.fromkeys(issues))
