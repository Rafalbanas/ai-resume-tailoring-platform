"""Regression coverage for the public AirHelp offer's section layout."""

import pytest

from app.models.job import JobAnalysis
from app.services.analysis_validator import AnalysisValidator
from app.services.job_sections import extract_sections

BENEFITS = [
    'Opportunity to make an immediate impact: support a tech-first international environment.',
    'Continuous learning & growth: certification budgets and hands-on exposure to enterprise systems.',
    'Culture of autonomy and support: initiative and process improvements are welcome.',
]
DUTIES = [
    'First-line Technical Support: Act as the primary point of contact via Jira Service Management and Slack.',
    'User Lifecycle Management: Manage onboarding and offboarding, provisioning laptops and system accounts.',
    'Hardware & Asset Administration: Maintain asset inventory and device lifecycle logistics.',
    'Office Infrastructure Support: Troubleshoot AV systems, Wi-Fi and printer configurations.',
    'Security & Compliance: Enforce MFA, password hygiene, device encryption and zero-trust principles.',
    'Documentation & Self-Service: Maintain Confluence knowledge base articles and user-facing guides.',
]
QUALIFICATIONS = [
    'Relevant Background: 1+ years of experience in first-line IT Support, Helpdesk, or Desktop Support (or a relevant academic background in Computer Science/IT with strong hands-on project experience).',
    'System Familiarity: good understanding of macOS environments, common peripheral setups, and basic networking principles (TCP/IP, DNS, VPNs, DHCP, Wi-Fi).',
    'Identity Experience: hands-on exposure or familiarity with Google Workspace, Microsoft 365 or Okta administration.',
    'Customer-Centric Mindset: strong problem-solving instincts paired with patience, empathy, and a strong drive to deliver an exceptional internal employee experience.',
    'Ownership & Initiative: curiosity to learn new technologies, proactive follow-through on open issues, and a desire to automate repetitive tasks where possible.',
    'Communication Skills: fluent written and spoken English (B2/C1+) - you will support international team members daily across multiple time zones.',
]
CLOSING = [
    'Fast Impact: Your daily work directly keeps the team productive and secure.',
    'Growth: Personal development budget, learning days, certification support and language classes.',
    'Perks: Private healthcare, wellness budget, travel stipend and gym subsidy.',
]


def offer(duty_heading="What you'll achieve", company='AirHelp'):
    return '\n'.join([
        'JOB DESCRIPTION', f'{company} is a global travel tech company.',
        'What can you expect from us:', *BENEFITS,
        duty_heading, *DUTIES,
        'What sets you apart:', *QUALIFICATIONS,
        f'Why {company}?', *CLOSING,
        'TECH STACK', 'IT Support', 'regular',
    ])


@pytest.mark.parametrize('heading', ["What you'll achieve", 'What you’ll achieve:', 'What you will achieve'])
@pytest.mark.parametrize('company', ['AirHelp', 'Example Travel'])
def test_offer_sections_keep_all_qualifications_and_separate_context(heading, company):
    units, _ = extract_sections(offer(heading, company))
    assert [u.quote for u in units if u.category == 'mandatory'] == QUALIFICATIONS
    assert [u.quote for u in units if u.category == 'responsibility'] == DUTIES
    assert [u.quote for u in units if u.category == 'benefits'] == BENEFITS + CLOSING
    stack = [u for u in units if u.category == 'competency']
    assert len(stack) == 1
    assert stack[0].quote == 'IT Support'
    assert stack[0].level == 'regular'
    assert stack[0].supporting_quotes == ['regular']


def test_validator_recovers_qualifications_when_model_returns_no_requirements(profile):
    empty_analysis = JobAnalysis(
        company='Example', role='Support', strong_matches=[], partial_matches=[], missing_requirements=[],
        recommendation='SKIP', match_level='LOW',
    )
    result = AnalysisValidator(profile).validate(empty_analysis, offer())
    recovered = [r for r in result.requirements if r.priority == 'mandatory']
    assert [r.source_quote for r in recovered] == QUALIFICATIONS
    assert not any(r.source_quote in BENEFITS + DUTIES + CLOSING for r in result.requirements)
