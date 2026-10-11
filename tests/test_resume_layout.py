from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from app.main import app
from app.models.resume import TailoredResume
from tests.test_provider_fallback import job, sample_workflow_response
from tests.test_recording_demo import sign_in


def setup_exports(monkeypatch):
    calls=[]
    def pdf(resume, profile, output, *args, **kwargs):
        calls.append(('pdf',kwargs['template_name']))
        output.write_bytes(b'%PDF '+kwargs['template_name'].encode())
    def docx(resume, profile, output, **kwargs):
        calls.append(('docx',kwargs['template_name']))
        output.write_bytes(b'PK '+kwargs['template_name'].encode())
    monkeypatch.setattr(app.state.pdf_generator,'generate',pdf)
    monkeypatch.setattr(app.state,'docx_generator',docx)
    ai=AsyncMock(side_effect=AssertionError('Layout change must not call AI'))
    monkeypatch.setattr(app.state.provider,'tailor',ai)
    return calls,ai


def test_layout_persistence_exports_content_isolation(monkeypatch,resume_payload):
    with TestClient(app) as client:
        sign_in(client)
        calls,ai=setup_exports(monkeypatch)
        response=sample_workflow_response('mock','fixture')
        resume=TailoredResume.model_validate(resume_payload)
        first,folder=app.state.storage.save_application(job(),response.analysis,resume,[],template_name='ats_classic')
        second,_=app.state.storage.save_application(job(),response.analysis,resume,[],template_name='ats_classic')
        before=(folder/'resume.json').read_bytes()
        baseline=(folder/'resume.generated.json').read_bytes()
        token=client.cookies.get('csrf_token')
        assert client.post(f'/preview/{first}/layout',data={'template_name':'modern_sidebar'}).status_code==403
        assert client.post(f'/preview/{first}/layout',data={'csrf_token':token,'template_name':'unknown'}).status_code==422
        result=client.post(f'/preview/{first}/layout',data={'csrf_token':token,'template_name':'modern_sidebar'},follow_redirects=False)
        assert result.status_code==303
        assert app.state.storage.load_application(first)[3]['template_name']=='modern_sidebar'
        assert app.state.storage.load_application(second)[3]['template_name']=='ats_classic'
        assert (folder/'resume.json').read_bytes()==before
        assert (folder/'resume.generated.json').read_bytes()==baseline
        assert calls==[('pdf','modern_sidebar'),('docx','modern_sidebar')]
        for path in [f'/preview/{first}',f'/edit/{first}']:
            page=client.get(path)
            assert page.status_code==200 and 'Resume layout' in page.text
            assert 'Modern Sidebar' in page.text and 'ATS Classic' in page.text
            assert 'DOCX uses a simplified layout' in page.text
        assert client.get(f'/download/{first}/pdf').content.endswith(b'modern_sidebar')
        assert client.get(f'/download/{first}/docx').content.endswith(b'modern_sidebar')
        ai.assert_not_awaited()


def test_legacy_layout_default_and_photo_preference(monkeypatch,resume_payload):
    import json
    with TestClient(app) as client:
        sign_in(client)
        setup_exports(monkeypatch)
        response=sample_workflow_response('mock','fixture')
        slug,folder=app.state.storage.save_application(job(),response.analysis,TailoredResume.model_validate(resume_payload),[],photo_enabled=True)
        metadata=json.loads((folder/'metadata.json').read_text())
        metadata.pop('template_name')
        (folder/'metadata.json').write_text(json.dumps(metadata))
        monkeypatch.setattr(app.state.profile_photo,'exists',lambda:True)
        data={'csrf_token':client.cookies.get('csrf_token'),'template_name':'ats_classic'}
        assert client.post(f'/preview/{slug}/layout',data=data,follow_redirects=False).status_code==303
        meta=app.state.storage.load_application(slug)[3]
        assert meta['photo_enabled'] is False and meta['modern_photo_enabled'] is True
        data['template_name']='modern_sidebar'
        assert client.post(f'/preview/{slug}/layout',data=data,follow_redirects=False).status_code==303
        assert app.state.storage.load_application(slug)[3]['photo_enabled'] is True


