"""Counterexamples found during independent review, beyond the reported batch."""
import pytest

from app.models.candidate import CandidateProfile
from app.models.job import JobRequest, JobRequirement
from app.services.analysis_validator import AnalysisValidator
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment, needs_assessment
from app.services.semantic_requirements import _facts


def validator(fact):
    return AnalysisValidator(CandidateProfile(personal={}, projects=[{'name': 'Synthetic', 'facts': [fact]}]))


@pytest.mark.parametrize('separator', ['. ', '; ', ', but ', ' — '])
def test_salary_cannot_hide_an_embedded_mandatory_condition(separator):
    quote = 'The salary we offer is EUR 30000' + separator + 'you must have experience with SQL.'
    assert needs_assessment({'text': quote, 'hints': ['benefits']})
    profile = CandidateProfile(personal={})
    job = JobRequest(company='Synthetic', role='Engineer', job_description='Benefits\n' + quote)
    inv = AnalysisInventory.build(job, profile)
    rows = [CompactAssessment(p=pid, k='context') for pid in inv.passages]
    report = AnalysisValidator(profile).validate(
        inv.expand(rows).to_analysis(job), job.role + '\n' + job.job_description, semantic=True)
    assert not report.is_reliable
    assert quote in report.unassessed_source_passages


@pytest.mark.parametrize('fact', [
    'Holds an ITIL certification. Attended CISSP training.',
    'Holds an ITIL certification; assisted CISSP-certified colleagues.',
    'Holds an ITIL certification, attended CISSP training.',
    'Holds an ITIL certification and plans to obtain CISSP certification.',
    'Will have obtained CISSP certification next month.',
])
def test_credential_possession_and_named_scope_cannot_come_from_different_clauses(fact):
    v = validator(fact)
    req = JobRequirement(name='Security credential',
                         source_quote='The candidate must hold a certification in:\nCISSP\nCISM',
                         status='strong', source_fact_ids=[e.source_id for e in v.matcher.entries])
    _facts(v, req)
    assert req.status == 'missing'


@pytest.mark.parametrize('fact,expected', [
    ('Configured MFA for an application connected to an Entra ID service owned by another team.', 'partial'),
    ('Discussed Entra ID with colleagues and configured MFA for a self-hosted application.', 'partial'),
    ('Planned Entra ID administration; configured MFA for a self-hosted application.', 'partial'),
    ('Never configured Entra ID, but configured MFA for a self-hosted application.', 'partial'),
    ('Configured MFA without Entra ID.', 'partial'),
    ('Will have configured Entra ID next month; configured MFA for a self-hosted application.', 'partial'),
    ('Administered Microsoft Entra ID and configured MFA.', 'strong'),
    ('Used Entra ID and MFA for an authentication integration.', 'strong'),
])
def test_practical_identity_evidence_must_bind_activity_to_the_requested_product(fact, expected):
    v = validator(fact)
    req = JobRequirement(name='MFA', source_quote='Practical experience with Entra ID and MFA.',
                         status='strong', source_fact_ids=[e.source_id for e in v.matcher.entries])
    _facts(v, req)
    assert req.status == expected


@pytest.mark.parametrize('source,fact,expected', [
    ('The candidate must hold CISSP and CISM certifications.', 'Holds CISSP certification.', 'partial'),
    ('The candidate must hold CISSP and CISM certifications.', 'Holds CISSP certification. Holds CISM certification.', 'strong'),
    ('The candidate must hold CISSP or CISM certification.', 'Holds CISSP certification.', 'strong'),
    ('The candidate must hold a certification in:\nDLP (SC-401 or EDU-222)', 'Holds DLP certification.', 'missing'),
    ('The candidate must hold a certification in:\nDLP (SC-401 or EDU-222)', 'Holds SC-401 certification.', 'strong'),
    ('The candidate must hold a certification in:\nCASB (ExampleVendor)', 'Holds ITIL certification.', 'partial'),
])
def test_credential_identifier_conjunctions_and_families_are_not_flattened(source, fact, expected):
    v = validator(fact)
    req = JobRequirement(name='Professional credential', source_quote=source,
                         status='strong', source_fact_ids=[e.source_id for e in v.matcher.entries])
    _facts(v, req)
    assert req.status == expected
