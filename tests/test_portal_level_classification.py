from app.models.job import JobRequest
from app.services.analysis_validator import AnalysisValidator
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment


def test_repeated_portal_regular_cannot_create_conflicting_source_categories(profile):
    job = JobRequest(company='Synthetic', role='Engineer', job_description=(
        'Requirements\nKnowledge of SQL\nTECH STACK\nSQL\nregular\nLinux\nregular'))
    inv = AnalysisInventory.build(job, profile)
    rows, level_count = [], 0
    for pid, passage in inv.passages.items():
        if passage['text'] == 'Knowledge of SQL':
            rows.append(CompactAssessment(p=pid, k='requirement', n='SQL', priority='mandatory', why='Not documented.'))
        elif passage['text'] == 'regular':
            level_count += 1
            assert passage['context_only']
            schema = inv.keyed_schema([pid])
            ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
            assert schema['$defs'][ref]['properties']['k']['enum'] == ['context']
            # Defend older/provider-neutral outputs that gave identical portal
            # labels different dispositions, not only newly constrained schemas.
            rows.append(CompactAssessment(p=pid, k='context' if level_count == 1 else 'responsibility'))
        else:
            rows.append(CompactAssessment(p=pid, k='context'))
    assert level_count == 2
    result = inv.expand(rows).to_analysis(job)
    for _ in range(3):
        result = AnalysisValidator(profile).validate(result, f'{job.role}\n{job.job_description}', semantic=True)
        assert result.is_reliable
        assert not any('Conflicting' in issue for issue in result.classification_issues)
        assert not any(r.source_quote == 'regular' for r in result.requirements)


def test_explicit_language_requirement_is_not_portal_level_metadata(profile):
    job = JobRequest(company='Synthetic', role='Engineer', job_description=(
        'Requirements\nEnglish B2 is required\nTECH STACK\nen\nB2'))
    inv = AnalysisInventory.build(job, profile)
    condition = next(p for p in inv.passages.values() if p['text'] == 'English B2 is required')
    metadata = next(p for p in inv.passages.values() if p['text'] == 'B2')
    assert not condition['context_only']
    assert metadata['context_only']
