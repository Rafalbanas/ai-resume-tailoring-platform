from datetime import date
from pathlib import Path

import pytest

from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis
from app.services.analysis_validator import AnalysisValidator
from app.services.evidence_matching import EvidenceMatcher
from app.services.fact_catalog import FactCatalog
from app.services.job_extractors.nofluff import NoFluffExtractor


def candidate():
    return JobAnalysis(company='Example', role='Support', strong_matches=[], partial_matches=[],
                       missing_requirements=[], recommendation='REVIEW', match_level='LOW')


@pytest.fixture
def contextual_profile():
    return CandidateProfile.model_validate({
        'personal': {'name': 'Synthetic Candidate'},
        'skills': {'languages': ['English B2', 'Polish Native'], 'programming': ['Python']},
        'experience': [
            {'company': 'Example Operations', 'title': 'IT Specialist', 'start': 'Mar 2023', 'end': 'May 2024', 'facts': [
                'Provided L1 and L2 technical support to users.',
                'Used MS SQL Server and T-SQL for operational queries, troubleshooting and data verification.',
                'Investigated application and network incidents and analyzed logs to identify root causes.',
            ]},
            {'company': 'Example Support', 'title': 'IT Specialist', 'start': 'Jun 2024', 'end': 'Aug 2025', 'facts': [
                'Provided L1 and L2 user support and investigated technical incidents.',
                'Automated operational tasks using PowerShell and Python.',
            ]},
            {'company': 'Example Services', 'title': 'IT Specialist', 'start': 'Oct 2025', 'end': 'Jan 2026', 'facts': [
                'Supported Windows applications for internal users.',
            ]},
            {'company': 'Example Telecom', 'title': 'Technical Support Engineer', 'start': 'Apr 2026', 'end': 'Present', 'facts': [
                'Provides Tier 2 technical support and troubleshoots application issues.',
                'Manages partner support cases and escalates complex cases to Tier 3 engineering.',
            ]},
        ],
        'projects': [{'name': 'Example API client', 'technologies': ['Python', 'HTTPX', 'JSON', 'JavaScript'], 'facts': [
            'Implemented REST API integration using Python, HTTPX and JSON for HTTP endpoints.',
            'Uses AI coding assistants and Codex for debugging, code analysis and workflow automation.',
            'Implemented client-side JavaScript using fetch for API requests.',
        ]}],
    })


def evaluate(text, profile):
    validator = AnalysisValidator(profile)
    validator.matcher = EvidenceMatcher(validator.catalog, as_of=date(2026, 10, 11))
    return validator.validate(candidate(), text)


@pytest.mark.parametrize('text', ['SQL', 'Working knowledge of SQL for investigation and validation.', 'SQL queries'])
def test_operational_tsql_proves_working_sql(contextual_profile, text):
    req = evaluate('Requirements\n' + text, contextual_profile).requirements[0]
    assert req.status == 'strong'
    assert any('T-SQL' in fact for fact in req.evidence)
    assert any(s['owner'].endswith('Example Operations') and s['type'] == 'experience' for s in req.evidence_sources)


@pytest.mark.parametrize('text', ['SQL DBA', 'SQL performance tuning', 'Advanced SQL cluster administration'])
def test_working_sql_does_not_prove_advanced_database_duties(contextual_profile, text):
    req = evaluate('Requirements\n' + text, contextual_profile).requirements[0]
    assert req.status == 'partial'


def test_httpx_json_integration_is_directional(contextual_profile):
    result = evaluate('Requirements\nREST API integration\nHands-on experience debugging REST APIs (requests, responses, auth, payloads, status codes).', contextual_profile)
    integration, debugging = result.requirements
    assert integration.status == 'strong'
    assert debugging.status == 'partial'
    assert integration.scoring_key != debugging.scoring_key
    assert integration.evidence_sources[0]['type'] == 'project'


def test_python_alone_does_not_prove_api_integration(profile):
    req = evaluate('Requirements\nREST API integration', profile).requirements[0]
    assert req.status == 'missing'


def test_sql_equivalence_does_not_reverse_product_specificity(profile):
    profile.skills = {'databases': ['SQL']}
    req = evaluate('Requirements\nT-SQL', profile).requirements[0]
    assert req.status == 'partial'
    assert 'specific' in req.reason


