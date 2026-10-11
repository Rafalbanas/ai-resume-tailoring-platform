"""Qualification absence is different from incomplete processing."""
from unittest.mock import patch

from jinja2 import Environment, FileSystemLoader

from app.models.job import JobAnalysis
from app.services.analysis_validator import AnalysisValidator
from app.services.job_extractors.justjoin import JustJoinExtractor


def candidate():
    return JobAnalysis(company='Example', role='Support', strong_matches=[], partial_matches=[],
                       missing_requirements=[], match_level='HIGH', recommendation='APPLY')


def test_qualified_offer_still_assesses_explicit_conditions(profile):
    result = AnalysisValidator(profile).validate(candidate(),
        'Responsibilities\nSupport users using Example Suite 400.\nQualifications\nPython\n'
        'Preferred qualifications\nExample Suite 400\nTECH STACK\nCustomer Support')
    assert result.is_reliable and len(result.requirements) == 2
    assert result.requirement_counts['mandatory'] == 1
    assert result.requirement_counts['preferred'] == 1
    assert result.requirements[1].status == 'missing'
    assert result.match_level != 'LIMITED'


def test_unqualified_offer_has_limited_role_assessment_and_product_gap(profile):
    profile.experience[0].facts = ['Supports partners and users with application issues.',
                                 'Troubleshoots applications and resolves incidents.']
    result = AnalysisValidator(profile).validate(candidate(),
        'Responsibilities\nSupport customers using Microsoft Dynamics 365 Customer Service.\n'
        'Configure processes within Dynamics 365.\nResolve application issues and incidents.\n'
        'TECH STACK\nCRM\nCustomer Support\nProblem Solving\nIT Support')
    assert result.is_reliable and not result.completeness_issues
    assert not result.requirements
    assert result.match_level == 'LIMITED' and result.recommendation == 'REVIEW'
    assert result.qualification_assessment == ('Qualification requirements are not specified. '
        'Assessment is based on listed role competencies and responsibilities.')
    products = [r for r in result.role_competencies if 'Dynamics' in r.name]
    assert len(products) == 1 and products[0].status == 'missing'
    assert products[0].priority == 'unspecified' and products[0].source_quote
    assert len(result.responsibilities) == 3
    assert profile.experience[0].facts[0] in result.responsibilities[2]['evidence']
    assert result.role_competency_counts['strong'] == 3


def test_role_skills_are_deduplicated_without_guessing_level(profile):
    profile.experience[0].facts = ['Supports partners and users with application issues.']
    result = AnalysisValidator(profile).validate(candidate(),
        'TECH STACK\nCustomer Support\nCustomer Service\nExample Suite 400')
    assert len(result.role_competencies) == 2
    assert result.role_competencies[0].status == 'strong'
    assert all(r.priority == 'unspecified' for r in result.role_competencies)
    assert 'unknown required level' in result.role_alignment_summary
    assert result.recommendation != 'APPLY'


def test_uncovered_requirement_is_processing_failure_even_with_role_skills(profile):
    result = AnalysisValidator(profile).validate(candidate(),
        'Must have Kubernetes experience.\nTECH STACK\nCustomer Support')
    assert not result.is_reliable
    assert result.match_level == 'UNRELIABLE' and result.recommendation == 'RETRY'


def test_dropped_source_requirement_is_incomplete(profile):
    # Simulate a processing loss after section extraction.
    with patch('app.services.grounded_requirements.source_lines', return_value=[]):
        result = AnalysisValidator(profile).validate(candidate(), 'Qualifications\nPython\nTECH STACK\nCRM')
    assert not result.is_reliable and 'Some source requirements were not assessed.' in result.completeness_issues


