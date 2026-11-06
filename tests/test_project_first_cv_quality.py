"""Synthetic regressions: target-role relevance without invented qualifications."""
import pytest

from app.models.candidate import CandidateProfile, Experience, Project
from app.models.job import JobAnalysis, JobRequest, JobRequirement
from app.models.skills import SkillEvidence, SkillsDocument, VerifiedSkill
from app.services.analysis_validator import AnalysisValidator
from app.services.evidence_matching import required_years
from app.services.fact_catalog import FactCatalog
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment, needs_assessment
from app.services.professional_summary import build_summary
from app.services.role_focus import role_family, role_focus_score
from app.services.skills_bank import SkillsBank


@pytest.fixture
def project_profile():
    return CandidateProfile(personal={'name': 'Synthetic Candidate'}, experience=[
        Experience(company='Example Support', title='Support Engineer', start='2024-01', end='Present',
                   facts=['Handles support incidents and investigates network issues.'])], projects=[
        Project(name='Synthetic LLM integration', facts=[
            'Integrated local Ollama models through a FastAPI API with structured JSON outputs validated by Pydantic.',
            'Built n8n automation workflows integrating REST APIs using Python.']),
        Project(name='Synthetic academic study', facts=[
            'Evaluated machine learning models as part of an academic MSc thesis.'])])


@pytest.mark.parametrize('title', ['AI Analyst', 'AI Architect', 'AI Inżynierka / AI Inżynier',
                                  'AI Implementation & Automation Specialist', 'Forward Deployed Engineer'])
def test_project_evidence_beats_support_priorities_for_ai_and_development_roles(project_profile, title):
    catalog = FactCatalog(project_profile)
    support = next(e for e in catalog.prompt_entries if 'Handles support' in e.text)
    text, ids = build_summary(catalog, title + '\nPython APIs and troubleshooting.',
                              compact=True, priorities={support.source_id: 100})
    assert text.startswith('Support Engineer at Example Support.')
    assert 'Project work' in text and ('FastAPI' in text or 'n8n' in text)
    assert 'Handles support' not in text
    assert len(text) <= 500 and text.endswith('.')
    assert all(catalog.get(source) for source in ids)
    assert not any(word in text for word in ['Azure', 'MCP', 'embeddings', 'vector databases'])
    assert title + ' at ' not in text


def test_support_title_is_not_reclassified_by_ai_words_in_description():
    assert role_family('Technical Support Engineer\nAI, FastAPI and LLM tools.') == 'support'
    assert role_focus_score('Integrated local Ollama models with FastAPI.', 'Technical Support Engineer') == 0
    assert role_family('Unknown job\nAI Architect') == 'other'


def bank(tmp_path, profile):
    technologies = ['Python', 'FastAPI', 'Pydantic', 'REST API integration', 'HTTPX', 'Ollama', 'n8n']
    generic = ['Incident handling', 'Tier 2 Support', 'Network troubleshooting', 'Technical documentation',
               'Active Directory', 'Windows administration']
    skills = [VerifiedSkill(id=f'skill_synthetic_{i}', name=name, category='AI / ML' if name in technologies else 'Support / Operations',
                            level='basic', priority=5 if name in technologies else 10,
                            verified=True, allowed_in_cv=True,
                            evidence=[SkillEvidence(source_type='manual_verified', source_id=f'manual:synthetic:{i}',
                                                    description=f'Project evidence of {name}.')])
              for i, name in enumerate(technologies + generic)]
    path = tmp_path / 'skills.json'
    path.write_text(SkillsDocument(skills=skills).model_dump_json())
    return SkillsBank(path, profile)


@pytest.mark.parametrize('title', ['AI Analyst', 'AI Architect', 'Forward Deployed Engineer',
                                  'AI Inżynierka / AI Inżynier'])
def test_technical_skills_remain_visible_before_support_fillers(tmp_path, project_profile, title):
    skills = bank(tmp_path, project_profile)
    chosen = skills.select_for_job([], title + '\nSupport incidents, networks and technical documentation. Python APIs.',
                                   minimum=10, maximum=10)
    assert len(chosen) == 10
    assert all(s.level == 'basic' and skills.eligible(s) for s in chosen)
    assert any(s.name == 'FastAPI' for s in chosen[:5])
    assert any(s.name == 'REST API integration' for s in chosen[:5])
    assert not any(s.category == 'Support / Operations' for s in chosen[:5])


