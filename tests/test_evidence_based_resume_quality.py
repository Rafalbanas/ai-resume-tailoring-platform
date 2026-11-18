import asyncio

import pytest

from app.core.config import Settings
from app.models.resume import ResumeBullet
from app.services.content_quality import evidence_specificity, generic_duty, high_value_detail
from app.services.fact_retrieval import retrieve_facts
from app.services.fact_validator import FactValidator
from app.services.ollama_draft_review import sign_bullet
from app.services.one_page_resume import prefer_one_page
from app.services.role_focus import target_focus
from scripts.compare_resume_quality import benchmark, benchmark_layout, scenario
from scripts.resume_quality_scenarios import SCENARIOS, profile, sparse_draft


def test_role_focus_uses_responsibilities_and_mandatory_evidence_not_benefits():
    focus = target_focus('Technical Specialist', '''Responsibilities
Onboard enterprise customers and troubleshoot REST API integrations.
Requirements
Professional experience with OAuth and SSO
Benefits
Wellness allowance, machine learning classes and employee Docker workshop.
''')
    assert {'implementation', 'integration_support'} <= set(focus.families)
    assert focus.professional_required
    assert focus.score('Diagnosed OAuth failures in REST APIs.') > focus.score('Built Docker images.')
    assert focus.score('Trained machine learning models.') == 0
    assert not {'machine', 'docker'} & focus.terms


def test_specificity_does_not_require_metrics_or_infer_a_result():
    assert generic_duty('Handled daily operational tasks.')
    assert not generic_duty('Diagnosed VPN failures.')
    assert evidence_specificity('Diagnosed VPN failures.') > evidence_specificity('Handled daily operational tasks.')
    assert high_value_detail('Provided support to 170 users across five locations.')
    assert high_value_detail('Reduced restore time by 20%.')
    assert not high_value_detail('Planned to reduce restore time by 20%.')


def test_retrieval_queries_include_duties_even_with_structured_requirements():
    candidate = profile()
    job, analysis = scenario('Technical Implementation Specialist', candidate)
    assert analysis.requirements and analysis.responsibilities
    retrieved = retrieve_facts(job, candidate, analysis, settings=Settings(_env_file=None))
    assert 'implementation' in retrieved.trace['target_families']
    queries = [q['text'] for q in retrieved.trace['queries']]
    assert any(query.startswith('Onboard enterprise customers') for query in queries)
    assert not any('workshops' in query for query in queries)
    assert all(any(e.text == fact and e.kind == 'experience' for e in retrieved.entries)
               for fact in SCENARIOS[job.role]['employment'])
    assert not any('Kubernetes' in e.text for e in retrieved.entries)


@pytest.mark.parametrize('role', SCENARIOS)
def test_tailoring_uses_canonical_documents_and_preserves_profile(role):
    candidate = profile()
    unchanged = candidate.model_dump()
    job, analysis = scenario(role, candidate)
    draft = sparse_draft(candidate)
    # Factual check: neither the role nor a real citation permits invented
    # business outcomes, offer-only expertise or transferring a project to work.
    draft.headline = 'Senior Kubernetes Expert'
    draft.core_skills += ['Kubernetes', 'Terraform']
    draft.experience[0].bullets[0].text = 'Reduced downtime by 99% using Kubernetes.'
    draft.experience[0].bullets.append(ResumeBullet(
        text='Deployed Docker in a production cluster.', source_fact_ids=['project:0:fact:0']))
    validator = FactValidator(candidate, analysis=analysis)
    result = validator.validate(draft, job)
    assert candidate.model_dump() == unchanged
    assert 'Kubernetes' not in result.resume.model_dump_json()
    assert '99%' not in result.resume.model_dump_json()
    assert 'production cluster' not in result.resume.model_dump_json()
    assert [(e.company, e.title) for e in result.resume.experience] == [(e.company, e.title) for e in candidate.experience]
    assert any('Unsupported AI bullet' in warning for warning in result.warnings)
    assert validator.validate(result.resume, job).resume == result.resume


def test_allowed_project_cannot_replace_employment_and_keeps_scope():
    candidate = profile()
    job, analysis = scenario('Technical Implementation Specialist', candidate)
    resume = FactValidator(candidate, analysis=analysis).validate(sparse_draft(candidate), job).resume
    assert resume.section_order.index('experience') < resume.section_order.index('projects')
    assert 'Personal project' in resume.projects[0].description
    assert not any('calendar' in b.text.casefold() for owner in resume.experience for b in owner.bullets)


def test_reviewed_bullet_does_not_hide_available_operational_scope():
    candidate = profile()
    job, analysis = scenario('Technical Support Engineer', candidate)
    validator = FactValidator(candidate, analysis=analysis, review_key='synthetic-review-key')
    draft = sparse_draft(candidate)
    bullet = ResumeBullet(text='Delivered L1/L2 user support, troubleshooting VPN and workstation incidents.',
                          source_fact_ids=[validator.catalog.get('experience:0:fact:1').source_id])
    draft.experience[0].bullets = [bullet]
    draft._bullet_attestations = [sign_bullet(bullet, candidate, validator.review_key)]
    resume = validator.validate(draft, job).resume
    assert resume.experience[0].bullets[0].text == candidate.experience[0].facts[1]
    assert bullet.text not in [b.text for b in resume.experience[0].bullets]


def test_preferred_one_page_does_not_remove_relevant_quantified_scope():
    candidate = profile()
    job, _ = scenario('Technical Support Engineer', candidate)
    validator = FactValidator(candidate)
    resume = validator.validate(sparse_draft(candidate), job).resume
    metric = next(b.text for e in resume.experience for b in e.bullets if '170 users' in b.text)
    fitted, warnings = prefer_one_page(resume, validator, f'{job.role}\n{job.relevance_text}',
        lambda cv: not any(b.text == metric for e in cv.experience for b in e.bullets))
    assert fitted == resume
    assert 'multi-page' in warnings[0]


def test_synthetic_benchmark_and_ats_exports(tmp_path):
    report = asyncio.run(benchmark(tmp_path, exports=True))
    assert report['mean_pairwise_bullet_jaccard'] < 0.60
    for result in report['resumes']:
        assert result['matched_before_fit'] == result['expected'], result
        assert result['matched_export'] == result['expected'], result
        assert not result['errors'], result
        assert result['generic_bullets'] == 0
        assert 1 <= result['pages'] <= 2
        assert all(e['found'] == e['required'] for e in result['extraction'].values()), result
        if result['expected_project']:
            assert result['projects'][0] == result['expected_project'], result
    assert next(r for r in report['resumes'] if r['role'] == 'Technical Support Engineer')['scale_visible']


def test_layout_retains_scope_and_allows_two_pages_when_needed(tmp_path):
    report = benchmark_layout(tmp_path)
    assert report['ats_classic']['pages'] == 2
    for result in report.values():
        assert result['scoped_facts'] == result['scoped_facts_before_fit'] == 24
        assert 1 <= result['pages'] <= 2
        assert all(e['found'] == e['required'] for e in result['extraction'].values())
