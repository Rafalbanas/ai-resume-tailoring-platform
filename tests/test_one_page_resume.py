from copy import deepcopy
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.models.candidate import Project
from app.models.resume import ResumeBullet, ResumeExperience, ResumeLearningSkill, ResumeProject, TailoredResume
from app.services.fact_validator import FactValidator
from app.services.one_page_resume import select_one_page
from app.services.pdf_generator import PDFGenerator


def sample(profile):
    profile.projects = [Project(name='Synthetic Python utility', description='Built a Python utility.', technologies=['Python'], facts=['Built a Python utility.'])]
    validator = FactValidator(profile)
    summary = next(e for e in validator.catalog.prompt_entries if e.kind == 'summary')
    project = next(e for e in validator.catalog.prompt_entries if e.kind == 'project' and ':fact:' in e.source_id)
    owner = profile.projects[project.owner_index]
    resume = TailoredResume(headline='Support Engineer', professional_summary=summary.text,
        summary_source_fact_ids=[summary.source_id], core_skills=['Basic Python'],
        experience=[ResumeExperience(company='Synthetic Kabe', title='Support', dates='2020–2022',
            bullets=[ResumeBullet(text='Used MS SQL Server and T-SQL for operational queries.',source_fact_ids=['old-sql']),
                     ResumeBullet(text='Used SQL and T-SQL queries for operational troubleshooting and data verification.',source_fact_ids=['sql'])])],
        projects=[ResumeProject(name=owner.name,description=owner.facts[0],source_fact_ids=[project.source_id])],
        currently_learning=[ResumeLearningSkill(skill_id='skill_kubernetes',name='Kubernetes',status='Course in progress')])
    return validator,resume


def test_sql_dedup_keeps_specific_statement_and_citations(profile):
    validator, resume = sample(profile)
    original = deepcopy(resume)
    fitted, actions = select_one_page(resume, validator, 'SQL', lambda r: True)
    assert len(fitted.experience[0].bullets)==1
    assert fitted.experience[0].bullets[0].text == original.experience[0].bullets[1].text
    assert fitted.experience[0].bullets[0].source_fact_ids == ['old-sql', 'sql']
    assert fitted.core_skills == original.core_skills
    assert fitted.currently_learning == original.currently_learning
    assert resume == original
    assert actions


def test_concise_summary_and_project_use_exact_sources(profile):
    validator,resume=sample(profile)
    resume.professional_summary += ' ' + 'Long saved wording. '*12
    resume.projects[0].description += ' ' + 'Additional saved project detail. '*12
    result,_=select_one_page(resume,validator,'Python Linux',lambda r: len(r.professional_summary)<300 and len(r.projects[0].description)<300)
    assert validator.catalog.supports_paraphrase(result.professional_summary,result.summary_source_fact_ids)
    assert validator.catalog.supports_paraphrase(result.projects[0].description,result.projects[0].source_fact_ids)
    assert not result.summary_attestation


def test_impossible_fit_does_not_hide_learning_or_employment(profile):
    validator,resume=sample(profile)
    before=resume.model_dump()
    with pytest.raises(ValueError,match='Select ATS Classic'):
        select_one_page(resume,validator,'Python',lambda r: False)
    assert resume.model_dump()==before


def test_manual_fit_remains_non_destructive(profile,tmp_path):
    _,resume=sample(profile)
    generator=PDFGenerator(Path('templates'),Path('static'),tmp_path)
    fitted,_=generator.fit_resume(resume,profile)
    assert fitted==resume


def test_generated_modern_pdf_one_page_keeps_levels_and_learning(profile,tmp_path):
    validator,resume=sample(profile)
    generator=PDFGenerator(Path('templates'),Path('static'),tmp_path)
    fitted,_=generator.fit_resume(resume,profile,one_page=True,fact_validator=validator)
    output=tmp_path/'cv.pdf'
    generator.generate(fitted,profile,output,template_name='modern_sidebar')
    reader=PdfReader(output)
    assert len(reader.pages)==1
    text=' '.join(p.extract_text() for p in reader.pages)
    assert 'Basic Python' in text
    assert 'Kubernetes' in text and 'Course in progress' in text
    assert 'operational troubleshooting and data verification' in text


def test_ats_keeps_full_content_even_with_one_page_flag(profile,tmp_path):
    _,resume=sample(profile)
    generator=PDFGenerator(Path('templates'),Path('static'),tmp_path)
    fitted,_=generator.fit_resume(resume,profile,template_name='ats_classic',one_page=True)
    assert fitted==resume


def test_mandatory_source_evidence_is_not_removed(profile):
    from types import SimpleNamespace
    validator, resume = sample(profile)
    validator.analysis = SimpleNamespace(requirements=[SimpleNamespace(priority='mandatory', status='strong', source_fact_ids=['old-sql'])],role_competencies=[])
    result,_ = select_one_page(resume,validator,'SQL',lambda r: len(r.experience[0].bullets)==1)
    assert result.experience[0].bullets[0].source_fact_ids==['old-sql', 'sql']
    assert result.experience[0].company==resume.experience[0].company
    assert result.experience[0].dates==resume.experience[0].dates


