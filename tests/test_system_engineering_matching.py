from datetime import date

import pytest

from app.models.candidate import CandidateProfile, Project
from app.models.job import JobAnalysis
from app.services.analysis_validator import AnalysisValidator
from app.services.evidence_matching import EvidenceMatcher


def profile():
    return CandidateProfile.model_validate({
        'personal': {'name': 'Example Candidate'},
        'skills': {'programming': ['Python'], 'languages': ['English B2']},
        'education': [{'institution': 'Example University', 'qualification': 'MSc Computer Science', 'dates': '2026'}],
        'experience': [
            {'company': 'Infrastructure', 'title': 'IT Specialist', 'start': 'Mar 2023', 'end': 'May 2024', 'facts': [
                'Deployed and configured Windows Server and VMware ESXi environments.',
                'Managed Active Directory access.',
            ]},
            {'company': 'Operations', 'title': 'IT Specialist', 'start': 'Jun 2024', 'end': 'Aug 2025', 'facts': [
                'Administered Active Directory users, groups and access.',
                'Automated operational tasks using PowerShell and Python.',
                'Supported VPN and tunnel operations.',
            ]},
            {'company': 'Clients', 'title': 'IT Specialist', 'start': 'Oct 2025', 'end': 'Jan 2026', 'facts': [
                'Supported Windows 11 and Active Directory for internal users.',
                'Troubleshot network, DNS, DHCP and VPN issues.',
            ]},
            {'company': 'Applications', 'title': 'Technical Support Engineer', 'start': 'Apr 2026', 'end': 'Present', 'facts': [
                'Troubleshoots Windows application and connectivity issues.',
            ]},
        ],
    })


def evaluate(text, candidate=None):
    p = candidate or profile()
    validator = AnalysisValidator(p)
    validator.matcher = EvidenceMatcher(validator.catalog, as_of=date(2026, 10, 11))
    suggestion = JobAnalysis(company='Example', role='Systems', strong_matches=[], partial_matches=[], missing_requirements=[], recommendation='REVIEW', match_level='LOW')
    return validator.validate(suggestion, text)


def test_windows_server_client_practice_and_solid_level():
    result = evaluate('Requirements\nKnowledge of Microsoft Server and Client environments\nSolid knowledge of Microsoft Server and Client environments')
    practice, solid = result.requirements
    assert practice.status == 'strong'
    assert solid.status == 'partial'
    assert solid.required_level == 'Solid'
    assert {s['owner'].split(' — ')[1] for s in solid.evidence_sources} == {'Infrastructure', 'Clients'}
    p = profile()
    p.experience = p.experience[:1]
    assert evaluate('Requirements\nKnowledge of Microsoft Server and Client environments', p).requirements[0].status == 'partial'


def test_similar_systems_roles_are_counted_but_exact_scope_is_separate():
    broad = evaluate('Requirements\n3+ years of professional experience in system engineering or a similar role').requirements[0]
    exact = evaluate('Requirements\n3+ years of professional experience in system engineering').requirements[0]
    assert broad.status == 'strong' and broad.observed_years == 3.37
    assert exact.status == 'partial' and exact.observed_years == 2.51
    assert 'related Windows/network' in broad.reason
    assert len({s['owner'] for s in broad.evidence_sources}) == 4
    cloud = evaluate('Requirements\n3 years of Azure system engineering or a similar role').requirements[0]
    assert cloud.observed_years == 0 and cloud.status == 'missing'


def test_tenure_excludes_overlaps_gaps_titles_and_undated_work():
    p = profile()
    p.experience[1].start = 'Apr 2023'
    p.experience[1].end = 'Apr 2024'
    p.experience[2].facts = ['Wrote user documentation.']
    p.experience[2].title = 'System Engineer'
    p.experience[3].start = '2026'
    r = evaluate('Requirements\n3 years system engineering or similar role', p).requirements[0]
    assert r.observed_years == 1.25 and r.status == 'partial'


@pytest.mark.parametrize('name, expected', [
    ('Familiarity with PowerShell scripting and automation', 'strong'),
    ('Advanced PowerShell scripting and automation', 'partial'),
])
def test_powershell_automation_level(name, expected):
    r = evaluate('Requirements\n' + name).requirements[0]
    assert r.status == expected
    assert r.evidence_sources[0]['type'] == 'experience'


