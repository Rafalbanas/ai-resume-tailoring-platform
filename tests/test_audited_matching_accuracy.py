"""Fictional reproductions of source/classification/evidence audit failures."""
import json
from datetime import date

import pytest

from app.models.candidate import CandidateProfile
from app.models.job import JobRequirement
from app.services.analysis_validator import AnalysisValidator
from app.services.evidence_matching import EvidenceMatcher
from app.services.fact_catalog import FactCatalog
from app.services.named_evidence import named_scope_ceiling
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment, needs_assessment
from app.services.semantic_requirements import _facts, merge_equivalent_source_rows


def profile(*facts):
    return CandidateProfile(personal={'name': 'Synthetic Candidate'}, projects=[{
        'name': 'Synthetic lab', 'facts': list(facts)}])


def test_postman_is_not_proved_by_httpx_and_sql():
    entries = FactCatalog(profile('Implemented API tests using HTTPX and TestClient.',
                                  'Used SQL queries.')).prompt_entries
    ceiling = named_scope_ceiling('Knowledge of SQL, Postman and API testing tools.', entries)
    assert ceiling and ceiling[0] == 'partial' and 'Postman' in ceiling[1]


def test_explicit_postman_use_and_optional_examples_are_preserved():
    entries = FactCatalog(profile('Implemented API tests using Postman and SQL.')).prompt_entries
    assert named_scope_ceiling('Knowledge of SQL, Postman and API testing tools.', entries) is None
    other = FactCatalog(profile('Implemented API tests using HTTPX.')).prompt_entries
    assert named_scope_ceiling('API testing tools such as Postman.', other) is None
    assert named_scope_ceiling('Knowledge of Postman or HTTPX.', other) is None


