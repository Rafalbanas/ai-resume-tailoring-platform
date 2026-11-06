import pytest

from app.models.candidate import CandidateProfile, Project
from app.models.job import JobRequest, JobRequirement
from app.services.analysis_validator import AnalysisValidator
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment
from app.services.semantic_requirements import _facts
from app.services.source_dispositions import explicit_skill_condition


@pytest.mark.parametrize('quote', [
    'Praktyczne doświadczenie w administracji bezpieczeństwem.',
    'Rozumienie zasad bezpieczeństwa danych.',
    'Zrozumienie koncepcji Zero Trust.',
    'Dobre zrozumienie podstaw sieci korporacyjnych.',
    'Wysokie umiejętności komunikacyjne i sprawna praca w zespole,',
    'Język niemiecki',
    'Język niemiecki – mile widziany.',
    'Język angielski (B2+)',
    'Język angielski na poziomie zaawansowanym.',
])
def test_explicit_polish_qualification_requires_assessment(quote):
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'})
    job = JobRequest(company='Synthetic', role='Engineer', job_description='Twój profil zawodowy i kwalifikacje\n' + quote)
    inventory = AnalysisInventory.build(job, profile)
    pid = next(p for p, row in inventory.passages.items() if row['text'] == quote)
    schema = inventory.keyed_schema([pid])
    ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    assert schema['$defs'][ref]['properties']['k']['enum'] == ['requirement']
    rows = [CompactAssessment(p=p, k='responsibility' if p == pid else 'context')
            for p in inventory.passages]
    report = AnalysisValidator(profile).validate(inventory.expand(rows).to_analysis(job),
                                                 job.role + '\n' + job.job_description, semantic=True)
    assert not report.is_reliable and quote in report.unassessed_source_passages


@pytest.mark.parametrize('quote', ['Python', 'English B2', 'Monitorowanie bezpieczeństwa sieci.',
                                  'Rozwijanie umiejętności zespołu.', 'Nasz język komunikacji to angielski.',
                                  'Język angielski jest językiem komunikacji w naszej firmie.'])
def test_tags_and_actions_are_not_forced_to_qualifications(quote):
    assert not explicit_skill_condition(quote)


@pytest.mark.parametrize('quote', ['Język angielski na poziomie zaawansowanym.', 'English C1 is required.'])
def test_advanced_polish_language_quote_is_not_weakened_by_b2_label(quote):
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'},
                               projects=[Project(name='Synthetic', facts=['Uses English at B2 level in daily professional work.'])])
    validator = AnalysisValidator(profile)
    req = JobRequirement(name='English B2', source_quote=quote,
                         status='strong', reason='Model assessment.',
                         source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status != 'strong'
