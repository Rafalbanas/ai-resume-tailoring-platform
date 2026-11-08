"""Fictional regressions for false whole-condition confirmations and coverage."""
import pytest

from app.models.candidate import CandidateProfile
from app.models.job import JobRequest, JobRequirement
from app.services.analysis_validator import AnalysisValidator
from app.services.evidence_matching import EvidenceMatcher
from app.services.fact_catalog import FactCatalog
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment, assessment_priority, needs_assessment
from app.services.semantic_requirements import _facts


def profile(*facts):
    return CandidateProfile(personal={'name': 'Synthetic'}, projects=[{'name': 'Synthetic lab', 'facts': list(facts)}])


IDENTITY = 'Practical experience with Microsoft Entra ID, MFA, Conditional Access and identity security.'


@pytest.mark.parametrize('label', ['MFA', 'Entra ID & MFA', 'Identity administration'])
@pytest.mark.parametrize('components', [False, True])
def test_mfa_only_cannot_confirm_a_combined_identity_source(label, components):
    from app.models.job import RequirementComponent
    validator = AnalysisValidator(profile('Configured MFA for a self-hosted example application.'))
    ids = [e.source_id for e in validator.matcher.entries]
    req = JobRequirement(name=label, source_quote=IDENTITY, status='strong', source_fact_ids=ids,
                         reason='Incorrect model confirmation.', operator='all' if components else 'single')
    if components:
        req.components = [RequirementComponent(name='MFA', status='strong', source_fact_ids=ids)]
    job = JobRequest(company='Synthetic', role='Administrator', job_description='Requirements\n' + IDENTITY)
    from app.models.job import JobAnalysis
    candidate = JobAnalysis(company='Synthetic', role='Administrator', requirements=[req],
                            strong_matches=[], partial_matches=[], missing_requirements=[],
                            recommendation='REVIEW', match_level='LOW',
                            source_context=[{'source_quote': 'Requirements'}])
    result = validator.validate(candidate, job.job_description, semantic=True)
    assert result.requirements[0].status != 'strong'
    assert 'Entra' in result.requirements[0].reason or result.requirements[0].interpretation_uncertain


@pytest.mark.parametrize('name', ['Entra ID & MFA', 'MFA and Conditional Access', 'Azure AD and MFA'])
def test_direct_security_match_checks_every_named_identity_facet(name):
    matcher = EvidenceMatcher(FactCatalog(profile('Configured MFA for a self-hosted example application.')))
    assert matcher.match(name).status != 'strong'


