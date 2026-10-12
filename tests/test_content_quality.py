import pytest

from app.models.job import JobRequest
from app.models.resume import TailoredResume
from app.services.content_quality import deduplicate_text, quality_issues
from app.services.fact_validator import FactValidator
from app.services.resume_export import web_link
from app.services.summary_review import sign_summary, valid_summary_attestation


def test_linux_repeated_base_merges_distinct_tools():
    value = ('Deploys and maintains self-hosted services on a Linux VPS using SSH. '
             'Deployment and maintenance of self-hosted services including n8n on a Linux VPS.')
    text = deduplicate_text(value)
    assert len(text.split('. ')) == 1
    assert 'SSH' in text and 'n8n' in text and 'Linux' in text


def test_ml_nominal_description_subsumes_repeated_build_statement():
    value = ('Python data pipeline for cycling FTP estimation and comparison of machine learning models. '
             'Built a Python pipeline for cycling FTP estimation.')
    text = deduplicate_text(value)
    assert 'comparison' in text
    assert text.count('cycling FTP estimation') == 1


@pytest.mark.parametrize('value', [
    'Deploys Linux services. Monitors Linux services.',
    'Uses Docker locally. Uses Docker in production.',
    'Uses basic Docker. Uses advanced Docker.',
    'Tested 3 models. Tested 5 models.',
    'Supports Linux systems. Does not administer Linux systems.',
])
def test_similar_words_do_not_remove_distinct_facts(value):
    assert deduplicate_text(value) == value


def test_duplicate_source_and_duplicate_output_are_idempotent():
    value = 'Automates checks with Python. Automates checks with Python.'
    clean = deduplicate_text(value)
    assert clean == 'Automates checks with Python.'
    assert deduplicate_text(clean) == clean


def test_signed_review_preserves_natural_summary_and_rejects_edits(profile):
    value = 'I automate operational workflows with Python at Example Ltd.'
    draft = TailoredResume(headline='Support Engineer', professional_summary=value,
                           summary_source_fact_ids=['experience:0:fact:0'], core_skills=['Python'], experience=[])
    draft.summary_attestation = sign_summary(draft, profile, 'test-secret')
    assert valid_summary_attestation(draft, profile, 'test-secret')
    job = JobRequest(company='A', role='Engineer', job_description='Requirements\nPython automation')
    kept = FactValidator(profile, review_key='test-secret').validate(draft, job).resume
    assert kept.professional_summary == value
    draft.professional_summary = 'I am a Kubernetes expert.'
    assert not valid_summary_attestation(draft, profile, 'test-secret')
    assert 'Kubernetes' not in FactValidator(profile, review_key='test-secret').validate(draft, job).resume.professional_summary
    profile.experience[0].facts = ['Does not automate workflows.']
    assert not valid_summary_attestation(kept, profile, 'test-secret')


def test_unsigned_approval_cannot_bypass_truth_lock(profile):
    draft = TailoredResume(headline='Engineer', professional_summary='Kubernetes expert.',
                           core_skills=[], experience=[])
    draft.summary_attestation = 'approved'
    job = JobRequest(company='A', role='Engineer', job_description='Requirements\nKubernetes expertise required')
    assert 'Kubernetes' not in FactValidator(profile, review_key='test-secret').validate(draft, job).resume.professional_summary


def test_ascii_url_target_is_unchanged():
    url = 'https://www.example.com:443/path%2Fpart?next=https%3A%2F%2Fother.example%2Fa&x=1#anchor'
    assert web_link(url) == url


def test_final_quality_reports_unfinished_text(profile):
    draft = TailoredResume(headline='Engineer', professional_summary='Automates Python workflows and', core_skills=[], experience=[])
    assert any('unfinished' in issue.lower() for issue in quality_issues(draft, profile))


def test_final_export_preserves_original_level_labels(profile, resume_payload):
    from app.services.resume_export import prepare_resume
    profile.skills['technical'] = ['Basic Docker', 'Junior Python']
    draft = TailoredResume.model_validate(resume_payload)
    draft.professional_summary = 'Automates operational workflows with Python.'
    draft.core_skills = ['Basic Docker', 'Junior Python']
    assert prepare_resume(draft, profile).core_skills == ['Basic Docker', 'Junior Python']
    assert profile.skills['technical'] == ['Basic Docker', 'Junior Python']
    draft.core_skills = ['Advanced Docker']
    with pytest.raises(ValueError, match='proficiency increase'):
        prepare_resume(draft, profile)