def test_edit_layout_only_preserves_legacy_content(monkeypatch,resume_payload):
    with TestClient(app) as client:
        sign_in(client)
        calls,ai=setup_exports(monkeypatch)
        response=sample_workflow_response('mock','fixture')
        slug,folder=app.state.storage.save_application(job(),response.analysis,TailoredResume.model_validate(resume_payload),[],template_name='ats_classic')
        before=(folder/'resume.json').read_bytes()
        data={'csrf_token':client.cookies.get('csrf_token'),'template_name':'modern_sidebar'}
        result=client.post(f'/edit/{slug}',data=data,follow_redirects=False)
        assert result.status_code==303
        assert (folder/'resume.json').read_bytes()==before
        assert calls==[('pdf','modern_sidebar'),('docx','modern_sidebar')]
        ai.assert_not_awaited()


def test_real_exports_keep_full_content_in_both_layouts(tmp_path,profile):
    import re
    from pathlib import Path

    from docx import Document
    from pypdf import PdfReader

    from app.models.resume import ResumeBullet, ResumeExperience, ResumeProject
    from app.services.docx_generator import generate_docx
    from app.services.pdf_generator import PDFGenerator
    text='Maintained the verified infrastructure workflow and documented operational troubleshooting.'
    bullets=[ResumeBullet(text=f'{text} Reference {i}.',source_fact_ids=['experience:0:fact:0']) for i in range(30)]
    resume=TailoredResume(headline='Support Engineer',professional_summary='Verified operational work.',core_skills=['Python'],
                          experience=[ResumeExperience(company='Example',title=f'Engineer {i}',dates='2022–Present',bullets=bullets[i:i+4]) for i in range(0,30,4)],
                          education=[],projects=[ResumeProject(name='Final project',description='This final project must remain visible.',technologies=['Python'],source_fact_ids=['project:0'])],
                          certifications=[],interests=['Cycling'])
    pdf=PDFGenerator(Path('templates'),Path('static'),tmp_path)
    def normalize(value):
        return re.sub(r'\W','',value).lower()
    docs=[]
    for layout in ['modern_sidebar','ats_classic']:
        pdf_path=tmp_path/f'{layout}.pdf'
        pdf.generate(resume,profile,pdf_path,template_name=layout)
        content=normalize(''.join(page.extract_text() for page in PdfReader(pdf_path).pages))
        assert all(normalize(b.text) in content for b in bullets)
        assert normalize(resume.projects[0].description) in content
        assert 'cycling' in content
        path=tmp_path/f'{layout}.docx'
        generate_docx(resume,profile,path,template_name=layout)
        docs.append([p.text for p in Document(path).paragraphs])
    assert docs[0]==docs[1]


def test_layout_choice_before_first_export(monkeypatch,resume_payload):
    with TestClient(app) as client:
        sign_in(client)
        calls,ai=setup_exports(monkeypatch)
        response=sample_workflow_response('mock','fixture')
        response.resume=TailoredResume.model_validate(resume_payload)
        draft=app.state.storage.save_draft(job(),response)
        page=client.get(f'/analysis/{draft}')
        assert page.status_code==200 and 'name="template_name"' in page.text
        assert 'ATS Classic' in page.text and 'Modern Sidebar' in page.text
        data={'csrf_token':client.cookies.get('csrf_token'),'template_name':'unsupported'}
        assert client.post(f'/generate/{draft}',data=data,follow_redirects=False).status_code==422
        data['template_name']='modern_sidebar'
        result=client.post(f'/generate/{draft}',data=data,follow_redirects=False)
        assert result.status_code==303
        slug=result.headers['location'].split('/')[-1]
        assert app.state.storage.load_application(slug)[3]['template_name']=='modern_sidebar'
        assert calls==[('pdf','modern_sidebar'),('docx','modern_sidebar')]
        ai.assert_not_awaited()
