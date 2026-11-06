from app.models.candidate import CandidateProfile, Project
from app.services.fact_catalog import FactCatalog
from app.services.professional_summary import build_summary


def test_pipeline_description_and_fact_do_not_repeat_the_same_topic():
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'}, projects=[Project(
        name='Synthetic data study', description='Python data pipeline for sensor estimation and comparison of multiple machine learning models.',
        facts=['Built a Python pipeline for sensor estimation.'])])
    text, ids = build_summary(FactCatalog(profile), 'Data Engineer\nPython data pipelines')
    assert text.casefold().count('pipeline') == 1
    assert ids and 'Project work' in text


def test_model_comparison_prefers_complete_thesis_provenance():
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'}, projects=[Project(
        name='Synthetic ML study', description='Python data pipeline and comparison of multiple machine learning models.',
        facts=['Evaluated multiple machine learning models as part of the MSc thesis.'])])
    catalog = FactCatalog(profile)
    text, ids = build_summary(catalog, 'Junior Data Scientist\nMachine learning models and Python')
    assert text.casefold().count('machine learning models') == 1
    assert 'MSc thesis' in text and 'Project work' in text
    assert any('MSc thesis' in catalog.get(i).text for i in ids)


def test_distinct_project_topics_are_not_deduplicated():
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'}, projects=[Project(
        name='Synthetic API lab', facts=['Integrated local models through a JSON API.',
                                       'Implemented evidence validation with Pydantic.'])])
    text, ids = build_summary(FactCatalog(profile), 'AI Engineer\nLocal models, JSON API, Pydantic evidence validation')
    assert 'JSON API' in text and 'Pydantic' in text
    assert len(ids) == 2
