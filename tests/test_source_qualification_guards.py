import pytest

from app.models.job import JobRequest
from app.services.analysis_validator import AnalysisValidator
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment

SOURCE = '''At cloudatus, you will:
Administer and maintain on-premises and cloud-based infrastructure environments
Required technical and professional expertise:
Very good knowledge of Windows Server technologies
Strong background in configuration and management of one virtualization platform
Hands-on experience with backup and monitoring solutions
Experience in servers/application/databases migration
Knowledge of Azure public cloud
Nice to have:
Familiarity with administration of Linux based operation systems
German language skills
Benefits:
Modern computer equipment
TECH STACK
en
B2
Windows Server
regular'''


def setup_inventory(profile):
    job = JobRequest(company='cloudatus', role='Infrastructure Administrator', job_description=SOURCE)
    return job, AnalysisInventory.build(job, profile)


def test_complete_context_map_cannot_claim_reliable_qualification_coverage(profile):
    job, inv = setup_inventory(profile)
    rows = [CompactAssessment(p=pid, k='context') for pid in inv.passages]
    candidate = inv.expand(rows).to_analysis(job)
    result = AnalysisValidator(profile).validate(candidate, f'{job.role}\n{SOURCE}', semantic=True)
    assert not result.is_reliable
    assert result.match_level.value == 'UNRELIABLE'
    assert any('Very good knowledge' in quote for quote in result.unassessed_source_passages)
    assert any('Strong background' in quote for quote in result.unassessed_source_passages)
    assert any('Administer and maintain' in quote for quote in result.unassessed_source_passages)
    assert not any(r.name == 'en\nB2' for r in result.requirements)


def test_required_capabilities_cannot_escape_scoring_as_role_tags(profile):
    job, inv = setup_inventory(profile)
    target = next(pid for pid, p in inv.passages.items() if p['text'] == 'Knowledge of Azure public cloud')
    rows = [CompactAssessment(p=pid, k='competency', n='Azure', why='Not documented.')
            if pid == target else CompactAssessment(p=pid, k='context') for pid in inv.passages]
    candidate = inv.expand(rows).to_analysis(job)
    result = AnalysisValidator(profile).validate(candidate, f'{job.role}\n{SOURCE}', semantic=True)
    assert not result.is_reliable
    assert any('Knowledge of Azure public cloud' in quote for quote in result.unassessed_source_passages)
    repaired = inv.validate_rows([rows[list(inv.passages).index(target)]], [target])[0]
    assert repaired.k == 'requirement'
    assert repaired.priority.value == 'mandatory'
    assert repaired.s.value == 'missing'
    assert repaired.f == []


@pytest.mark.parametrize('phrase,kind,priority', [
    ('Very good knowledge of Windows Server technologies', 'requirement', 'mandatory'),
    ('Strong background in configuration and management of one virtualization platform', 'requirement', 'mandatory'),
    ('Knowledge of Azure public cloud', 'requirement', 'mandatory'),
    ('German language skills', 'requirement', 'preferred'),
    ('Administer and maintain on-premises and cloud-based infrastructure environments', 'responsibility', None),
])
def test_structured_schema_preserves_clear_source_dispositions(profile, phrase, kind, priority):
    _, inv = setup_inventory(profile)
    pid = next(pid for pid, p in inv.passages.items() if p['text'] == phrase)
    schema = inv.keyed_schema([pid])
    ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    row = schema['$defs'][ref]
    assert row['properties']['k']['enum'] == [kind]
    if priority:
        assert row['properties']['priority']['enum'] == [priority]


@pytest.mark.parametrize('text', [
    'Podstawową znajomość programowania lub skryptowania (np. Python, Bash lub podobne).',
    'Bardzo dobrą znajomość języka polskiego (minimum C1) oraz języka angielskiego (minimum B2).',
])
def test_polish_qualification_modifiers_cannot_hide_candidate_conditions(text):
    from app.services.ollama_analysis import needs_assessment
    assert needs_assessment({'text': text, 'hints': []})


