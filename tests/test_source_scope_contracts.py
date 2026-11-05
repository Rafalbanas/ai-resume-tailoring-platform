"""Fictional regressions for compound scope and shifted indexed labels."""
import pytest

from app.models.candidate import CandidateProfile, Experience, Project
from app.models.job import JobAnalysis, JobRequest, JobRequirement
from app.services.analysis_validator import AnalysisValidator
from app.services.fact_catalog import FactCatalog
from app.services.named_evidence import named_scope_ceiling
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment, OllamaAnalysisError
from app.services.semantic_requirements import _facts


def candidate(*facts):
    return CandidateProfile(personal={'name': 'Synthetic Candidate'},
                            projects=[Project(name='Synthetic project', facts=list(facts))])


@pytest.mark.parametrize('label,quote,facts', [
    ('CI/CD', 'Znasz AWS, Docker, CI/CD oraz dobre praktyki wytwarzania oprogramowania.',
     ['Configured GitHub Actions CI/CD; the pipeline runs tests and deploys Docker images.']),
    ('Networking', 'Good understanding of networking, including DNS, NSGs, routing, Private Endpoints, VPN, and ExpressRoute.',
     ['Configured DNS, routing and VPN on MikroTik routers.']),
    ('XML and JSON', 'Znajomość XML, JSON.', ['Implemented JSON responses using Python.']),
    ('Web technologies (API, ETL, SQL)', 'Experience with ETL / data analytics platforms.',
     ['Integrated REST APIs and used SQL queries.']),
    ('AI Quality Testing', 'Knowledge of testing AI quality and monitoring LLM models; LLM observability.',
     ['Implemented CI tests and deployment health checks.']),
    ('Linux and Windows proficiency', 'Linux and Windows for vulnerability finding and privilege escalation.',
     ['Administered Linux and Windows and Active Directory users.']),
    ('Project execution', 'Ability to execute multiple projects and drive key business results under tight deadlines.',
     ['Deployed and maintained multiple personal applications on a Linux VPS.']),
    ('Project leadership', 'Ability to learn and lead projects independently, and to work with customers.',
     ['Deployed and maintained a personal application independently.']),
    ('Managed services', 'Experience in managed services.', ['Provided Tier 2 support to partners.']),
])
def test_whole_condition_needs_its_own_scope_not_adjacent_evidence(label, quote, facts):
    validator = AnalysisValidator(candidate(*facts))
    req = JobRequirement(name=label, source_quote=quote, status='strong', reason='Incorrect full match.',
                         source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status != 'strong'
    assert 'Named source scope is not confirmed' in req.reason


@pytest.mark.parametrize('quote,fact', [
    ('Knowledge of AWS, Docker and CI/CD.', 'Used AWS and Docker; configured CI/CD pipelines that run tests.'),
    ('Knowledge of XML and JSON.', 'Implemented XML and JSON parsers.'),
    ('Understanding of DNS, NSGs, Private Endpoints and ExpressRoute.',
     'Configured DNS, NSGs, Private Endpoints and ExpressRoute in a lab.'),
    ('Experience with ETL / data analytics platforms.', 'Implemented ETL jobs on a data analytics platform.'),
    ('Experience with LLM observability.', 'Implemented LLM observability with request traces.'),
    ('Ability to lead projects independently.', 'Led two customer projects independently.'),
])
def test_actual_scope_evidence_is_accepted(quote, fact):
    entries = list(FactCatalog(candidate(fact)).entries.values())
    assert named_scope_ceiling(quote, entries) is None


def test_optional_examples_and_explicit_alternatives_are_not_cumulative():
    entries = list(FactCatalog(candidate('Used JSON and deployed Docker applications.')).entries.values())
    assert named_scope_ceiling('Knowledge of XML or JSON.', entries) is None
    assert named_scope_ceiling('Cloud tooling such as AWS and GCP.', entries) is None


def test_broad_matcher_preserves_cited_evidence_for_an_additional_source_scope():
    validator = AnalysisValidator(candidate('Used AWS for deploying a personal application.',
                                            'Configured GitHub Actions CI/CD; the pipeline runs tests and deploys Docker images.'))
    req = JobRequirement(name='CI/CD', source_quote='Knowledge of AWS, Docker and CI/CD.', status='strong',
                         source_fact_ids=[e.source_id for e in validator.matcher.entries], reason='Confirmed individual scopes.')
    _facts(validator, req)
    assert req.status == 'strong'
    assert any('Used AWS' in text for text in req.evidence)


def test_ticketing_citation_schema_keeps_literal_scope_and_excludes_unrelated_evidence():
    quote = 'Experience with ticketing systems and ITIL practices.'
    job = JobRequest(company='Synthetic', role='Support', job_description='Requirements\n' + quote)
    profile = candidate('Implemented JSON APIs.', 'Used ITIL incident management practices.')
    profile.experience = [Experience(company='Example Ltd', title='Support', start='2020-01', end='2025-01',
                                     facts=['Managed support tickets in Salesforce.'])]
    inv = AnalysisInventory.build(job, profile)
    pid = next(pid for pid, p in inv.passages.items() if p['text'] == quote)
    schema = inv.keyed_schema([pid])
    ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    fields = schema['$defs'][ref]['properties']
    assert fields['n']['enum'] == [quote]
    evidence = [inv.evidence[fid].text for fid in fields['f']['items']['enum']]
    assert any('Salesforce' in text for text in evidence)
    assert any('ITIL' in text for text in evidence)
    assert not any('JSON APIs' in text for text in evidence)


def test_example_in_short_label_does_not_override_the_literal_generic_condition():
    validator = AnalysisValidator(candidate('Managed support tickets in Salesforce.'))
    req = JobRequirement(name='Experience with support ticketing systems (Zendesk)',
                         source_quote='Experience with support ticketing systems such as Zendesk.',
                         status='strong', reason='The requested scope is generic ticketing.')
    _facts(validator, req)
    assert req.status == 'strong'
    assert any('Salesforce' in text for text in req.evidence)


def inventory_for(quote):
    job = JobRequest(company='Synthetic', role='Monitoring Specialist', job_description='Nasze wymagania:\n' + quote)
    inventory = AnalysisInventory.build(job, candidate('Analyzed application logs to resolve incidents.'))
    pid = next(pid for pid, p in inventory.passages.items() if p['text'] == quote)
    return job, inventory, pid


def test_shifted_label_rejected_before_indexed_expansion():
    quote = 'Gotowość do pracy w systemie zmianowym i pracy stacjonarnej.'
    _, inv, pid = inventory_for(quote)
    with pytest.raises(OllamaAnalysisError, match='does not describe'):
        inv.validate_rows([CompactAssessment(p=pid, k='requirement', n='Analytical thinking', s='strong', why='Analyzed logs.')], [pid])


def test_availability_schema_and_portable_rows_cannot_borrow_technical_evidence():
    quote = 'Gotowość do pracy w systemie zmianowym i pracy stacjonarnej.'
    _, inv, pid = inventory_for(quote)
    schema = inv.keyed_schema([pid])
    ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    fields = schema['$defs'][ref]['properties']
    assert fields['n']['enum'] == [quote]
    assert fields['s']['enum'] == ['missing']
    assert fields['f']['maxItems'] == fields['c']['maxItems'] == 0
    row = inv.validate_rows([CompactAssessment(p=pid, k='requirement', n='Shift availability', s='strong',
                                              f=list(inv.evidence), why='Analyzed logs.')], [pid])[0]
    assert row.s == 'missing' and not row.f and not row.c
    assert row.n == quote


def test_independent_validator_blocks_shifted_label_and_never_confirms_availability():
    quote = 'Gotowość do pracy w systemie zmianowym i pracy stacjonarnej.'
    job, inv, pid = inventory_for(quote)
    rows = [CompactAssessment(p=p, k='context') for p in inv.passages if p != pid]
    rows += [CompactAssessment(p=pid, k='requirement', n='Analytical thinking', s='strong',
                               f=list(inv.evidence), why='Analyzed logs.')]
    report = AnalysisValidator(inv.matcher.catalog.profile).validate(inv.expand(rows).to_analysis(job), job.job_description, semantic=True)
    assert not report.is_reliable
    req = next(r for r in report.requirements if r.source_quote == quote)
    assert req.status == 'missing'
    assert req.name == quote
    assert not req.source_fact_ids
    assert 'personal confirmation' in req.reason
    assert report.match_sources[quote] == []
    assert 'Analytical thinking' not in report.match_sources


@pytest.mark.parametrize('quote', ['Podstawy działania sieci.', 'Podstawowa wiedza o cyberbezpieczeństwie.',
                                  'Certyfikaty z obszaru cyberbezpieczeństwa.',
                                  'Exposure to web technologies and related stacks (API, ETL, SQL).',
                                  'A consultative mindset with genuine empathy.'])
def test_explicit_conditions_cannot_disappear_into_context(quote):
    job, inv, _ = inventory_for(quote)
    report = AnalysisValidator(candidate()).validate(inv.expand([CompactAssessment(p=p, k='context') for p in inv.passages]).to_analysis(job),
                                                      job.job_description, semantic=True)
    assert not report.is_reliable
    assert quote in report.unassessed_source_passages


def test_tenure_arithmetic_cannot_restore_unproven_named_scope():
    profile = candidate()
    profile.experience = [Experience(company='Synthetic', title='Developer', start='2017-01', end='2025-01',
                                     facts=['Developed Python APIs and Docker applications.'])]
    validator = AnalysisValidator(profile)
    quote = 'Minimum 2 years of experience with AWS and Docker.'
    req = JobRequirement(name='Cloud development', source_quote=quote, status='strong', reason='Claims full match.',
                         source_fact_ids=[e.source_id for e in validator.matcher.entries if e.kind == 'experience'])
    analysis = JobAnalysis(company='Synthetic', role='Developer', requirements=[req], strong_matches=[], partial_matches=[],
                           missing_requirements=[], recommendation='REVIEW', match_level='LOW')
    report = validator.validate(analysis, 'Requirements\n' + quote, semantic=True)
    assert all(r.status != 'strong' for r in report.requirements)


@pytest.mark.parametrize('quote', ['Knowledge of AWS and Docker.', 'Fluent English communication skills.',
                                  'Zaawansowana znajomość języka angielskiego.'])
def test_generation_schema_forbids_a_known_unprovable_full_confirmation(quote):
    _, inv, pid = inventory_for(quote)
    schema = inv.keyed_schema([pid])
    ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    allowed = schema['$defs'][ref]['properties']['s']['enum']
    assert allowed and 'strong' not in allowed


def test_long_availability_condition_keeps_full_quote_without_an_invalid_label_enum():
    quote = ('Gotowość do pracy w systemie zmianowym i pracy stacjonarnej. ' + 'Additional office scheduling details. ' * 5).strip()
    job, inv, pid = inventory_for(quote)
    schema = inv.keyed_schema([pid])
    ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    fields = schema['$defs'][ref]['properties']
    label = fields['n']['enum'][0]
    assert len(label) <= 120
    row = CompactAssessment(p=pid, k='requirement', n=label, s='missing', why=fields['why']['enum'][0])
    report = inv.expand(inv.validate_rows([row], [pid])).to_analysis(job)
    assert report.requirements[0].source_quote == quote


def test_explicit_consultative_condition_is_a_qualification_under_an_unfamiliar_heading():
    quote = 'A consultative mindset with genuine empathy.'
    job = JobRequest(company='Synthetic', role='Support', job_description='We are excited if you have:\n' + quote)
    inv = AnalysisInventory.build(job, candidate())
    pid = next(pid for pid, p in inv.passages.items() if p['text'] == quote)
    row = inv.validate_rows([CompactAssessment(p=pid, k='competency', n='Consultative mindset', s='missing', why='Not confirmed.')], [pid])[0]
    assert row.k == 'requirement' and row.priority == 'mandatory'


async def test_source_ceilings_enable_a_correct_single_call_without_waiving_final_validation():
    import json

    import httpx

    from app.core.config import Settings
    from app.services.ollama_provider import OllamaProvider
    profile = candidate('Configured GitHub Actions CI/CD; the pipeline runs tests and deploys Docker images.')
    profile.summary_facts = ['Uses English at B2 level in daily professional work.']
    job = JobRequest(company='Synthetic', role='Engineer', job_description=(
        'Requirements\nKnowledge of AWS, Docker and CI/CD.\nFluent English communication skills.'))
    inv = AnalysisInventory.build(job, profile)
    ci = next(fid for fid, entry in inv.evidence.items() if 'Configured GitHub Actions' in entry.text)
    english = next(fid for fid, entry in inv.evidence.items() if 'English at B2' in entry.text)
    calls = []
    async def handler(request):
        body = json.loads(request.content)
        payload = json.loads(body['messages'][1]['content'])
        calls.append(body)
        assessments = {}
        for passage in payload['passages']:
            pid, text = passage['id'], passage['text']
            if text in {'Engineer', 'Requirements'}:
                assessments[pid] = {'k': 'context'}
            else:
                ref = body['format']['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
                assert 'strong' not in body['format']['$defs'][ref]['properties']['s']['enum']
                assessments[pid] = {'k': 'requirement', 'n': 'CI/CD' if 'AWS' in text else 'English fluency',
                                     's': 'partial', 'f': [ci if 'AWS' in text else english], 'priority': 'mandatory',
                                     'why': 'Related documented evidence; full source scope is not confirmed.'}
        return httpx.Response(200, json={'message': {'content': json.dumps({'assessments': assessments})}, 'done': True})
    provider = OllamaProvider(Settings(_env_file=None), transport=httpx.MockTransport(handler))
    report = await provider.analyze_job(job, profile)
    assert report.is_reliable
    assert len(calls) == 1
    assert {r.status for r in report.requirements} == {'partial'}
