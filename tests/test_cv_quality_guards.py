"""Synthetic regressions for source priorities, specialist tenure and CV scope."""
from datetime import date

import pytest

from app.models.candidate import Project
from app.models.job import JobAnalysis, JobRequest, JobRequirement
from app.models.resume import TailoredResume
from app.services.analysis_validator import AnalysisValidator
from app.services.evidence_matching import EvidenceMatcher, required_years
from app.services.fact_catalog import FactCatalog
from app.services.fact_validator import FactValidator
from app.services.job_sections import extract_sections
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment, assessment_priority
from app.services.professional_summary import build_summary
from app.services.summary_confirmation import summary_review
from app.services.summary_review import sign_summary, valid_source_summary, valid_summary_attestation


def analysis(**values):
    return JobAnalysis(company='Synthetic', role='Engineer', strong_matches=[], partial_matches=[],
                       missing_requirements=[], recommendation='REVIEW', match_level='LOW', **values)


def test_polish_natural_headings_separate_qualifications_duties_and_benefits():
    text = '''JOB DESCRIPTION
Our team builds useful products.
Jakie działania będą należeć do Ciebie?
Przeprowadzanie testów aplikacji.
Jakie kompetencje są dla nas ważne?
Minimum 3–4 lata komercyjnego doświadczenia w testach penetracyjnych.
Biegłość w obsłudze narzędzi bezpieczeństwa.
Co zyskujesz, dołączając do Example?
Flexible working hours.
TECH STACK
Linux'''
    units, _ = extract_sections(text)
    categories = {u.quote: u.category for u in units}
    assert categories['Przeprowadzanie testów aplikacji.'] == 'responsibility'
    assert categories['Minimum 3–4 lata komercyjnego doświadczenia w testach penetracyjnych.'] == 'mandatory'
    assert categories['Biegłość w obsłudze narzędzi bezpieczeństwa.'] == 'mandatory'
    assert categories['Flexible working hours.'] == 'benefits'
    assert categories['Linux'] == 'competency'


@pytest.mark.parametrize('heading', ["Ideally, you’ll also have", "Ideally, you'll also have:"])
def test_english_natural_headings_preserve_optional_section(heading):
    units, _ = extract_sections(f'To qualify for the role, you must have\n8+ years experience in security.\n{heading}\nSecurity certification.')
    assert units[0].category == 'mandatory'
    assert units[1].category == 'preferred'


@pytest.mark.parametrize('quote,years', [
    ('Minimum 3-4 lata komercyjnego doświadczenia w testach penetracyjnych.', 3),
    ('Min. 4 lata doświadczenia w inżynierii danych.', 4),
    ('Co najmniej 1 rok doświadczenia w inżynierii danych.', 1),
    ('At least 3–5 years of experience in data engineering.', 3),
    ('8+ years of experience in security consulting.', 8),
])
def test_literal_minimum_is_assessable_without_a_recognized_heading(quote, years):
    assert required_years(quote) == years
    assert assessment_priority({'text': quote, 'hints': []}) == 'mandatory'


def test_complete_context_map_cannot_hide_polish_minimum(profile):
    quote = 'Minimum 3–4 lata komercyjnego doświadczenia w testach penetracyjnych.'
    job = JobRequest(company='Synthetic', role='Security specialist', job_description='JOB DESCRIPTION\n' + quote)
    inventory = AnalysisInventory.build(job, profile)
    candidate = inventory.expand([CompactAssessment(p=pid, k='context') for pid in inventory.passages]).to_analysis(job)
    checked = AnalysisValidator(profile).validate(candidate, job.job_description, semantic=True)
    assert not checked.is_reliable
    assert checked.recommendation != 'APPLY'
    assert quote in checked.unassessed_source_passages