def test_generic_support_does_not_establish_saas_or_saas_tenure(contextual_profile):
    result = evaluate('Requirements\nSaaS technical support\n2 years of SaaS technical support experience', contextual_profile)
    assert all(r.status != 'strong' for r in result.requirements)
    assert result.requirements[1].observed_years == 0


@pytest.mark.parametrize('text', ['JavaScript or TypeScript preferred.', 'JavaScript or TypeScript (nice to have)'])
def test_preference_suffix_and_alternatives_are_preserved(contextual_profile, text):
    req = evaluate('Requirements\n' + text, contextual_profile).requirements[0]
    assert req.priority == 'preferred' and req.operator == 'any'
    assert req.status == 'strong' and req.source_quote == text


def test_matching_preferences_alone_does_not_establish_full_qualification(contextual_profile):
    result = evaluate('Preferred qualifications\nJavaScript', contextual_profile)
    assert result.requirements[0].status == 'strong'
    assert result.match_level == 'LIMITED' and result.recommendation == 'REVIEW'
    assert result.scoring_counts['mandatory_groups'] == 0


def test_or_proficiency_applies_to_each_branch(contextual_profile):
    req = evaluate('Requirements\nAdvanced knowledge of JavaScript or TypeScript', contextual_profile).requirements[0]
    assert req.operator == 'any' and req.status == 'partial'
    assert all('Advanced knowledge' in alternative for alternative in req.alternatives)


def test_programming_or_needs_only_one_alternative(contextual_profile):
    result = evaluate('Requirements\nJavaScript OR TypeScript', contextual_profile)
    req = result.requirements[0]
    assert req.status == 'strong' and req.operator == 'any'
    assert req.alternatives == ['JavaScript', 'TypeScript']
    assert len(result.requirements) == 1


def test_programming_and_needs_both_conditions(contextual_profile):
    result = evaluate('Requirements\nJavaScript AND TypeScript', contextual_profile)
    js, ts = result.requirements
    assert js.status == 'strong' and ts.status == 'missing'
    assert js.group_id == ts.group_id
    assert result.scoring_counts['confirmed'] == 0
    assert result.match_level == 'LOW'


def test_read_code_with_preferred_languages(contextual_profile):
    text = 'Ability to read and understand code (JavaScript / TypeScript preferred; other languages welcome).'
    result = evaluate('Requirements\n' + text, contextual_profile)
    ability, languages = result.requirements
    assert ability.priority == 'mandatory' and ability.status == 'strong'
    assert languages.priority == 'preferred' and languages.operator == 'any'
    assert languages.status == 'strong'
    assert ability.accepted_alternatives == ['other programming languages']
    assert ability.source_quote == languages.source_quote == text
    assert all(r.name != 'TypeScript' for r in result.requirements)


@pytest.mark.parametrize('level,expected', [('B1', 'strong'), ('B2', 'strong'), ('B2+', 'partial'), ('C1', 'partial'), ('C2', 'partial')])
def test_language_level_respects_b2_plus(contextual_profile, level, expected):
    req = evaluate('Requirements\nEnglish ' + level, contextual_profile).requirements[0]
    assert req.status == expected
    assert req.required_level == level
    if level == 'B2+':
        assert 'B2+' in req.reason and 'documented B2' in req.reason


def test_native_polish_meets_polish_requirement(contextual_profile):
    req = evaluate('Requirements\nPolish C1', contextual_profile).requirements[0]
    assert req.status == 'strong'


def test_reversed_native_language_wording_is_supported(contextual_profile):
    contextual_profile.skills['languages'] = ['Native Polish']
    req = evaluate('Requirements\nPolish C1', contextual_profile).requirements[0]
    assert req.status == 'strong'


def test_app_english_text_is_not_language_evidence(profile):
    from app.models.candidate import Project
    profile.projects.append(Project(name='English UI', facts=['Implemented an English text label for the user interface.']))
    req = evaluate('Requirements\nEnglish', profile).requirements[0]
    assert req.status == 'missing'


