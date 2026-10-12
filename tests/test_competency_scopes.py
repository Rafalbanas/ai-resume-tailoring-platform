import pytest

from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis, JobRequirement
from app.services.analysis_validator import AnalysisValidator
from app.services.competency_scope import atomic_parts
from app.services.evidence_gaps import answer_fact, evidence_questions
from app.services.evidence_matching import EvidenceMatcher
from app.services.fact_catalog import FactCatalog


def profile_with(*facts):
    return CandidateProfile(personal={'name': 'Synthetic'}, summary_facts=list(facts), skills={})


def match(text, *facts):
    return EvidenceMatcher(FactCatalog(profile_with(*facts))).match(text)


@pytest.mark.parametrize('source', [
    'Understanding of networking concepts and principles and security best practices',
    'Understanding of backup and disaster recovery strategies',
    'Understanding of Agile Scrum Experience and working in a CI/CD environment',
    'Familiarity with configuration management and version control systems',
])
def test_source_scopes_are_atomic_without_duplicate_scoring(source):
    assert len(atomic_parts(source)) == (3 if 'Agile' in source else 2)


def test_concept_and_principle_are_not_independent_scoring_conditions():
    assert not atomic_parts('Networking concepts and principles')


def test_network_evidence_reused_but_not_security_mastery():
    facts = ('Used TCP/IP, DNS and DHCP while troubleshooting network incidents.',)
    simple = match('Understanding of networking concepts', *facts)
    combined = match('Understanding of networking concepts and principles and security best practices', *facts)
    assert simple.status == 'strong'
    assert combined.status == 'partial'
    assert {e.source_id for e in simple.entries} <= {e.source_id for e in combined.entries}


def test_backups_and_theoretical_dr_satisfy_understanding_not_practice():
    facts = ('Used Veeam to perform backups.', 'Understands the basic purpose of disaster recovery. No practical experience performing disaster recovery procedures.')
    assert match('Understanding of backup and disaster recovery strategies', *facts).status == 'partial'
    assert match('Hands-on experience with disaster recovery', *facts).status == 'absent'


def test_agile_training_not_scrum_professional_practice():
    facts = ('Completed Agile and Scrum training.',)
    assert match('Understanding of Agile Scrum', *facts).status == 'strong'
    assert match('Professional experience with Scrum', *facts).status == 'partial'


def test_git_does_not_confirm_configuration_management():
    facts = ('Used Git and GitHub for project version control.',)
    assert match('Familiarity with version control systems', *facts).status == 'strong'
    assert match('Familiarity with configuration management and version control systems', *facts).status == 'partial'
    assert match('Practical experience with Ansible', *facts).status == 'missing'


def test_conflicting_scope_evidence_requires_review():
    result = match('Practical experience with backup', 'Used Veeam to perform backups.', 'No practical experience with backups.')
    assert result.status == 'partial'
    assert len(result.entries) == 2


@pytest.mark.parametrize('level', ['awareness', 'familiarity', 'basic knowledge', 'understanding'])
def test_theory_matches_knowledge_level(level):
    assert match(f'{level} of disaster recovery', 'Theoretical understanding of disaster recovery.').status == 'strong'


@pytest.mark.parametrize('level', ['practical knowledge', 'hands-on experience', 'professional experience', 'proficiency'])
def test_theory_does_not_match_practice_level(level):
    assert match(f'{level} of disaster recovery', 'Theoretical understanding of disaster recovery.').status == 'partial'


def test_semantic_missing_rows_recover_existing_evidence_and_atoms():
    quote = 'Familiarity with configuration management and version control systems'
    candidate = JobAnalysis(company='Synthetic', role='DevOps', strong_matches=[], partial_matches=[], missing_requirements=[quote], recommendation='REVIEW', match_level='LOW',
                            requirements=[JobRequirement(name=quote, source_quote=quote, interpretation_origin='llm')])
    result = AnalysisValidator(profile_with('Used Git and GitHub for project version control.')).validate(candidate, 'Requirements\n' + quote)
    assert len(result.requirements) == 1
    req = result.requirements[0]
    assert req.status == 'partial'
    assert len(req.components) == 2
    assert {c.status for c in req.components} == {'strong', 'missing'}


def analysis_with_gaps():
    return JobAnalysis(company='Synthetic', role='Role', strong_matches=[], partial_matches=[], missing_requirements=[], recommendation='REVIEW', match_level='LOW',
                       requirements=[JobRequirement(id=str(i), name=f'Tool {i}') for i in range(10)])


def test_gap_questions_are_bounded_stable_and_skip_confirmed_gaps():
    analysis = analysis_with_gaps()
    analysis.requirements[0].status = 'absent'
    questions = evidence_questions(analysis)
    assert len(questions) == 5
    assert questions == evidence_questions(analysis)
    assert all(q['name'] != 'Tool 0' for q in questions)


def test_question_alone_and_unconsented_answer_cannot_create_fact():
    question = evidence_questions(analysis_with_gaps())[0]
    with pytest.raises(ValueError, match='consent'):
        answer_fact(question, 'confirm', 'theoretical', 'education', 'Studied basics in a course.', consent=False)
    fact = answer_fact(question, 'confirm', 'theoretical', 'education', 'Studied basics in a course.', consent=True)
    assert fact.startswith('Theoretical knowledge')
    assert 'Professional practical' not in fact


