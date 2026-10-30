"""Synthetic reconstruction of the reported Netige/CodeARM failure; no original model output."""
import pytest

from app.models.candidate import CandidateProfile
from app.models.job import JobRequirement, RequirementComponent
from app.services.analysis_validator import AnalysisValidator
from app.services.fact_catalog import FactCatalog
from tests.test_evidence_matching import candidate

PL = '''Specjalista / Specjalistka IT
Wymagania:
- Experience in IT support
- Znajomość M365 + Entra ID + Intune
Mile widziane
- Linux
Nie masz wszystkiego z tej listy? Aplikuj – resztę nadrobisz u nas
**Oferujemy:**
- Różnorodne środowiska i realny wpływ na ich bezpieczeństwo
- Budżet i czas pracy na szkolenia oraz certyfikaty
- Nowoczesne narzędzia (m.in. własny panel z asystentem AI, monitoring, SIEM)
- Pracę zdalną lub hybrydową – z okazjonalnymi wizytami u klientów'''
EN = '''IT Specialist
Requirements:
Experience in IT support
Nice to have:
Linux
Don't meet every requirement? Apply anyway — you can learn with us.
• **What we offer:**
Diverse environments and an impact on their security
Training and certification budget
Modern tools (e.g. AI assistant, monitoring, SIEM)
Remote or hybrid work with occasional client visits'''


def support_profile(facts=None):
    return CandidateProfile.model_validate({
        'personal': {'name': 'Synthetic'},
        'experience': [{'company': 'Synthetic', 'title': 'IT Support Expert', 'start': '2023', 'end': 'Present',
                        'facts': facts if facts is not None else [
                            'Resolved Windows and Microsoft 365 incidents for end users.',
                            'Diagnozował problemy użytkowników Windows i zarządzał kontami Active Directory.',
                        ]}],
    })


def support_fact_id():
    return next(e.source_id for e in FactCatalog(support_profile()).prompt_entries if ':fact:' in e.source_id)


def analyze(text, profile=None, rows=None):
    draft = candidate()
    draft.requirements = rows or []
    return AnalysisValidator(profile or support_profile()).validate(draft, text, semantic=rows is not None)


SAAS_SOURCE = '''Technical Implementation Specialist – SaaS Integrations
Responsibilities
Configure, implement, and troubleshoot SaaS integrations using REST APIs, webhooks, and JSON.
Support customer-facing technical implementations and software deployments.
Required Technical Skills
Minimum 2 years of hands-on experience in SaaS/software technical roles, including L2/L3 Support, Technical Implementation, Integrations, or Technical Consulting.
REST API integration and troubleshooting.
Webhooks and event-driven integrations.
JSON data formats and API payloads.
Authentication and identity management protocols.
Technical troubleshooting and problem-solving.
Customer-facing SaaS implementation experience.
Jira, Asana, Trello, Monday.com, Notion, or similar project management tools.
Professional Requirements
Native-level English proficiency in written and spoken communication.
Strong technical and non-technical communication skills.
Experience independently leading customer integrations or deployments.
Ability to translate complex technical concepts into clear explanations.
Strong organizational skills and task ownership.
Ability to work autonomously in an async-first remote environment.
Professionalism, patience, and adaptability.
ATS Keywords
Technical Implementation Specialist, SaaS, REST API, Webhooks, JSON, Authentication, Identity Management, Jira.'''


@pytest.mark.parametrize('formatted', [False, True])
def test_saas_requirements_do_not_inherit_responsibility_section(formatted):
    from app.services.job_sections import extract_sections

    text = SAAS_SOURCE
    if formatted:
        for heading in ('Required Technical Skills', 'Professional Requirements', 'ATS Keywords'):
            text = text.replace(heading, f'**{heading}:**')
    units, headings = extract_sections(text)
    assert len([u for u in units if u.category == 'mandatory']) == 15
    assert len([u for u in units if u.category == 'responsibility']) == 2
    assert units[-1].category == 'keywords'
    assert len(headings) == 4
    result = analyze(text)
    assert result.requirements
    assert result.scoring_counts['mandatory_groups'] == 15
    assert len(result.responsibilities) == 2
    assert any(c['category'] == 'keywords' for c in result.source_context)
    assert not any('Technical Implementation Specialist, SaaS' in r.source_quote for r in result.requirements)