def test_manual_skill_selection_is_not_expanded_or_replaced(tmp_path, project_profile):
    skills = bank(tmp_path, project_profile)
    chosen = skills.select_for_job(['skill_synthetic_7'], 'AI Architect\nFastAPI and LLMs.',
                                   minimum=0, maximum=10, requested_only=True)
    assert [s.id for s in chosen] == ['skill_synthetic_7']


@pytest.mark.parametrize('quote,years', [
    ('Masz co najmniej 3 lata doświadczenia w inżynierii danych.', 3),
    ('Minimum 2 letnie doświadczenie w tej lub podobnej roli.', 2),
    ('Minimum 2-letnie doświadczenie w tej lub podobnej roli.', 2),
])
def test_polish_minimum_tenure_is_not_hidden_as_context(project_profile, quote, years):
    assert required_years(quote) == years
    assert needs_assessment({'text': quote, 'hints': ['mandatory']})
    assert_context_rejected(project_profile, 'Requirements', quote)


@pytest.mark.parametrize('quote', [
    'AI & Agentic Engineering: Deep understanding of modern AI patterns including MCP.',
    'System Architecture & Ownership: Demonstrated ability to make foundational platform decisions.',
    'You read API documentation and get a working connection independently.',
    'You build test sets before go-live and extract data from contracts and invoices.',
    'You use and build with coding agents every day.',
    'Codziennej, praktycznej pracy z agentami AI w procesie wytwarzania oprogramowania.',
    'Bardzo dobrze znasz Pythona i SQL.',
    'Pracowałeś(-aś) z dużymi wolumenami danych w środowisku produkcyjnym.',
])
def test_required_capabilities_cannot_disappear_from_complete_source_map(project_profile, quote):
    assert_context_rejected(project_profile, 'Must have', quote)


def assert_context_rejected(profile, heading, quote):
    job = JobRequest(company='Synthetic', role='AI Engineer', job_description=heading + '\n' + quote)
    inv = AnalysisInventory.build(job, profile)
    pid = next(pid for pid, passage in inv.passages.items() if passage['text'] == quote)
    assert needs_assessment(inv.passages[pid])
    rows = [CompactAssessment(p=p, k='context') for p in inv.passages]
    report = AnalysisValidator(profile).validate(inv.expand(rows).to_analysis(job),
                                                 job.role + '\n' + job.job_description, semantic=True)
    assert not report.is_reliable
    assert report.recommendation == 'RETRY'
    assert quote in report.unassessed_source_passages


def test_second_person_duties_are_not_forced_to_qualifications():
    assert not needs_assessment({'text': 'You build reports for the team.', 'hints': ['responsibility']})
    assert not needs_assessment({'text': 'You use free parking.', 'hints': ['benefits']})


def test_general_employment_years_do_not_prove_similar_specialist_role(project_profile):
    project_profile.experience[0].start = '2020-01'
    validator = AnalysisValidator(project_profile)
    quote = 'At least 3 years of experience in a similar role.'
    candidate = JobAnalysis(company='Synthetic', role='AI Analytics Engineer', strong_matches=[],
                            partial_matches=[], missing_requirements=[], recommendation='APPLY', match_level='HIGH',
                            requirements=[JobRequirement(name='Relevant experience', source_quote=quote,
                                priority='mandatory', status='strong', source_fact_ids=[e.source_id for e in validator.matcher.entries
                                                                                       if e.kind == 'experience'])])
    checked = validator.validate(candidate, 'Requirements\n' + quote, semantic=True)
    req = next(r for r in checked.requirements if r.source_quote == quote)
    assert req.status != 'strong'
    assert checked.recommendation not in {'APPLY', 'REASONABLE_STRETCH'}


@pytest.mark.parametrize('quote', [
    'Demonstrated ability to make and defend foundational platform decisions and govern platform-level standards.',
    'Minimum 2 years of professional experience in a large organization.',
])
def test_project_or_generic_support_is_not_architectural_ownership_or_org_size(project_profile, quote):
    from app.services.named_evidence import named_scope_ceiling
    entries = FactCatalog(project_profile).prompt_entries
    ceiling = named_scope_ceiling(quote, entries)
    assert ceiling and ceiling[0] != 'strong'