def test_profile_answer_persists_only_with_consent_and_valid_question():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.services.profile_loader import load_master_profile
    from tests.test_provider_fallback import job, sample_workflow_response
    from tests.test_recording_demo import sign_in
    with TestClient(app) as client:
        sign_in(client)
        response = sample_workflow_response("mock", "synthetic")
        response.analysis = analysis_with_gaps()
        draft = app.state.storage.save_draft(job(), response)
        question = evidence_questions(response.analysis)[0]
        form = {'csrf_token': client.cookies.get('csrf_token'), 'question_id': question['id'],
                'answer': 'confirm', 'scope': 'theoretical', 'experience_context': 'education',
                'details': 'Studied the principles in a university course.'}
        before = app.state.settings.master_profile_path.read_bytes()
        assert client.post(f'/analysis/{draft}/evidence', data=form, follow_redirects=False).status_code == 400
        assert app.state.settings.master_profile_path.read_bytes() == before
        form['save_consent'] = 'on'
        forged = dict(form, question_id='forged')
        assert client.post(f'/analysis/{draft}/evidence', data=forged, follow_redirects=False).status_code == 400
        assert client.post(f'/analysis/{draft}/evidence', data=dict(form, csrf_token='wrong'), follow_redirects=False).status_code == 403
        assert client.post(f'/analysis/{draft}/evidence', data=form, follow_redirects=False).status_code == 303
        saved, _ = load_master_profile(app.state.settings)
        assert any('Theoretical knowledge of Tool 0' in fact for fact in saved.summary_facts)
        assert saved.summary_facts == app.state.profile.summary_facts
        assert any('Tool 0' in e.text for e in app.state.skills_bank.catalog.prompt_entries)
        assert app.state.storage.load_draft(draft)[1].analysis.requirements[0].status == 'missing'
        page = client.get(f'/analysis/{draft}')
        assert page.status_code == 200
        assert 'save_consent' in page.text


def test_generic_theoretical_fact_cannot_confirm_hands_on_kubernetes():
    from app.models.job import RequirementComponent
    from app.services.semantic_requirements import _facts
    profile = profile_with('Theoretical knowledge of Kubernetes from a course.')
    validator = AnalysisValidator(profile)
    fact = validator.matcher.entries[0]
    item = RequirementComponent(name='Hands-on experience with Kubernetes', status='strong', source_fact_ids=[fact.source_id])
    _facts(validator, item)
    assert item.status == 'partial'


def test_saved_denial_of_generic_practice_does_not_deny_theory():
    facts = ('Theoretical knowledge of Kubernetes from a course.', 'No practical experience with Kubernetes. Context: education.')
    assert match('Hands-on experience with Kubernetes', *facts).status == 'partial'
    assert match('Knowledge of Kubernetes', *facts).status != 'absent'
    assert match('Hands-on experience with Kubernetes', facts[1]).status == 'absent'


def test_ci_component_recovers_existing_artifact_evidence():
    from app.models.job import RequirementComponent
    from app.services.semantic_requirements import _facts
    validator = AnalysisValidator(profile_with('Implemented GitHub Actions in .github/workflows/ci.yml.'))
    item = RequirementComponent(name='Working in a CI/CD environment')
    _facts(validator, item)
    assert item.status == 'partial'
    assert item.source_fact_ids


def test_verified_artifact_label_does_not_prove_pipeline_execution():
    from app.services.evidence_strength import evidence_strength
    from app.services.fact_catalog import FactEntry
    entry = FactEntry('manual:ci', 'verified_skill', 'Verified in example/repository: .github/workflows/ci.yml test and lint')
    assert evidence_strength(entry) == 'implementation'


def test_one_fact_can_contain_theory_and_separate_practice_denial():
    from app.models.job import RequirementComponent
    from app.services.semantic_requirements import _facts
    validator = AnalysisValidator(profile_with('Completed Agile training. No practical experience working in a Scrum team.'))
    item = RequirementComponent(name='Understanding of Agile Scrum knowledge')
    _facts(validator, item)
    assert item.status == 'strong'
    assert item.source_fact_ids


def test_atomization_preserves_advanced_source_scope():
    parts = atomic_parts('Advanced understanding of backup and disaster recovery strategies')
    assert all(part.startswith('Advanced understanding of ') for part in parts)
    assert match(parts[0], 'Used Veeam to perform backups.').status == 'partial'


def test_answer_does_not_copy_employer_tenure_or_proficiency_into_profile():
    fact = answer_fact({'name': 'Minimum 5+ years of advanced proficiency in Ansible'}, 'confirm', 'theoretical', 'education', 'Studied the basics in a course.', consent=True)
    assert fact.startswith('Theoretical knowledge of Ansible.')
    assert '5+' not in fact and 'advanced' not in fact


def test_final_recovery_contract_requires_each_missing_passage():
    from app.models.job import JobRequest
    from app.services.ollama_analysis import AnalysisInventory, CompactInterpretation
    job = JobRequest(company='Synthetic', role='DevOps', job_description='Requirements\nUnderstanding of networking concepts\nFamiliarity with version control systems')
    inventory = AnalysisInventory.build(job, profile_with('Used Git for version control.'), None)
    ids = list(inventory.passages)[-2:]
    schema = inventory.keyed_schema(ids)
    assert schema['properties']['assessments']['required'] == ids
    assert set(schema['properties']['assessments']['properties']) == set(ids)
    assert not schema['properties']['assessments']['additionalProperties']
    parsed = CompactInterpretation.model_validate({'assessments': {pid: {'k': 'requirement', 'n': 'Knowledge', 's': 'missing', 'f': [], 'why': 'No evidence', 'priority': 'mandatory'} for pid in ids}})
    assert [r.p for r in inventory.validate_rows(parsed.rows, ids)] == ids