def test_language_upgrade_is_rejected_before_export(profile, resume_payload):
    from app.services.resume_export import prepare_resume
    profile.skills['languages'] = ['English B2']
    draft = TailoredResume.model_validate(resume_payload)
    draft.professional_summary = 'Uses English C1 in professional communication.'
    with pytest.raises(ValueError, match='proficiency increase'):
        prepare_resume(draft, profile)


@pytest.mark.asyncio
async def test_review_does_not_call_another_provider_on_failure(profile, resume_payload):
    from app.services.ai_provider import AIProviderError
    from app.services.summary_review import review_summary
    draft = TailoredResume.model_validate(resume_payload)
    draft.professional_summary = 'I automate operational workflows with Python.'
    class Unavailable:
        summary_review_key = 'test-secret'
        async def _chat(self, *args):
            raise AIProviderError('Unavailable')
    result = await review_summary(Unavailable(), draft, profile)
    assert not result.summary_attestation
    assert result.professional_summary == draft.professional_summary


@pytest.mark.asyncio
async def test_reviewer_approval_is_signed_and_cannot_be_reused_for_other_text(profile, resume_payload):
    from app.services.summary_review import SummaryVerdict, review_summary
    draft = TailoredResume.model_validate(resume_payload)
    draft.professional_summary = 'I automate infrastructure and support workflows with Python.'
    class Approved:
        summary_review_key = 'test-secret'
        async def _chat(self, model, prompt, payload):
            assert payload['stage'] == 'review_summary'
            assert 'job_description' not in payload
            return SummaryVerdict(supported=True)
    result = await review_summary(Approved(), draft, profile)
    assert valid_summary_attestation(result, profile, 'test-secret')
    result.professional_summary += ' I am a senior DevOps engineer.'
    assert not valid_summary_attestation(result, profile, 'test-secret')


def test_review_survives_storage_without_changing_resume_json_contract(tmp_path, profile, resume_payload):
    from app.models.job import JobAnalysis
    from app.models.resume import WorkflowResponse
    from app.services.storage import Storage
    draft = TailoredResume.model_validate(resume_payload)
    draft.summary_attestation = sign_summary(draft, profile, 'test-secret')
    assert 'summary_attestation' not in draft.model_dump()
    assert 'summary_attestation' not in TailoredResume.model_json_schema()['properties']
    job = JobRequest(company='A', role='Engineer', job_description='Requirements\nPython automation required')
    analysis = JobAnalysis(company='A', role='Engineer', strong_matches=[], partial_matches=[], missing_requirements=[], recommendation='REVIEW', match_level='LOW')
    storage = Storage(tmp_path)
    id = storage.save_draft(job, WorkflowResponse(analysis=analysis, resume=draft))
    _, loaded = storage.load_draft(id)
    assert valid_summary_attestation(loaded.resume, profile, 'test-secret')
    slug, _ = storage.save_application(job, analysis, draft, [])
    _, loaded_resume, generated, _ = storage.load_application(slug)
    assert valid_summary_attestation(loaded_resume, profile, 'test-secret')
    assert valid_summary_attestation(generated, profile, 'test-secret')


def test_pagination_does_not_rewrite_natural_summary(tmp_path, profile, resume_payload, monkeypatch):
    from pathlib import Path

    from app.services.pdf_generator import PDFGenerator
    draft = TailoredResume.model_validate(resume_payload)
    draft.professional_summary = 'I automate infrastructure and support workflows with Python.'
    draft.summary_attestation = sign_summary(draft, profile, 'test-secret')
    gen = PDFGenerator(Path('templates'), Path('static'), tmp_path)
    monkeypatch.setattr(gen, '_fits_one_page', lambda *args: False)
    fitted, _ = gen.fit_resume(draft, profile, {})
    assert fitted.professional_summary == draft.professional_summary
    assert fitted.core_skills == draft.core_skills
    assert valid_summary_attestation(fitted, profile, 'test-secret')


@pytest.mark.asyncio
async def test_missing_model_citations_are_recovered_only_by_reviewer(profile, resume_payload):
    from app.services.summary_review import SummaryVerdict, review_summary
    draft = TailoredResume.model_validate(resume_payload)
    draft.professional_summary = 'I automate infrastructure and support workflows with Python.'
    draft.summary_source_fact_ids = []
    class Reviewer:
        summary_review_key = 'test-secret'
        async def _chat(self, model, prompt, payload):
            ids = [f['source_id'] for f in payload['source_facts'] if 'Automates' in f['fact']]
            return SummaryVerdict(supported=True, source_fact_ids=ids)
    approved = await review_summary(Reviewer(), draft, profile)
    assert approved.summary_source_fact_ids
    assert valid_summary_attestation(approved, profile, 'test-secret')