def test_saas_keyword_list_cannot_be_promoted_by_model():
    quote = SAAS_SOURCE.splitlines()[-1]
    result = analyze(SAAS_SOURCE, rows=[JobRequirement(
        name='Webhooks', source_quote=quote, status='missing', reason='Not documented',
    )])
    assert not any(r.source_quote == quote for r in result.requirements)
    assert result.classification_issues


def test_full_lancesoft_markdown_source_preserves_overview_for_assessment():
    from app.services.job_sections import extract_sections

    text = '''# Technical Implementation Specialist – SaaS Integrations

**Company:** LanceSoft (Recruitment for an external client)
**Location:** Poland – Fully Remote
**Contract Duration:** 12 months
**Position:** Technical Implementation Specialist

## Role Overview

We are seeking a Technical Implementation Specialist with experience in SaaS platforms, technical support, API integrations, and customer-facing implementation projects.

The role focuses on implementing, configuring, troubleshooting, and supporting integrations between SaaS applications and external customer systems. The successful candidate will work independently, act as a primary technical point of contact, and communicate effectively with both technical and non-technical stakeholders.

## Key Responsibilities

- Configure, implement, and troubleshoot SaaS integrations using REST APIs, webhooks, and JSON.
- Support customer-facing technical implementations and software deployments.
- Troubleshoot integration issues involving authentication, identity management, API communication, and application configuration.
- Act as the primary technical contact for external customers during integrations and deployments.
- Investigate complex technical problems and communicate solutions clearly.
- Coordinate implementation activities and track progress using project management tools.
- Provide technical guidance to customers and non-technical stakeholders.
- Work independently in a remote, asynchronous environment with changing priorities.

'''
    # The technical/professional bullets are the same 15 supplied conditions.
    requirements = SAAS_SOURCE[SAAS_SOURCE.index('Required Technical Skills'):]
    for heading in ('Required Technical Skills', 'Professional Requirements', 'ATS Keywords'):
        requirements = requirements.replace(heading, f'## {heading}')
    requirements = requirements.replace(SAAS_SOURCE.splitlines()[-1],
        'Technical Implementation Specialist, SaaS, Software Integrations, REST API, API Troubleshooting, Webhooks, JSON, Authentication, Identity Management, Technical Support L2, Technical Support L3, Technical Consulting, Customer Integrations, SaaS Implementation, Software Deployment, Customer-Facing Technical Support, Jira, Project Management, Incident Troubleshooting, Technical Communication, Remote Collaboration, Stakeholder Management, Technical Problem Solving.')
    lines = requirements.splitlines()
    text += '\n'.join(line if line.startswith('## ') or index == len(lines) - 1 else '- ' + line
                      for index, line in enumerate(lines))
    units, _ = extract_sections(text)
    assert len([u for u in units if u.category == 'mandatory']) == 15
    assert len([u for u in units if u.category == 'responsibility']) == 7
    assert any(u.category == 'employment' and 'Work independently' in u.quote for u in units)
    overview = [u for u in units if u.section == 'Role Overview']
    assert len(overview) == 2
    assert overview[0].uncertain
    result = analyze(text)
    assert len(result.responsibilities) == 7
    assert any('Native-level English' in r.name for r in result.requirements)
    assert any('Minimum 2 years' in r.name for r in result.requirements)
    assert any(c['category'] == 'keywords' for c in result.source_context)
    # An overview mentioning experience is not silently discarded as marketing.
    assert any('We are seeking' in r.source_quote for r in result.requirements)


@pytest.mark.parametrize('text', [PL, EN])
def test_section_transition_excludes_context_from_scoring(text):
    result = analyze(text)
    assert len(result.requirements) == (3 if text == PL else 2)
    assert {'benefits', 'employment', 'recruitment'} <= {c['category'] for c in result.source_context}
    assert result.scoring_counts['mandatory_groups'] == (2 if text == PL else 1)