@pytest.mark.parametrize('advanced_evidence', [False, True])
def test_advanced_source_level_survives_shortened_model_label(advanced_evidence):
    fact = ('Advanced Python and machine learning framework proficiency demonstrated in implemented projects.'
            if advanced_evidence else 'Implemented Python pipelines using scikit-learn in a personal project.')
    validator = AnalysisValidator(profile(fact))
    req = JobRequirement(name='Python and ML frameworks',
                         source_quote='Bardzo dobra znajomość Pythona oraz frameworków Machine Learning.',
                         required_level='advanced', status='strong', reason='Model confirmed practical use.',
                         source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status == ('strong' if advanced_evidence else 'partial')


@pytest.mark.parametrize('testing_duties', [False, True])
def test_specialist_testing_tenure_requires_duties_not_support_title(testing_duties):
    fact = ('Designed software test cases and performed regression testing of analytical systems.'
            if testing_duties else 'Handled technical support tickets and SQL troubleshooting.')
    candidate = CandidateProfile(personal={}, experience=[{
        'company': 'Synthetic Ltd', 'title': 'Support Specialist', 'start': '2020-01', 'end': '2024-12',
        'facts': [fact]}])
    matcher = EvidenceMatcher(FactCatalog(candidate), as_of=date(2026, 11, 7))
    result = matcher.cited_tenure([e.source_id for e in matcher.entries], 3,
                                 scope='3 years of experience in software testing, analytical systems or data-driven solutions')
    assert result.status == ('strong' if testing_duties else 'missing')
    assert (result.observed_years >= 3) == testing_duties


@pytest.mark.parametrize('quote', [
    'Zdolność przekładania potrzeb biznesowych na rozwiązania technologiczne.',
    'Podstawowa wiedza z zakresu inżynierii danych i architektury oprogramowania.',
])
def test_explicit_polish_capabilities_cannot_hide_as_context(quote):
    assert needs_assessment({'text': quote, 'hints': ['mandatory']})


def test_equivalent_bilingual_conditions_merge_without_inflating_confirmation():
    pl = 'Znajomość SQL, Postman oraz narzędzi do testowania API.'
    en = 'Knowledge of SQL, Postman and API testing tools.'
    rows = [JobRequirement(name='SQL and API testing', source_quote=pl, priority='mandatory', status='strong'),
            JobRequirement(name='Knowledge of SQL and Postman', source_quote=en, priority='mandatory', status='missing')]
    merged = merge_equivalent_source_rows(rows)
    assert len(merged) == 1
    assert merged[0].status == 'missing'
    assert merged[0].interpretation_uncertain
    assert set(merged[0].source_quotes) == {pl, en}


def test_different_source_proficiency_or_optional_priority_does_not_merge():
    rows = [JobRequirement(name='SQL and Postman', source_quote='Knowledge of SQL, Postman and API testing tools.',
                           priority='mandatory', required_level='basic'),
            JobRequirement(name='SQL and Postman', source_quote='Zaawansowana znajomość SQL, Postman i testowania API.',
                           priority='mandatory', required_level='advanced')]
    assert len(merge_equivalent_source_rows(rows)) == 2


def test_coverage_failure_is_reported_for_misclassified_capability():
    from app.models.job import JobRequest
    quote = 'Zdolność przekładania potrzeb biznesowych na rozwiązania technologiczne.'
    job = JobRequest(company='Synthetic', role='Analyst', job_description='Wymagania\n' + quote)
    candidate = profile('Built Python applications.')
    inv = AnalysisInventory.build(job, candidate)
    rows = [CompactAssessment(p=pid, k='responsibility' if p['text'] == quote else 'context')
            for pid, p in inv.passages.items()]
    result = AnalysisValidator(candidate).validate(inv.expand(rows).to_analysis(job), job.job_description, semantic=True)
    assert not result.is_reliable
    assert quote in result.unassessed_source_passages


def test_bilingual_merge_preserves_coverage_on_revalidation():
    from app.models.interpretation import JobInterpretation, ModelRequirement
    from app.models.job import JobRequest
    pl = 'Znajomość SQL, Postman oraz narzędzi do testowania API.'
    en = 'Knowledge of SQL, Postman and API testing tools.'
    text = 'Wymagane doświadczenie\n' + pl + '\nExperience required\n' + en
    job = JobRequest(company='Synthetic', role='Tester', job_description=text)
    rows = [ModelRequirement(name='SQL, Postman and API tools', source_quote=quote, priority='mandatory',
                             status='missing', source_fact_ids=[], reason='Not documented.', operator='all',
                             components=[], classification_basis='Literal qualification') for quote in (pl, en)]
    interpretation = JobInterpretation(requirements=rows, source_context=[
        {'source_quote': 'Wymagane doświadczenie'}, {'source_quote': 'Experience required'}])
    validator = AnalysisValidator(profile())
    result = validator.validate(interpretation.to_analysis(job), text, semantic=True)
    for _ in range(2):
        assert len(result.requirements) == 1
        assert result.is_reliable, result.reasoning_summary
        assert set(result.requirements[0].source_quotes) == {pl, en}
        assert result.scoring_counts['mandatory_groups'] == 1
        result = validator.validate(result, text, semantic=True)


def test_source_review_cannot_confirm_postman_from_other_api_tools():
    from app.services.grounded_requirements import verify_requirement
    validator = AnalysisValidator(profile('Implemented API tests using HTTPX.', 'Used SQL queries.'))
    assert verify_requirement(validator, 'Knowledge of SQL, Postman and API testing tools.')[0] != 'strong'


def test_model_cannot_omit_a_named_and_component():
    from app.models.interpretation import JobInterpretation, ModelComponent, ModelRequirement
    from app.models.job import JobRequest
    candidate = profile('Implemented API tests using HTTPX.', 'Used SQL queries.')
    ids = [entry.source_id for entry in FactCatalog(candidate).prompt_entries]
    quote = 'Knowledge of SQL, Postman and API testing tools.'
    job = JobRequest(company='Synthetic', role='Tester', job_description='Requirements\n' + quote)
    components = [ModelComponent(name=name, status='strong', source_fact_ids=ids, reason='Documented practical use.')
                  for name in ('SQL', 'API testing tools')]
    row = ModelRequirement(name='SQL and API testing', source_quote=quote, priority='mandatory', status='strong',
                           source_fact_ids=ids, reason='Model omitted one condition.', operator='all',
                           components=components, classification_basis='Literal qualification')
    result = AnalysisValidator(candidate).validate(JobInterpretation(
        requirements=[row], source_context=[{'source_quote': 'Requirements'}]).to_analysis(job),
        job.job_description, semantic=True)
    req = result.requirements[0]
    assert req.status == 'partial'
    assert any(c.name == 'Postman' and c.status == 'missing' for c in req.components)


@pytest.mark.parametrize(('pl', 'en'), [
    ('Minimum 3 lata doświadczenia w testowaniu oprogramowania, systemów analitycznych lub rozwiązań opartych na danych.',
     'Minimum 3 years of experience in software testing, analytical systems or data-driven solutions.'),
    ('Praktyczna znajomość tworzenia przypadków i scenariuszy testowych oraz raportowania defektów.',
     'Practical knowledge of creating test cases, test scenarios and defect reports.'),
    ('Umiejętność projektowania zestawów testowych do oceny jakości odpowiedzi modeli, klasyfikacji i ekstrakcji informacji.',
     'Ability to design test suites for evaluating model output quality, classification and information extraction.'),
])
def test_bounded_bilingual_contracts_preserve_equivalence(pl, en):
    from app.services.requirement_equivalence import equivalent_translation
    assert equivalent_translation(pl, en)


@pytest.mark.parametrize('different', [
    'Knowledge of SQL, Insomnia and API testing tools.',
    'Knowledge of SQL, Postman or API testing tools.',
    'Advanced knowledge of SQL, Postman and API testing tools.',
    'Knowledge of SQL, Postman and API testing tools at C1.',
    'No knowledge of SQL, Postman and API testing tools.',
])
def test_bilingual_contracts_never_drop_products_logic_levels_or_negations(different):
    from app.services.requirement_equivalence import equivalent_translation
    assert not equivalent_translation('Znajomość SQL, Postman oraz narzędzi do testowania API.', different)


@pytest.mark.parametrize('level', ['intermediate', 'advanced'])
def test_advanced_skill_bank_attestation_is_respected(tmp_path, level):
    from app.services.skills_bank import SkillsBank
    candidate = profile('Implemented Python applications in a personal project.')
    path = tmp_path / 'skills.json'
    path.write_text(json.dumps({'skills': [{
        'id': 'skill_python', 'name': 'Python', 'category': 'Programming', 'level': level,
        'enabled': True, 'verified': True, 'allowed_in_cv': True,
        'evidence': [{'source_type': 'manual_verified', 'source_id': 'manual:synthetic_python',
                      'description': f'Explicitly verified {level} Python knowledge.'}]}]}))
    validator = AnalysisValidator(candidate, SkillsBank(path, candidate))
    req = JobRequirement(name='Python', source_quote='Bardzo dobra znajomość Pythona.',
                         status='strong', reason='Practical use documented.',
                         source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status == ('strong' if level == 'advanced' else 'partial')


@pytest.mark.parametrize(('pl', 'en'), [
    ('Znajomość podstaw działania modeli ML lub LLM oraz specyfiki testowania systemów niedeterministycznych.',
     'Basic understanding of ML or LLM models and the specifics of testing non-deterministic systems.'),
    ('Umiejętność oceny wyników modeli pod kątem trafności, kompletności, zgodności ze źródłem, bezpieczeństwa i użyteczności.',
     'Ability to evaluate model outputs based on accuracy, completeness, source consistency, security and usability.'),
    ('Doświadczenie w testowaniu systemów RAG, chatbotów, asystentów AI lub modeli predykcyjnych.',
     'Experience testing RAG systems, chatbots, AI assistants or predictive models.'),
    ('Znajomość narzędzi do automatycznej ewaluacji LLM oraz testów regresji promptów.',
     'Knowledge of automated LLM evaluation tools and prompt regression testing.'),
    ('Doświadczenie w testach bezpieczeństwa rozwiązań GenAI, w tym prompt injection i jailbreak.',
     'Experience in GenAI security testing, including prompt injection and jailbreak testing.'),
    ('Znajomość wymagań dotyczących dostępności, UX lub prostego języka.',
     'Knowledge of accessibility, UX or plain-language requirements.'),
])
def test_bilingual_evaluation_contracts_keep_each_scope(pl, en):
    from app.services.requirement_equivalence import equivalent_translation
    assert equivalent_translation(pl, en)


def test_ci_regressions_are_not_prompt_regression_or_llm_evaluation_tools():
    entries = FactCatalog(profile('Configured GitHub Actions to run API regression tests.')).prompt_entries
    text = 'Knowledge of automated LLM evaluation tools and prompt regression testing.'
    ceiling = named_scope_ceiling(text, entries)
    assert ceiling and 'prompt regression testing' in ceiling[1] and 'LLM evaluation tools' in ceiling[1]
    true_entries = FactCatalog(profile('Used promptfoo for automated LLM evaluation tools and prompt regression testing.')).prompt_entries
    assert named_scope_ceiling(text, true_entries) is None


def test_language_proficiency_condition_cannot_be_hidden_as_context():
    assert needs_assessment({'text': 'English proficiency sufficient for technical documentation.', 'hints': ['preferred']})


def test_negative_advanced_declaration_never_confirms_the_level():
    validator = AnalysisValidator(profile('No advanced Python knowledge. Implemented basic Python scripts.'))
    req = JobRequirement(name='Python', source_quote='Advanced knowledge of Python.', status='strong',
                         reason='Incorrect level claim.', source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status != 'strong'


def test_decorated_preferred_section_corrects_model_priorities():
    from app.models.interpretation import JobInterpretation, ModelRequirement
    from app.models.job import JobRequest
    preferred = ['Knowledge of Python.', 'Knowledge of Docker.', 'Knowledge of Kubernetes.',
                 'Experience with machine learning.', 'Experience with research projects.']
    main = 'Experience with support tickets.'
    text = 'Requirements\n' + main + '\n⭐ Mile widziane\n' + '\n'.join(preferred)
    job = JobRequest(company='Synthetic', role='Analyst', job_description=text)
    interpretation = JobInterpretation(requirements=[ModelRequirement(
        name=quote, source_quote=quote, priority='mandatory', status='missing', source_fact_ids=[],
        reason='Not documented.', operator='single', components=[], classification_basis='Model interpretation')
        for quote in [main, *preferred]], source_context=[
            {'source_quote': 'Requirements'}, {'source_quote': '⭐ Mile widziane'}])
    result = AnalysisValidator(profile()).validate(interpretation.to_analysis(job), text, semantic=True)
    assert sum(r.priority == 'mandatory' for r in result.requirements) == 1
    assert sum(r.priority == 'preferred' for r in result.requirements) == 5


def test_software_testing_scope_does_not_relax_explicit_pentesting_tenure():
    candidate = CandidateProfile(personal={}, experience=[{
        'company': 'Synthetic', 'title': 'Tester', 'start': '2020-01', 'end': '2025-01',
        'facts': ['Designed software test cases and regression tests.']}])
    matcher = EvidenceMatcher(FactCatalog(candidate), as_of=date(2026, 11, 7))
    match = matcher.cited_tenure([e.source_id for e in matcher.entries], 2,
                                 scope='2 years of software testing and penetration testing experience')
    assert match.status == 'missing'


def test_advanced_other_technology_does_not_elevate_basic_python():
    validator = AnalysisValidator(profile('Advanced Linux administration and basic Python scripting.'))
    req = JobRequirement(name='Python', source_quote='Advanced knowledge of Python.', status='strong',
                         reason='Wrong shared qualifier.', source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status == 'partial'


def test_complex_multiple_durations_are_not_deduplicated_by_word_sets():
    from app.services.requirement_equivalence import equivalent_translation
    assert not equivalent_translation(
        '3 lata doświadczenia w testowaniu oprogramowania oraz 5 lat SQL.',
        '5 years of experience in software testing and 3 years SQL.')