def test_justjoin_resumes_after_benefits_preserves_qualifications():
    html = '''<main><h1>Support Engineer</h1><div data-test-id="job-description">
      <h2>Responsibilities</h2><p>Use Example Suite 400 for customer support.</p>
      <h2>Benefits</h2><p>Medical insurance</p>
      <h2>Qualifications</h2><p>Two years of customer support experience.</p>
      <h2>Nice to have:</h2><p>Experience with Example Suite 400.</p>
      <h2>About us</h2><p>We build software.</p></div></main>'''
    result = JustJoinExtractor().extract(html)
    assert 'Qualifications' in result.job_description
    assert 'Two years' in result.job_description and 'Nice to have' in result.job_description
    assert 'Medical insurance' not in result.job_description


def test_company_text_after_preferences_is_not_a_qualification(profile):
    result = AnalysisValidator(profile).validate(candidate(),
        'Qualifications\nPython\nNice to have\nMicrosoft certifications.\n'
        'Develop yourself and the digital future!\nExample specialises in designing software.')
    assert len(result.requirements) == 2
    assert result.requirements[1].priority == 'preferred'
    assert len(result.organization_context) >= 1


def test_comparison_shows_separate_assessments(profile, resume_payload):
    analysis = AnalysisValidator(profile).validate(candidate(), 'TECH STACK\nCustomer Support\nExample Suite 400')
    result = dict(ok=True, model='mock', duration_ms=0, analysis=analysis.model_dump(), resume=resume_payload)
    html = Environment(loader=FileSystemLoader('templates')).get_template('compare.html').render(
        results={'ollama': result, 'gemini': result}, job={'role':'Support','company':'Example'},
        csrf_token='fixture', request={'state':{'authenticated':False}})
    assert 'Limited role assessment' in html and 'Qualification requirements are not specified.' in html
    assert 'Role alignment' in html and 'Example Suite 400' in html and 'Not confirmed in profile' in html
    assert 'Incomplete analysis — review required' not in html


def test_listed_role_level_is_preserved_but_not_claimed_as_met(profile):
    result = AnalysisValidator(profile).validate(candidate(), 'TECH STACK\nPython\nAdvanced')
    assert not result.requirements and result.is_reliable
    assert result.role_competencies[0].required_level == 'Advanced'
    assert result.match_level == 'LIMITED' and result.recommendation == 'REVIEW'


def test_justjoin_preserves_stack_level():
    html = '<div data-test-id="tech-stack"><h4>Python</h4><ul><li></li></ul><span>regular</span></div>'
    assert 'Python\nregular' in JustJoinExtractor().extract(html).job_description


def test_preferred_language_clause_not_mandatory(profile):
    result = AnalysisValidator(profile).validate(candidate(),
        'Qualifications\nVery good English and Polish skills. German language skills would be a plus.')
    assert [r.priority for r in result.requirements] == ['mandatory', 'preferred']


def test_duty_and_company_work_mode_do_not_create_qualification_blockers(profile):
    result = AnalysisValidator(profile).validate(candidate(),
        'Responsibilities\nProvide on-site support in a hybrid office.\nAbout us\nOur company offers on-site training.')
    assert not result.requirements and result.match_level == 'LIMITED'


def test_stack_c1_level_does_not_invent_mandatory_qualification(profile):
    result = AnalysisValidator(profile).validate(candidate(), 'TECH STACK\nEnglish\nC1')
    assert not result.requirements and result.role_competencies[0].required_level == 'C1'


def test_replay_is_labelled_not_a_new_generation(profile, resume_payload):
    analysis = AnalysisValidator(profile).validate(candidate(), 'TECH STACK\nCRM')
    result = dict(ok=True, model='saved', duration_ms=0, analysis=analysis.model_dump(),
                  resume=resume_payload, validation_replay=True)
    html = Environment(loader=FileSystemLoader('templates')).get_template('compare.html').render(
        results={'ollama':result, 'gemini':result}, job={'role':'Support','company':'Example'},
        csrf_token='fixture', request={'state':{'authenticated':False}})
    assert 'no new model generation' in html