@pytest.mark.parametrize('semantic', [False, True])
def test_support_retrieves_duties_even_when_model_omits_evidence(semantic):
    text = 'Requirements\nExperience in IT support'
    rows = [JobRequirement(name='Experience in IT support', source_quote='Experience in IT support',
                           status='missing', reason='Not confirmed in profile')] if semantic else None
    req = analyze(text, rows=rows).requirements[0]
    assert req.status == 'strong'
    assert req.source_fact_ids and all(':fact:' in i for i in req.source_fact_ids)
    absent = analyze(text, support_profile([]), rows=rows).requirements[0]
    assert absent.status == 'missing' and not absent.source_fact_ids


@pytest.mark.parametrize('join,operator,status', [('+', 'all', 'partial'), ('and', 'all', 'partial'),
                                               ('or', 'any', 'strong'), ('lub', 'any', 'strong')])
@pytest.mark.parametrize('semantic', [False, True])
def test_product_components_are_independent(join, operator, status, semantic):
    quote = f'Knowledge of M365 {join} Entra ID {join} Intune'
    rows = [JobRequirement(name=quote, source_quote=quote, status='strong',
                           source_fact_ids=[support_fact_id()], reason='M365 documented')] if semantic else None
    req = analyze('Requirements\n' + quote, rows=rows).requirements[0]
    assert req.operator == operator and req.status == status
    assert [c.status for c in req.components] == ['strong', 'missing', 'missing']
    assert all(not c.source_fact_ids for c in req.components[1:])


def test_examples_do_not_become_cumulative_requirements():
    result = analyze('Requirements\nKnowledge of collaboration tools such as M365, Entra ID and Intune')
    req = result.requirements[0]
    assert req.operator == 'any' and req.status == 'strong'


def test_bad_model_classification_is_removed_and_audited():
    quote = 'Training and certification budget'
    result = analyze(EN, rows=[JobRequirement(name='Certifications', source_quote=quote, status='missing')])
    assert all(r.source_quote != quote for r in result.requirements)
    assert result.classification_issues and not result.is_reliable
    assert not result.completeness_issues  # Coverage and correctness are independent.


def test_unusual_heading_preserves_real_requirement_for_review():
    result = analyze('## Your superpowers:\nKnowledge of PhotonStack')
    assert result.requirements[0].name == 'Knowledge of PhotonStack'
    assert result.requirements[0].interpretation_uncertain
    assert not result.is_reliable


def test_unrelated_valid_fact_does_not_prove_product_component():
    quote = 'Knowledge of M365 and Intune'
    row = JobRequirement(name=quote, source_quote=quote, operator='all', reason='Model claim', components=[
        RequirementComponent(name='M365', status='strong', source_fact_ids=[support_fact_id()]),
        RequirementComponent(name='Intune', status='strong', source_fact_ids=[support_fact_id()]),
    ])
    result = analyze('Requirements\n' + quote, rows=[row])
    assert result.requirements[0].components[1].status == 'missing'
    assert result.evidence_issues and not result.is_reliable


@pytest.mark.parametrize('heading', ['Oferujemy:', '**Oferujemy:**', '• Oferujemy:', '## Oferujemy:',
                                   '1. Oferujemy:', '* **What we offer:**', '__Benefits:__'])
def test_heading_formatting_does_not_leak_priority(heading):
    result = analyze(f'Requirements\nExperience in IT support\nMile widziane:\nLinux\n{heading}\nTraining budget')
    assert [r.name for r in result.requirements] == ['Experience in IT support', 'Linux']


def test_compact_inventory_uses_same_context_boundaries():
    from app.models.job import JobRequest
    from app.services.ollama_analysis import AnalysisInventory

    inventory = AnalysisInventory.build(JobRequest(company='Synthetic', role='IT', job_description=PL), support_profile())
    passages = list(inventory.passages.values())
    assert not next(p for p in passages if 'Oferujemy' in p['text'])['context_only']
    assert passages[0]['context_only']
    assert next(p for p in passages if 'Budżet' in p['text'])['hints'] == ['benefits']
    assert next(p for p in passages if 'wizytami' in p['text'])['hints'] == ['employment']