def test_wrong_skill_evidence_is_not_reused_as_sql_practice(tmp_path, profile):
    from app.models.skills import SkillEvidence, SkillsDocument, VerifiedSkill
    from app.services.skills_bank import SkillsBank
    wrong_id = next(e.source_id for e in FactCatalog(profile).prompt_entries if e.kind == 'experience')
    skill = VerifiedSkill(id='skill_sql_queries', name='SQL troubleshooting / operational queries', category='Databases',
                          level='hands_on', verified=True, allowed_in_cv=True, evidence=[SkillEvidence(
                              source_type='employment', source_id=wrong_id, description='Python automation')])
    path = tmp_path / 'skills.json'
    path.write_text(SkillsDocument(skills=[skill]).model_dump_json())
    req = AnalysisValidator(profile, SkillsBank(path, profile)).validate(candidate(), 'Requirements\nWorking knowledge of SQL for investigation and validation.').requirements[0]
    assert req.status == 'missing'
    assert wrong_id not in req.source_fact_ids


def test_portal_language_levels_are_retained():
    result = NoFluffExtractor().extract(Path('tests/fixtures/nofluff_onerail_support.html').read_text())
    assert 'Polish A2' in result.job_description
    assert 'English B2' in result.job_description
    assert 'B2+' in result.job_description


def test_bilingual_level_checks_both(contextual_profile):
    req = evaluate('Requirements\nAdvanced proficiency in English & Polish, both written and spoken (B2+).', contextual_profile).requirements[0]
    assert req.status == 'partial'
    assert 'English' in req.reason and 'Polish' in req.reason


def test_unknown_technology_is_not_a_confirmed_gap(contextual_profile):
    result = evaluate('Requirements\nSaaS\nTypeScript', contextual_profile)
    assert all(r.status == 'missing' for r in result.requirements)
    assert result.requirement_counts['confirmed_absence'] == 0
    assert result.profile_clarifications
    assert result.recommendation != 'SKIP'


def test_explicit_absence_stays_distinct(contextual_profile):
    contextual_profile.summary_facts.append('No experience with TypeScript.')
    req = evaluate('Requirements\nTypeScript', contextual_profile).requirements[0]
    assert req.status == 'absent'
    assert req.evidence_sources


def test_equivalent_sql_rows_share_weight_but_preserve_quotes(contextual_profile):
    result = evaluate('Requirements\nSQL\nSQL queries\nWorking knowledge of SQL for investigation and validation.\nSaaS', contextual_profile)
    assert len(result.requirements) == 4
    assert result.scoring_counts['mandatory_groups'] == 2
    assert result.scoring_counts['duplicate_rows'] == 2
    assert result.scoring_counts['confirmed'] == 1
    assert result.requirement_counts['confirmed'] == 3
    assert all(r.source_quote == r.name for r in result.requirements)


def test_ticket_work_does_not_prove_ownership(contextual_profile):
    req = evaluate('Requirements\nExperience owning support tickets from intake through resolution.', contextual_profile).requirements[0]
    assert req.status == 'partial'
    assert 'closure' in req.reason


def test_engineering_escalation_does_not_prove_product_collaboration(contextual_profile):
    req = evaluate('Requirements\nComfortable collaborating with Engineering and Product teams during escalations.', contextual_profile).requirements[0]
    assert req.status == 'partial'
    assert 'Product' in req.reason


def test_titles_alone_do_not_establish_support_experience(contextual_profile):
    contextual_profile.experience[0].facts = []
    contextual_profile.experience = [contextual_profile.experience[0]]
    req = evaluate('Requirements\n2 years of technical support experience', contextual_profile).requirements[0]
    assert req.status == 'missing' and req.observed_years == 0


def test_dated_relevant_employment_counts_disjoint_periods(contextual_profile):
    req = evaluate('Requirements\n2–4 years of experience in technical support, product support, software development, or a customer-facing technical role.', contextual_profile).requirements[0]
    assert req.status == 'strong'
    assert req.required_years == 2
    assert 3.3 < req.observed_years < 3.5


def test_employment_periods_do_not_double_count_overlap(contextual_profile):
    contextual_profile.experience = [contextual_profile.experience[0], contextual_profile.experience[0].model_copy(deep=True)]
    req = evaluate('Requirements\n2 years of technical support experience', contextual_profile).requirements[0]
    assert req.status == 'partial'
    assert 1.2 < req.observed_years < 1.3