@pytest.mark.parametrize('classified', [False, True])
def test_model_cannot_downgrade_explicit_minimum_to_preferred(profile, classified):
    quote = 'Min. 4 lata doświadczenia w inżynierii danych.'
    candidate = analysis(requirements=[JobRequirement(name='Data engineering experience', source_quote=quote,
        priority='preferred', status='missing', reason='No documented specialist duties.')])
    if classified:
        candidate.source_context = [{'name': 'Requirements', 'source_quote': 'Requirements'}]
    result = AnalysisValidator(profile).validate(candidate, 'Requirements\n' + quote, semantic=True)
    requirement = next(r for r in result.requirements if r.source_quote == quote)
    assert requirement.priority == 'mandatory'
    assert requirement.required_years == 4
    assert result.recommendation not in {'APPLY', 'REASONABLE_STRETCH'}


def test_preferred_tenure_stays_optional(profile):
    quote = '3 years of data engineering experience preferred.'
    candidate = analysis(requirements=[JobRequirement(name='Data engineering experience', source_quote=quote,
        priority='preferred', status='missing', reason='No documented specialist duties.')])
    result = AnalysisValidator(profile).validate(candidate, 'Preferred qualifications\n' + quote, semantic=True)
    assert all(r.priority != 'mandatory' for r in result.requirements)


@pytest.mark.parametrize('scope', ['4 years of data engineering experience',
                                 '3 years of infrastructure penetration testing experience',
                                 '8 years of Cybersecurity and AI Security experience'])
def test_general_support_duties_cannot_supply_specialist_years(profile, scope):
    profile.experience[0].start = '2020-01'
    profile.experience[0].facts = ['Administered Windows infrastructure and used SQL for operational troubleshooting.',
                                  'Prepared team onboarding documentation.',
                                  'No commercial experience in penetration testing or data engineering.',
                                  'Brak komercyjnego doświadczenia w testach penetracyjnych.']
    matcher = EvidenceMatcher(FactCatalog(profile), as_of=date(2026, 1, 1))
    ids = [e.source_id for e in matcher.entries if e.kind == 'experience']
    result = matcher.cited_tenure(ids, 3, scope=scope)
    assert result.observed_years == 0
    assert result.status != 'strong'
    assert not result.entries


@pytest.mark.parametrize('fact,scope', [
    ('Built and maintained ETL data pipelines for the warehouse.', '3 years of data engineering experience'),
    ('Performed infrastructure penetration testing for clients.', '3 years of infrastructure penetration testing experience'),
    ('Delivered information security architecture assessments for clients.', '3 years of information security experience'),
])
def test_explicit_specialist_employment_can_supply_years(profile, fact, scope):
    profile.experience[0].start = '2022-01'
    profile.experience[0].facts = [fact]
    matcher = EvidenceMatcher(FactCatalog(profile), as_of=date(2026, 1, 1))
    ids = [e.source_id for e in matcher.entries if e.kind == 'experience']
    assert matcher.cited_tenure(ids, 3, scope=scope).status == 'strong'
    assert matcher.match(scope).status == 'strong'


@pytest.mark.parametrize('specialist', [False, True])
def test_final_validator_checks_specialist_scope_of_model_tenure_citations(profile, specialist):
    profile.experience[0].start = '2018-01'
    profile.experience[0].facts = (['Built ETL data pipelines for an operational warehouse.'] if specialist
                                   else ['Used SQL queries for operational troubleshooting.'])
    validator = AnalysisValidator(profile)
    validator.matcher = EvidenceMatcher(validator.catalog, as_of=date(2026, 1, 1))
    ids = [e.source_id for e in validator.catalog.prompt_entries if e.kind == 'experience']
    quote = 'Minimum 4 years of data engineering experience.'
    candidate = analysis(requirements=[JobRequirement(name='Data engineering experience', source_quote=quote,
        priority='mandatory', status='strong', source_fact_ids=ids, reason='Cited dated employment.')])
    result = validator.validate(candidate, 'Requirements\n' + quote, semantic=True)
    req = next(r for r in result.requirements if r.source_quote == quote)
    assert req.required_years == 4
    if specialist:
        assert req.observed_years >= 4
        assert req.status == 'strong'
        assert result.recommendation == 'APPLY'
    else:
        assert req.observed_years == 0
        assert req.status != 'strong'
        assert result.recommendation != 'APPLY'


