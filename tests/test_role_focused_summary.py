from app.models.candidate import CandidateProfile, Experience, Project
from app.models.job import JobRequest
from app.models.resume import ResumeProject
from app.services.fact_catalog import FactCatalog
from app.services.fact_validator import FactValidator
from app.services.professional_summary import build_summary, summary_contains_clause


def profile():
    return CandidateProfile(personal={'name': 'Synthetic Candidate'}, experience=[
        Experience(company='Example Ltd', title='Support Engineer', start='2023-01', end='Present',
                   facts=['Handles incident spikes and communicates with partners in English.'])], projects=[
        Project(name='LLM API lab', technologies=['Python', 'FastAPI'], facts=[
            'Integrated local Ollama models through an API with structured JSON outputs validated by Pydantic.']),
        Project(name='Academic ML thesis', technologies=['Python', 'pandas'], facts=[
            'Built a Python data pipeline for machine learning model comparison as part of an academic MSc thesis.',
            'Evaluated machine learning models in an academic MSc thesis.'])])


def test_data_science_summary_prefers_academic_model_evidence_over_support_or_llm_details():
    candidate = profile()
    candidate.summary_facts = ['Completed academic Agile training and a university course.']
    catalog = FactCatalog(candidate)
    incident = next(e for e in catalog.prompt_entries if 'Handles incident' in e.text)
    text, ids = build_summary(catalog, 'Junior Data Scientist\nPython, data, machine learning and LLM workflows.',
                             priorities={incident.source_id: 100})
    assert text.startswith('Support Engineer at Example Ltd.')
    assert 'academic MSc thesis' in text and 'machine learning' in text
    assert 'Handles incident' not in text
    assert 'Agile' not in text
    assert 'Project work' in text
    assert all(catalog.get(i) for i in ids)
    assert 'Data Scientist at' not in text


def test_data_engineering_keeps_pipeline_as_project_not_commercial_tenure():
    text, _ = build_summary(FactCatalog(profile()), 'Data Engineer\nPython data pipelines and SQL.')
    assert 'data pipeline' in text
    assert 'Project work' in text and 'academic' in text
    assert 'years' not in text and 'commercial' not in text


def test_project_ranking_favors_the_actual_ml_thesis_for_data_scientist():
    candidate = profile()
    validator = FactValidator(candidate)
    projects = [ResumeProject(name=p.name, description=p.facts[0], technologies=p.technologies,
                              source_fact_ids=[e.source_id for e in validator.catalog.prompt_entries
                                               if e.kind == 'project' and e.owner_name == p.name and ':fact:' in e.source_id])
                for p in candidate.projects]
    ranked = validator._rank_projects(projects, JobRequest(company='Synthetic', role='Data Scientist',
                                                           job_description='Python machine learning and AI APIs.'))
    assert ranked[0].name == 'Academic ML thesis'


def test_compact_summary_omits_a_whole_overlong_clause_never_cuts_a_sentence():
    candidate = profile()
    candidate.projects[0].facts = ['Implemented an API integration ' + 'with verified source checks ' * 12 + 'in a personal project.']
    text, ids = build_summary(FactCatalog(candidate), 'AI Engineer\nAPI integration.', compact=True)
    assert len(text) <= 500 and text.endswith('.')
    assert 'in a personal project.' in text or 'Implemented an API integration' not in text
    assert ids


def test_source_bound_background_is_not_mechanical_experienced_label():
    candidate = profile()
    candidate.summary_facts = ['Experienced in Windows, application and network troubleshooting.']
    catalog = FactCatalog(candidate)
    text, _ = build_summary(catalog, 'Support Engineer', compact=True)
    assert 'Background: Experienced' not in text
    assert 'Broader experience includes Windows' in text
    assert summary_contains_clause(text, candidate.summary_facts[0])