def test_year_only_dates_require_verification(contextual_profile):
    contextual_profile.experience[0].start = '2023'
    contextual_profile.experience = [contextual_profile.experience[0]]
    req = evaluate('Requirements\n2 years of technical support experience', contextual_profile).requirements[0]
    assert req.status == 'partial' and req.observed_years == 0


def test_ai_coding_tools_are_not_ai_engineer_experience(contextual_profile):
    req = evaluate('Requirements\nComfort using modern AI-assisted tools for code understanding, debugging and documentation.', contextual_profile).requirements[0]
    assert req.status == 'strong'
    assert 'AI Engineer' in req.reason
    engineer = evaluate('Requirements\n4 years of experience as an AI Engineer', contextual_profile).requirements[0]
    assert engineer.status != 'strong'


def test_slash_ambiguity_is_kept_for_review(contextual_profile):
    req = evaluate('Requirements\nPython / JavaScript', contextual_profile).requirements[0]
    assert req.interpretation_uncertain
    assert req.operator == 'ambiguous' and req.source_quote == 'Python / JavaScript'


def test_portal_tags_are_not_extra_mandatory_conditions(contextual_profile):
    result = evaluate('MUST HAVE\nSaaS\nJavaScript\nTypeScript\n\nREQUIREMENTS\nAbility to read and understand code (JavaScript / TypeScript preferred; other languages welcome).', contextual_profile)
    assert result.is_reliable
    assert len(result.requirements) == 2
    assert result.requirement_counts['mandatory'] == 1
    assert len(result.role_competencies) == 3
    assert all(r.priority == 'unspecified' for r in result.role_competencies)


def test_onerail_public_fixture_with_synthetic_evidence(contextual_profile):
    text = NoFluffExtractor().extract(Path('tests/fixtures/nofluff_onerail_support.html').read_text()).job_description
    result = evaluate(text, contextual_profile)
    by_name = {r.name: r for r in result.requirements}
    assert result.is_reliable
    assert result.requirement_counts['mandatory'] == 10
    assert result.requirement_counts['preferred'] == 1
    assert by_name['Working knowledge of SQL for investigation and validation.'].status == 'strong'
    assert by_name['JavaScript OR TypeScript'].status == 'strong'
    assert by_name['Experience owning support tickets from intake through resolution.'].status == 'partial'
    assert not any(r.name == 'TypeScript' and r.priority == 'mandatory' for r in result.requirements)
    counts = result.requirement_counts
    assert sum(counts[k] for k in ('confirmed', 'partial', 'not_confirmed', 'confirmed_absence')) == len(result.requirements)
    assert result.match_level == 'MEDIUM'


def test_older_saved_models_remain_loadable():
    analysis = candidate().model_dump()
    analysis.pop('scoring_counts')
    analysis.pop('profile_clarifications')
    assert JobAnalysis.model_validate(analysis).scoring_counts == {}


def test_manual_project_attestation_provides_real_source(tmp_path, profile):
    from app.models.skills import SkillEvidence, SkillsDocument, VerifiedSkill
    from app.services.skills_bank import SkillsBank
    skill = VerifiedSkill(id='skill_rest_api', name='REST API integration', category='Web / APIs', level='hands_on',
                          verified=True, allowed_in_cv=True, evidence=[SkillEvidence(source_type='manual_verified',
                          source_id='manual:synthetic:httpx', description='Implemented REST API integration using HTTPX and JSON in a project.')])
    path = tmp_path / 'skills.json'
    path.write_text(SkillsDocument(skills=[skill]).model_dump_json())
    result = AnalysisValidator(profile, SkillsBank(path, profile)).validate(candidate(), 'Requirements\nREST API integration')
    req = result.requirements[0]
    assert req.status == 'strong'
    assert req.source_fact_ids == ['manual:synthetic:httpx']
    assert skill.evidence[0].description in req.evidence_sources[0]['fact']


def test_log_analysis_evidence_can_come_from_employment(contextual_profile):
    matcher = EvidenceMatcher(FactCatalog(contextual_profile))
    req = matcher.match('Technical troubleshooting')
    assert req.status == 'strong'
    assert any('logs' in e.text for e in req.entries)