def test_photo_overflow_compacts_to_one_page(profile,tmp_path):
    from PIL import Image
    validator,resume=sample(profile)
    text='Built the verified Python utility and documented integration testing, deployment and operational troubleshooting. '
    resume.projects[0].description=' '.join(text.rstrip().rstrip('.') + f' in scenario {i}.' for i in range(40))
    profile.projects[0].description=resume.projects[0].description
    generator=PDFGenerator(Path('templates'),Path('static'),tmp_path)
    generator.photo_store.directory.mkdir(parents=True)
    Image.new('RGB',(80,80),'gray').save(generator.photo_store.jpg_path)
    original=generator._render_document(generator.render_html(resume,profile,photo_enabled=True))
    assert len(original.pages)>1
    fitted,_=generator.fit_resume(resume,profile,one_page=True,fact_validator=validator)
    output=tmp_path/'photo-cv.pdf'
    generator.generate(fitted,profile,output,photo_enabled=True)
    assert len(PdfReader(output).pages)==1
    assert fitted.currently_learning==resume.currently_learning


def test_small_continuation_does_not_prevent_safe_selection(profile,tmp_path,monkeypatch):
    validator,resume=sample(profile)
    generator=PDFGenerator(Path('templates'),Path('static'),tmp_path)
    calls=[]
    def fits(*args):
        calls.append(True)
        if len(calls)==1:
            raise ValueError('A nearly empty continuation page remains; review content before export.')
        return True
    monkeypatch.setattr(generator,'_fits_one_page',fits)
    fitted,_=generator.fit_resume(resume,profile,one_page=True,fact_validator=validator)
    assert fitted.currently_learning==resume.currently_learning
    assert len(calls)>1


def test_generation_failure_explains_field_and_does_not_save_partial_cv(monkeypatch,resume_payload):
    from fastapi.testclient import TestClient

    from app.main import app
    from tests.test_provider_fallback import job, sample_workflow_response
    from tests.test_recording_demo import sign_in
    with TestClient(app) as client:
        sign_in(client)
        response=sample_workflow_response('mock','fixture')
        response.resume=TailoredResume.model_validate(resume_payload)
        draft=app.state.storage.save_draft(job(),response)
        before=list(app.state.storage.generated_dir.iterdir())
        def reject(*args,**kwargs):
            assert kwargs['one_page'] is True
            assert isinstance(kwargs['fact_validator'],FactValidator)
            raise ValueError('Modern Sidebar cannot fit one page. Select ATS Classic.')
        monkeypatch.setattr(app.state.pdf_generator,'fit_resume',reject)
        result=client.post(f'/generate/{draft}',data={'csrf_token':client.cookies.get('csrf_token'),'template_name':'modern_sidebar'},follow_redirects=False)
        assert result.status_code==422
        assert 'Select ATS Classic' in result.text
        assert list(app.state.storage.generated_dir.iterdir())==before


def required_summary_fixture(profile, texts):
    from types import SimpleNamespace
    profile.summary_facts = texts
    validator, resume = sample(profile)
    entries = [entry for entry in validator.catalog.prompt_entries if entry.kind == 'summary']
    resume.summary_source_fact_ids = [entry.source_id for entry in entries]
    resume.professional_summary = ' '.join(texts) + ' Additional saved explanation. ' * 8
    resume.summary_attestation = 'old-review'
    validator.analysis = SimpleNamespace(requirements=[SimpleNamespace(priority='mandatory', status='partial',
        source_fact_ids=resume.summary_source_fact_ids)], role_competencies=[])
    return validator, resume


def test_three_required_summary_facts_can_shorten_without_dropping_evidence(profile):
    texts = ['Uses Linux to investigate documented operational incidents.',
             'Writes verified Python scripts for operational automation.',
             'Uses English at B2 level in documented professional work.']
    validator, resume = required_summary_fixture(profile, texts)
    original = deepcopy(resume)
    fitted, _ = select_one_page(resume, validator, 'Python Linux', lambda r: len(r.professional_summary) < 230)
    assert set(fitted.summary_source_fact_ids) == set(original.summary_source_fact_ids)
    assert all(text in fitted.professional_summary for text in texts)
    assert validator.catalog.supports_paraphrase(fitted.professional_summary, fitted.summary_source_fact_ids)
    assert not fitted.summary_attestation
    assert resume == original


def test_required_summary_over_length_budget_is_not_silently_dropped(profile):
    texts = ['Verified Linux incident handling and investigation. ' * 3,
             'Verified Python automation and operational scripting. ' * 3,
             'Verified English communication in technical support. ' * 3]
    validator, resume = required_summary_fixture(profile, texts)
    original = deepcopy(resume)
    seen = []
    def fits(value):
        seen.append(deepcopy(value))
        return False
    with pytest.raises(ValueError, match='Select ATS Classic'):
        select_one_page(resume, validator, 'Python Linux', fits)
    assert all(value.professional_summary == original.professional_summary for value in seen)
    assert all(value.summary_source_fact_ids == original.summary_source_fact_ids for value in seen)
    assert resume == original