def test_qualification_in_context_section_is_kept_but_requires_review():
    result = analyze('Requirements\nExperience in IT support\nWhat we offer:\nYou must know PhotonStack')
    assert any('PhotonStack' in r.name for r in result.requirements)
    assert result.classification_issues and not result.is_reliable


@pytest.mark.parametrize('semantic', [False, True])
def test_examples_override_model_and_logic(semantic):
    quote = 'Knowledge of collaboration tools such as M365, Entra ID and Intune'
    rows = [JobRequirement(name=quote, source_quote=quote, operator='all', status='missing', reason='Synthetic bad AND')] if semantic else None
    req = analyze('Requirements\n' + quote, rows=rows).requirements[0]
    assert req.operator == 'any' and req.status == 'strong'


def test_mixed_logic_stays_visible_for_review():
    req = analyze('Requirements\nKnowledge of M365 and Entra ID or Intune').requirements[0]
    assert req.operator == 'ambiguous' and req.interpretation_uncertain


def test_saved_reports_default_to_old_validation_without_mutation():
    report = candidate()
    original = report.model_dump_json()
    assert report.validation_version == 0
    updated = AnalysisValidator(support_profile()).validate(report, 'Requirements\nExperience in IT support')
    assert updated.validation_version == 2 and report.model_dump_json() == original


def test_polish_duties_support_general_it_support():
    req = analyze('Requirements\nExperience in IT support', support_profile([
        'Diagnozował problemy użytkowników Windows i zarządzał kontami Active Directory.',
    ])).requirements[0]
    assert req.status == 'strong' and len(req.source_fact_ids) == 1
    assert ':fact:' in req.source_fact_ids[0]


def test_report_shows_component_results_and_no_unconditional_fallback_success():
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader

    from app.models.job import JobRequest

    result = analyze(PL)
    request = type('Request', (), {'query_params': {}, 'state': type('State', (), {'authenticated': False})()})()
    template = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / 'templates')).get_template('analysis.html')
    args = dict(job=JobRequest(company='Synthetic', role='IT', job_description=PL), request=request,
                fallback_used=True, fallback_reason='Synthetic fallback', token_usage={})
    html = template.render(analysis=result, **args)
    assert 'passed completeness validation' not in html
    assert 'AND — every component must be confirmed.' in html
    assert 'Entra ID</strong> — Not confirmed' in html
    assert 'Intune</strong> — Not confirmed' in html
    assert 'M365</strong> — Confirmed' in html
    legacy = candidate()
    html = template.render(analysis=legacy, **args)
    assert 'Saved report uses older validation rules' in html
    bad = analyze(EN, rows=[JobRequirement(name='Certificates', source_quote='Training and certification budget')])
    html = template.render(analysis=bad, **args)
    assert 'Validation requires review' in html
    assert 'passed completeness validation' not in html


@pytest.mark.parametrize('fact', ['Never resolved Windows incidents for users.',
                                'Nie diagnozował problemów użytkowników Windows.'])
def test_negated_duties_cannot_establish_support(fact):
    req = analyze('Requirements\nExperience in IT support', support_profile([fact])).requirements[0]
    assert req.status != 'strong'
    assert not req.source_fact_ids


@pytest.mark.parametrize('join', ['oraz', 'i'])
def test_polish_conjunctions_retain_all_product_conditions(join):
    req = analyze(f'Wymagania\nZnajomość M365 {join} Entra ID {join} Intune').requirements[0]
    assert req.operator == 'all' and len(req.components) == 3
    assert [c.status for c in req.components] == ['strong', 'missing', 'missing']


def test_unknown_uninterpreted_content_does_not_silently_pass_validation():
    result = analyze('Requirements\nExperience in IT support\n## Your superpowers\nPhotonStack')
    assert any(c['source_quote'] == 'PhotonStack' for c in result.source_context)
    assert result.classification_issues and not result.is_reliable