@pytest.mark.asyncio
async def test_ollama_full_workflow_preserves_reviewed_natural_summary(profile):
    import json

    import httpx

    from app.core.config import Settings
    from app.services.ollama_provider import OllamaProvider
    from tests.test_ollama_provider import resume_payload
    text = 'I automate infrastructure and support workflows with Python. I work as a Support Engineer at Example Ltd.'
    payload = resume_payload()
    payload['professional_summary'] = text
    analysis = {'rows': [
        {'p': 'P1', 'k': 'context'}, {'p': 'P2', 'k': 'context'},
        {'p': 'P3', 'k': 'requirement', 'n': 'Python automation', 'priority': 'mandatory',
         's': 'strong', 'f': ['F1'], 'why': 'The summary fact explicitly documents Python automation.'},
    ]}
    replies = [analysis, payload, {'supported': True, 'issues': []}]
    requests = []
    async def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={'message': {'content': json.dumps(replies[len(requests)-1])}})
    settings = Settings(_env_file=None, csrf_secret='test-secret')
    provider = OllamaProvider(settings, transport=httpx.MockTransport(handler))
    job = JobRequest(company='A', role='Engineer', job_description='Requirements\nPython automation required')
    response = await provider.tailor(job, profile)
    assert len(requests) == 3
    assert requests[-1]['messages'][1]['content'].find('review_summary') >= 0
    resume = FactValidator(profile, review_key=settings.csrf_secret).validate(response.resume, job).resume
    assert resume.professional_summary == text
    assert valid_summary_attestation(resume, profile, settings.csrf_secret)


def test_word_order_and_actor_roles_are_not_deduplicated():
    text = 'Tested component X using component Y. Tested component Y using component X.'
    assert deduplicate_text(text) == text


def test_proficiency_checker_does_not_rebind_adjacent_skill_level(profile, resume_payload):
    profile.skills['technical'] = ['Basic Docker', 'Advanced Python']
    draft = TailoredResume.model_validate(resume_payload)
    draft.professional_summary = 'Advanced Python and basic Docker are documented skills.'
    assert not any(i.startswith('Unsupported proficiency') for i in quality_issues(draft, profile))


def test_empty_experience_bullet_is_reported(profile, resume_payload):
    draft = TailoredResume.model_validate(resume_payload)
    draft.experience[0].bullets[0].text = ''
    assert any(i.startswith('Empty fragment') for i in quality_issues(draft, profile))


@pytest.mark.asyncio
async def test_optional_summary_review_is_time_bounded(profile, resume_payload, monkeypatch):
    import asyncio

    import app.services.summary_review as review
    draft = TailoredResume.model_validate(resume_payload)
    draft.professional_summary = 'I automate infrastructure and support workflows with Python.'
    monkeypatch.setattr(review, 'SUMMARY_REVIEW_TIMEOUT_SECONDS', 0.001)
    class SlowReviewer:
        summary_review_key = 'test-secret'
        async def _chat(self, *args):
            await asyncio.sleep(1)
    result = await review.review_summary(SlowReviewer(), draft, profile)
    assert not result.summary_attestation


def test_contact_change_does_not_invalidate_professional_claim_review(profile, resume_payload):
    draft = TailoredResume.model_validate(resume_payload)
    draft.summary_attestation = sign_summary(draft, profile, 'test-secret')
    profile.personal.linkedin = 'https://linkedin.com/in/new-link'
    assert valid_summary_attestation(draft, profile, 'test-secret')
    profile.experience[0].title = 'A different occupation'
    assert not valid_summary_attestation(draft, profile, 'test-secret')


def test_negated_expertise_is_not_mistaken_for_a_level_increase(profile, resume_payload):
    profile.skills['technical'] = ['Basic Docker']
    draft = TailoredResume.model_validate(resume_payload)
    draft.professional_summary = 'Uses basic Docker, not advanced Docker.'
    assert not any(i.startswith('Unsupported proficiency') for i in quality_issues(draft, profile))
    draft.professional_summary = 'Has basic Docker knowledge. Advanced Docker expertise.'
    assert any(i.startswith('Unsupported proficiency') for i in quality_issues(draft, profile))