def test_full_identity_evidence_can_still_confirm_all_scopes():
    validator = AnalysisValidator(profile('Administered Microsoft Entra ID, configured MFA, Conditional Access and identity security.'))
    req = JobRequirement(name='Entra ID & MFA', source_quote=IDENTITY, status='strong',
                         source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status == 'strong'


def test_positive_status_with_explicit_evidence_denial_requires_review():
    validator = AnalysisValidator(profile('Used SQL for operational queries.'))
    req = JobRequirement(name='Contract negotiation', source_quote='Ability to negotiate commercial contracts.',
                         status='strong', reason='No evidence of contract negotiation.',
                         source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status != 'strong'
    assert req.interpretation_uncertain
    assert validator._evidence_issues


@pytest.mark.parametrize('name', ['MFA or Entra ID', 'Conditional Access lub MFA', 'MFA, Entra ID or Conditional Access'])
def test_pure_identity_alternatives_keep_their_or_meaning(name):
    matcher = EvidenceMatcher(FactCatalog(profile('Configured MFA for a self-hosted example application.')))
    assert matcher.match(name).status == 'strong'


def test_short_label_does_not_erase_mixed_identity_and_or_scope():
    validator = AnalysisValidator(profile('Configured MFA for a self-hosted example application.'))
    req = JobRequirement(name='MFA', source_quote='Knowledge of MFA and Entra ID or Conditional Access.',
                         status='strong', source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status != 'strong'
    assert req.interpretation_uncertain


@pytest.mark.parametrize('quote', [
    'The salary expectations of the candidate must be provided.',
    'The salary we offer is EUR 30000. You must have experience with SQL.',
])
def test_compensation_word_does_not_hide_an_actual_candidate_mandate(quote):
    from app.services.source_dispositions import employer_offer_context
    assert not employer_offer_context(quote)


def test_mixed_compensation_and_qualification_paragraph_still_needs_assessment():
    quote = 'The salary we offer is EUR 30000. You must have experience with SQL.'
    assert needs_assessment({'text': quote, 'hints': ['benefits']})


SALARY = ('The base salary we offer is EUR 25000 to 35000 per year depending on experience. '
          'Apply now if you want to join our team.')
CONDITIONS = [
    'Dużym plusem będzie MCP.',
    'Proven ability to develop strategic customer relationships.',
    'Strategic relationship development and executive stakeholder engagement.',
    'Highly adept with support tools, including ticketing systems and communication platforms.',
    'Certyfikaty związane z zarządzaniem usługami IT, np. ITIL.',
    'Jasna komunikacja i współpraca z użytkownikami oraz zespołem.',
    'Abiliy to work independently and communicate effectively with stakeholders.',
    'The successful candidate must hold at least one professional certification in:',
]


def inventory(source):
    candidate = profile()
    job = JobRequest(company='Synthetic', role='Engineer', job_description='JOB DESCRIPTION\n' + source)
    return job, candidate, AnalysisInventory.build(job, candidate)


@pytest.mark.parametrize('quote', CONDITIONS)
@pytest.mark.parametrize('kind', ['context', 'responsibility', 'competency'])
def test_nominal_and_colon_conditions_cannot_disappear_in_complete_dispositions(quote, kind):
    job, candidate, inv = inventory('Requirements\n' + quote)
    rows = [CompactAssessment(p=pid, k=kind, n='Candidate capability', why='Not documented.')
            if p['text'] == quote else CompactAssessment(p=pid, k='context') for pid, p in inv.passages.items()]
    result = AnalysisValidator(candidate).validate(
        inv.expand(rows).to_analysis(job), job.role + '\n' + job.job_description, semantic=True)
    assert not result.is_reliable
    assert quote in result.unassessed_source_passages


@pytest.mark.parametrize('kind', ['requirement', 'competency'])
def test_offered_salary_is_never_a_candidate_gap_in_schema_or_final_validation(kind):
    from app.services.source_dispositions import known_source_context
    job, candidate, inv = inventory('Requirements\nKnowledge of Linux\n' + SALARY)
    pid = next(pid for pid, p in inv.passages.items() if p['text'] == SALARY)
    assert not needs_assessment(inv.passages[pid])
    assert known_source_context(inv.passages[pid])
    rows = [CompactAssessment(p=p, k=kind, n='Salary expectation', why='Not documented.') if p == pid
            else CompactAssessment(p=p, k='requirement', n='Linux', why='Not documented.', priority='mandatory')
            if passage['text'] == 'Knowledge of Linux' else CompactAssessment(p=p, k='context')
            for p, passage in inv.passages.items()]
    assert next(row for row in inv.validate_rows(rows, list(inv.passages)) if row.p == pid).k == 'context'
    result = AnalysisValidator(candidate).validate(
        inv.expand(rows).to_analysis(job), job.role + '\n' + job.job_description, semantic=True)
    assert result.is_reliable, result.completeness_issues
    assert len(result.requirements) == 1
    assert not any(r.source_quote == SALARY for r in result.role_competencies)


def test_leading_polish_plus_is_preferred_not_mandatory():
    assert assessment_priority({'text': CONDITIONS[0], 'hints': ['mandatory']}) == 'preferred'


def test_must_hold_certification_colon_is_not_an_administrative_heading():
    job, _, inv = inventory('Requirements\n' + CONDITIONS[-1] + '\nCISSP\nCISM')
    pid, passage = next((pid, p) for pid, p in inv.passages.items() if p['text'] == CONDITIONS[-1])
    assert needs_assessment(passage)
    assert assessment_priority(passage) == 'mandatory'
    schema = inv.keyed_schema([pid])
    ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    assert schema['$defs'][ref]['properties']['k']['enum'] == ['requirement']


def test_assessing_only_open_certification_header_does_not_prove_complete_coverage():
    quote = CONDITIONS[-1]
    job, candidate, inv = inventory('Requirements\n' + quote + '\nCISSP\nCISM')
    rows = [CompactAssessment(p=pid, k='requirement', n='Professional certification', why='Not documented.')
            if p['text'] == quote else CompactAssessment(p=pid, k='context') for pid, p in inv.passages.items()]
    report = AnalysisValidator(candidate).validate(
        inv.expand(rows).to_analysis(job), job.role + '\n' + job.job_description, semantic=True)
    assert not report.is_reliable
    assert quote in report.unassessed_source_passages


def test_open_certification_cannot_be_closed_by_an_unrelated_source_quote():
    from app.services.source_classification import _continuation_quotes
    header = CONDITIONS[-1]
    source = 'Knowledge of Linux\n' + header + '\nCISSP\nCISM\nResponsibilities\nMaintain integrations.'
    assert _continuation_quotes(header, source) == {'CISSP', 'CISM'}


def test_credential_scope_in_secondary_quote_is_still_enforced():
    validator = AnalysisValidator(profile('Earned an ITIL certification.'))
    req = JobRequirement(name='Professional credential', source_quote='The candidate must hold a certification in:',
                         source_quotes=['The candidate must hold a certification in:', 'CISSP'],
                         status='strong', source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status == 'missing'


@pytest.mark.parametrize('fact,expected', [
    ('Configured security controls for a self-hosted application.', 'missing'),
    ('Earned an unrelated ITIL certification.', 'missing'),
    ('Does not hold CISSP certification.', 'missing'),
    ('Holds an expired CISSP certification.', 'missing'),
    ('Studying for CISSP certification.', 'missing'),
    ('Holds CISSP certification.', 'strong'),
])
def test_credential_choice_is_not_proved_by_product_use_or_an_unlisted_certificate(fact, expected):
    validator = AnalysisValidator(profile(fact))
    req = JobRequirement(name='Professional credential',
                         source_quote='The candidate must hold a certification in:\nCISSP\nCISM',
                         status='strong', source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status == expected


@pytest.mark.asyncio
@pytest.mark.parametrize('recover', [False, True])
async def test_new_conditions_have_bounded_recovery_and_salary_never_becomes_a_gap(recover):
    from app.services.ai_provider import ProviderResponseError
    from app.services.indexed_analysis import indexed_interpretation
    from app.services.ollama_analysis import CompactInterpretation
    quotes = CONDITIONS[:-1]
    job, candidate, inv = inventory('Requirements\n' + '\n'.join(quotes) + '\n' + SALARY)
    calls = []

    class Provider:
        async def _chat(self, model, prompt, payload, **kwargs):
            calls.append(payload)
            rows = []
            for p in payload['passages']:
                if p['text'] == SALARY or (recover and len(calls) > 1 and p['text'] in quotes):
                    rows.append(CompactAssessment(p=p['id'], k='requirement', n=p['text'][:100],
                                                  priority='mandatory', why='Not documented.'))
                else:
                    rows.append(CompactAssessment(p=p['id'], k='context'))
            return CompactInterpretation(rows=rows)

    if not recover:
        with pytest.raises(ProviderResponseError, match='bounded recovery'):
            await indexed_interpretation(Provider(), inv)
    else:
        result = await indexed_interpretation(Provider(), inv)
        report = AnalysisValidator(candidate).validate(
            result.to_analysis(job), job.role + '\n' + job.job_description, semantic=True)
        assert report.is_reliable, report.completeness_issues
        assert len(report.requirements) == len(quotes)
        assert not any(r.source_quote == SALARY for r in report.requirements)
        assert all(r.status == 'missing' and not r.source_fact_ids for r in report.requirements)
        assert next(r for r in report.requirements if r.source_quote == CONDITIONS[0]).priority == 'preferred'
    assert len(calls) == 2
    assert {p['text'] for p in calls[1]['passages']} == set(quotes)