def test_revalidation_keeps_portal_levels_as_covered_metadata(profile):
    job = JobRequest(company='Synthetic', role='Engineer', job_description='Requirements\nKnowledge of Azure public cloud\nTECH STACK\nen\nB2\nWindows Server\nregular')
    inv = AnalysisInventory.build(job, profile)
    rows = [CompactAssessment(p=pid, k='requirement', n='Azure public cloud', why='Not documented.', priority='mandatory')
            if passage['text'] == 'Knowledge of Azure public cloud' else CompactAssessment(p=pid, k='context')
            for pid, passage in inv.passages.items()]
    first = AnalysisValidator(profile).validate(inv.expand(rows).to_analysis(job), f'{job.role}\n{job.job_description}', semantic=True)
    assert first.is_reliable
    for _ in range(4):
        first = AnalysisValidator(profile).validate(first, f'{job.role}\n{job.job_description}', semantic=True)
        assert first.is_reliable
        assert len(first.requirements) == 1
        assert not first.unassessed_source_passages


def test_candidate_tenure_cannot_be_invented_as_a_job_requirement(profile):
    from app.services.ollama_analysis import OllamaAnalysisError
    job = JobRequest(company='Synthetic', role='Engineer', job_description='Requirements\nFamiliarity with Linux administration')
    inv = AnalysisInventory.build(job, profile)
    pid = next(pid for pid, p in inv.passages.items() if p['text'].startswith('Familiarity'))
    row = CompactAssessment(p=pid, k='requirement', n='Linux administration', why='Not documented.', yrs=3)
    with pytest.raises(OllamaAnalysisError, match='invented or changed minimum tenure'):
        inv.validate_rows([row], [pid])
    schema = inv.keyed_schema([pid])
    ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    assert schema['$defs'][ref]['properties']['yrs'] == {'type': 'null'}
    # The independent final validator also rejects legacy/provider output that
    # bypasses the compact row validator; it cannot score against phantom years.
    rows = [row if source_id == pid else CompactAssessment(p=source_id, k='context') for source_id in inv.passages]
    candidate = inv.expand(rows).to_analysis(job)
    validated = AnalysisValidator(profile).validate(candidate, f'{job.role}\n{job.job_description}', semantic=True)
    assert not validated.is_reliable
    assert any('Minimum tenure not supported' in issue for issue in validated.classification_issues)
    assert all(r.required_years is None for r in validated.requirements)


def test_compound_languages_do_not_apply_polish_c1_to_english_b2(profile):
    from app.services.ollama_analysis import CompactComponent
    profile = profile.model_copy(deep=True)
    profile.skills['languages'] = ['Polish Native', 'English B2']
    quote = 'Bardzo dobrą znajomość języka polskiego (minimum C1) oraz języka angielskiego (minimum B2).'
    job = JobRequest(company='Synthetic', role='Engineer', job_description='Requirements\n' + quote)
    inv = AnalysisInventory.build(job, profile)
    pid = next(pid for pid, p in inv.passages.items() if p['text'] == quote)
    components = []
    for language, level in [('Polish', 'C1'), ('English', 'B2')]:
        match = inv.matcher._language(f'{language} {level}')
        assert match.status.value == 'strong'
        source_ids = {e.source_id for e in match.entries}
        ids = [fid for fid, entry in inv.evidence.items() if entry.source_id in source_ids]
        components.append(CompactComponent(n=language, lvl=level, s='strong', f=ids, why='Documented language level.'))
    rows = [CompactAssessment(p=source_id, k='requirement', n='Polish (C1) and English (B2) proficiency',
                              s='strong', priority='mandatory', lvl='C1/B2', op='all', c=components, why='Documented language levels.')
            if source_id == pid else CompactAssessment(p=source_id, k='context') for source_id in inv.passages]
    analysis = inv.expand(rows).to_analysis(job)
    for _ in range(3):
        analysis = AnalysisValidator(profile).validate(analysis, f'{job.role}\n{job.job_description}', semantic=True)
        assert analysis.is_reliable
        assert not analysis.evidence_issues
        assert analysis.requirements[0].status.value == 'strong'
        english = next(c for c in analysis.requirements[0].components if c.name == 'English')
        assert english.required_level == 'B2'
        assert english.status.value == 'strong'