def test_summary_explicitly_separates_project_work_from_employer(profile):
    profile.projects = [Project(name='API lab', facts=['Integrated local models into a FastAPI application.'], technologies=['FastAPI'])]
    catalog = FactCatalog(profile)
    text, ids = build_summary(catalog, 'AI developer\nRequirements\nFastAPI local models integration')
    assert 'Support Engineer at Example Ltd.' in text
    assert 'Project work includes integrating local models' in text
    assert any(catalog.get(source).kind == 'project' for source in ids)


def test_approved_summary_cannot_silently_move_project_work_into_employment(profile):
    fact = 'Integrated local models into a FastAPI application.'
    profile.projects = [Project(name='API lab', facts=[fact], technologies=['FastAPI'])]
    catalog = FactCatalog(profile)
    project_id = next(e.source_id for e in catalog.prompt_entries if e.kind == 'project' and e.text == fact)
    resume = TailoredResume(headline='Support Engineer', professional_summary=fact,
                            summary_source_fact_ids=[project_id], core_skills=[], experience=[])
    resume.summary_attestation = sign_summary(resume, profile, 'synthetic-key')
    job = JobRequest(company='Synthetic', role='AI developer', job_description='Requirements\nFastAPI local models integration.')
    checked = FactValidator(profile, review_key='synthetic-key').validate(resume, job).resume
    assert 'Project work includes' in checked.professional_summary
    assert valid_source_summary(checked, profile, 'synthetic-key')
    assert not valid_summary_attestation(checked, profile, 'synthetic-key')
    second = FactValidator(profile, review_key='synthetic-key').validate(checked, job).resume
    assert second.professional_summary == checked.professional_summary


def test_scoped_model_review_still_requires_owner_confirmation(profile):
    fact = 'Integrated local models into a FastAPI application.'
    profile.projects = [Project(name='API lab', facts=[fact], technologies=['FastAPI'])]
    catalog = FactCatalog(profile)
    source = next(e.source_id for e in catalog.prompt_entries if e.kind == 'project' and e.text == fact)
    text = 'In a project, integrated local models into a FastAPI application.'
    resume = TailoredResume(headline='Support Engineer', professional_summary=text,
                            summary_source_fact_ids=[source], core_skills=[], experience=[])
    resume.summary_attestation = sign_summary(resume, profile, 'synthetic-key')
    job = JobRequest(company='Synthetic', role='AI developer', job_description='Requirements\nFastAPI local models integration.')
    checked = FactValidator(profile, review_key='synthetic-key').validate(resume, job).resume
    assert checked.professional_summary == text
    assert valid_summary_attestation(checked, profile, 'synthetic-key')
    assert summary_review(checked, profile, 'synthetic-key', 'synthetic-account:document')['required']


def test_project_relevance_beats_an_unrelated_high_priority_citation(profile):
    profile.projects = [Project(name='Academic model comparison', facts=['Compared machine learning models.'],
                                technologies=['Python', 'NumPy']),
                        Project(name='API lab', facts=['Integrated local models using FastAPI and REST APIs.'],
                                technologies=['Python', 'FastAPI', 'REST API', 'Ollama'])]
    validator = FactValidator(profile)
    academic = next(e for e in validator.catalog.prompt_entries if e.kind == 'project' and e.owner_index == 0)
    validator.fact_priorities = {academic.source_id: 100}
    from app.models.resume import ResumeProject
    projects = [ResumeProject(name=p.name, description=p.facts[0], technologies=p.technologies,
                              source_fact_ids=[e.source_id for e in validator.catalog.prompt_entries
                                               if e.kind == 'project' and e.owner_name == p.name]) for p in profile.projects]
    job = JobRequest(company='Synthetic', role='AI API developer', job_description='Requirements\nFastAPI REST API Ollama integration.')
    assert validator._rank_projects(projects, job)[0].name == 'API lab'