def test_powershell_name_does_not_prove_scripts():
    p = profile()
    p.experience = []
    p.skills = {'programming': ['PowerShell']}
    assert evaluate('Requirements\nFamiliarity with PowerShell scripting and automation', p).requirements[0].status == 'partial'


@pytest.mark.parametrize('suffix, priority', [('preferred', 'preferred'), ('nice to have', 'preferred'), ('big plus', 'preferred'), ('advantage', 'preferred'), ('considered an advantage', 'preferred'), ('optional', 'nice_to_have')])
def test_arrow_semicolon_preference_suffix(suffix, priority):
    r = evaluate(f'Requirements\n-> Experience with cloud virtual desktops ({suffix});').requirements[0]
    assert r.priority == priority and r.status == 'missing'
    assert not r.name.endswith('(')
    assert r.source_quote.endswith(';')
    assert r.name.startswith('Experience')
    assert evaluate(f'Requirements\n-> Python ({suffix});').scoring_counts['mandatory_groups'] == 0


def test_mixed_powershell_python_and_language_clauses():
    text = 'Requirements\n-> Familiarity with PowerShell scripting and automation; knowledge of Python is considered an advantage;\n-> Fluent English (German or other languages are a plus).'
    result = evaluate(text)
    powershell, python, english, german = result.requirements
    assert (powershell.priority, powershell.status) == ('mandatory', 'strong')
    assert (python.priority, python.status) == ('preferred', 'strong')
    assert (english.priority, english.status) == ('mandatory', 'partial')
    assert german.priority == 'preferred'
    assert powershell.source_quote == python.source_quote
    assert result.scoring_counts == {'mandatory_groups': 2, 'confirmed': 1, 'partial': 1, 'not_confirmed_or_gap': 0, 'duplicate_rows': 0}


def test_security_scopes_need_individual_practice():
    result = evaluate('Requirements\nGood understanding of IT security practices (endpoint protection, compliance, monitoring)\nAccess management\nSecurity policies / GPO\nPatch management\nSecurity monitoring\nVPN\nMFA\nIdentity security')
    general, access, gpo, patch, monitoring, vpn, mfa, identity = result.requirements
    assert general.status == 'partial'
    assert 'security monitoring' in general.clarification_needed
    assert access.status == vpn.status == 'strong'
    assert all(r.status == 'missing' for r in (gpo, patch, monitoring, mfa, identity))
    assert not result.requirement_counts['confirmed_absence']
    p = profile()
    p.projects = [Project(name='Endpoint lab', facts=['Configured Microsoft Defender endpoint protection and security monitoring.', 'Deployed security patches and configured Group Policy security policies.'])]
    with_evidence = evaluate('Requirements\nEndpoint protection\nSecurity monitoring\nGroup Policy\nPatch management', p)
    assert all(r.status == 'strong' for r in with_evidence.requirements)
    assert all(r.evidence_sources[0]['type'] == 'project' for r in with_evidence.requirements)


def test_directory_scopes_do_not_equate_ad_with_entra_or_gpo():
    r = evaluate('Requirements\nHands-on experience with A D / Entra ID, DNS, DHCP, and GPO').requirements[0]
    assert r.status == 'partial'
    assert 'Entra ID, GPO' in r.clarification_needed
    assert any('Active Directory' in text for text in r.evidence)


def test_absence_remains_distinct_from_unknown_security():
    p = profile()
    p.summary_facts = ['No experience with endpoint protection.']
    r = evaluate('Requirements\nEndpoint protection', p).requirements[0]
    assert r.status == 'absent'


def test_saved_cloud_microsoft_offer_counts_and_unconfirmed_cloud():
    from pathlib import Path
    result = evaluate(Path('tests/fixtures/system_engineering_requirements.txt').read_text())
    assert result.is_reliable
    assert result.match_level == 'MEDIUM'
    assert result.requirement_counts == {'mandatory': 8, 'preferred': 6, 'confirmed': 6, 'partial': 4, 'not_confirmed': 4, 'confirmed_absence': 0}
    assert result.scoring_counts['mandatory_groups'] == 8
    mandatory = [r for r in result.requirements if r.priority == 'mandatory']
    assert sum(r.status == 'strong' for r in mandatory) == 3
    assert sum(r.priority == 'nice_to_have' for r in result.requirements) == 1
    cloud = next(r for r in mandatory if 'cloud platforms' in r.name)
    assert cloud.status == 'missing'
