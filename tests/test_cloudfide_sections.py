"""Regression for section leakage in the reported Cloudfide match report."""
from itertools import permutations

import pytest

from app.models.job import JobRequirement
from app.services.job_sections import extract_sections
from tests.test_match_report_integrity import analyze

SOURCE = '''Your Responsibilities
Build data pipelines.
What We’re Looking For
At least 1.5 years of commercial experience in data engineering.
Hands-on experience with Databricks.
Experience working with Azure.
Experience building enterprise-level data pipelines.
Fluent English communication, able to collaborate effectively across international teams.
Nice to Have
Experience with agentic AI, AI agents, or LLM-based solutions.
Knowledge of Apache Spark / PySpark optimization.
Experience with CI/CD pipelines (Azure DevOps or GitHub Actions).
Here’s why you’ll love Cloudfide
Benefits:
MyBenefit platform / Multisport
Professional Growth:
Annual 2,000 PLN development budget
Access to e-learning platforms
Mentoring from experienced engineers and a clear path to grow your skills
Work Environment:
Remote-first, work from anywhere in the world (workation)
Culture & Integration:
Team integration budgets
Equal Opportunities
CLOUDFIDE is an Equal Opportunity Employer. We celebrate diversity and are committed to creating an inclusive environment for all employees.'''


def classified_analysis(text, requirements, duties=()):
    from app.services.analysis_validator import AnalysisValidator
    from tests.test_evidence_matching import candidate
    from tests.test_match_report_integrity import support_profile

    draft = candidate()
    draft.requirements = [JobRequirement(name=quote, source_quote=quote, priority=priority,
        reason='Not documented in supplied profile.', operator='any' if '/' in quote else 'single')
        for quote, priority in requirements]
    draft.responsibilities = [{'source_quote': q} for q in duties]
    assessed = {q for q, _ in requirements} | set(duties)
    draft.source_context = [{'source_quote': line} for line in text.splitlines() if line and line not in assessed]
    return AnalysisValidator(support_profile()).validate(draft, text, semantic=True)


@pytest.mark.parametrize('formatting', ['plain', 'markdown', 'ascii'])
def test_cloudfide_model_classification_overrides_inherited_section_hints(formatting):
    text = SOURCE
    lines = text.splitlines()
    qualifications = [(line, 'mandatory') for line in lines[3:8]] + [(line, 'preferred') for line in lines[9:12]]
    if formatting == 'markdown':
        text = text.replace('What We’re Looking For', '## What We’re Looking For').replace('Professional Growth:', '**Professional Growth:**')
    elif formatting == 'ascii':
        text = text.replace('’', "'")
    result = classified_analysis(text, qualifications, ['Build data pipelines.'])
    assert result.is_reliable, result.classification_issues + result.completeness_issues
    assert result.requirement_counts['mandatory'] == 5
    assert len(result.requirements) == 8
    assert len(result.responsibilities) == 1
    assert not any('love Cloudfide' in r.name for r in result.requirements)
    assert not result.classification_issues
    assert not next(r for r in result.requirements if 'optimization' in r.name).interpretation_uncertain


@pytest.mark.parametrize('order', list(permutations(range(4))))
@pytest.mark.parametrize('formatting', ['plain', 'markdown', 'bullets'])
def test_arbitrary_headings_and_section_order_do_not_override_semantics(order, formatting):
    # These invented labels deliberately have no entry in the parser dictionary.
    blocks = [
        ('Your next chapter', 'Experience with PhotonStack.'),
        ('An extra edge', 'Knowledge of NebulaDB.'),
        ('A week with us', 'Maintain data pipelines.'),
        ('Life around the code', 'Annual learning allowance.'),
    ]
    def heading(s):
        return f'## {s}' if formatting == 'markdown' else s

    def body(s):
        return f'• {s}' if formatting == 'bullets' else s
    text = '\n'.join('\n'.join((heading(blocks[i][0]), body(blocks[i][1]))) for i in order)
    reqs = [(body(blocks[0][1]), 'mandatory'), (body(blocks[1][1]), 'preferred')]
    result = classified_analysis(text, reqs, [body(blocks[2][1])])
    assert result.is_reliable, result.completeness_issues + result.classification_issues
    assert result.requirement_counts['mandatory'] == 1
    assert len(result.requirements) == 2
    assert len(result.responsibilities) == 1


def test_model_context_cannot_hide_omitted_or_invented_passages():
    from app.services.analysis_validator import AnalysisValidator
    from tests.test_evidence_matching import candidate
    from tests.test_match_report_integrity import support_profile

    draft = candidate()
    draft.source_context = [{'source_quote': 'A unique heading'}, {'source_quote': 'Invented benefit'}]
    result = AnalysisValidator(support_profile()).validate(draft,
        'A unique heading\nRequired expertise in PhotonStack.', semantic=True)
    assert not result.is_reliable
    assert any('no verifiable' in issue for issue in result.completeness_issues)
    assert any('Required expertise' in issue for issue in result.completeness_issues)


def test_unrelated_slash_still_requires_review():
    units, _ = extract_sections('Requirements\nKnowledge of Kafka / RabbitMQ')
    assert units[0].uncertain


def test_report_shows_validation_issue_once_and_collapses_fallback_details():
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader

    from app.models.job import JobRequest

    result = analyze('Requirements\nExperience in IT support\n## Unknown scope\nUnclassified text')
    assert not result.is_reliable
    issue = result.classification_issues[0]
    request = type('Request', (), {'query_params': {}, 'state': type('State', (), {'authenticated': False})()})()
    template = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / 'templates')).get_template('analysis.html')
    html = template.render(analysis=result, job=JobRequest(company='Synthetic', role='IT', job_description=SOURCE),
                           request=request, fallback_used=True, fallback_reason='Primary failed: diagnostic detail',
                           provider_used='gemini', token_usage={})
    assert html.count(issue) == 1
    assert '<details><summary>Technical details</summary>' in html
    assert 'Primary failed: diagnostic detail' in html


def test_complete_context_map_cannot_discard_explicit_tenure():
    from app.services.analysis_validator import AnalysisValidator
    from tests.test_evidence_matching import candidate
    from tests.test_match_report_integrity import support_profile

    text = 'Unusual heading\nAt least 1.5 years of commercial experience in data engineering.'
    draft = candidate()
    draft.source_context = [{'source_quote': line} for line in text.splitlines()]
    result = AnalysisValidator(support_profile()).validate(draft, text, semantic=True)
    assert not result.is_reliable
    assert text.splitlines()[1] in result.unassessed_source_passages


def test_model_cannot_classify_same_passage_as_benefit_and_qualification():
    from app.services.analysis_validator import AnalysisValidator
    from tests.test_evidence_matching import candidate
    from tests.test_match_report_integrity import support_profile

    text = 'Experience with PhotonStack.'
    draft = candidate()
    draft.source_context = [{'source_quote': text}]
    draft.requirements = [JobRequirement(name=text, source_quote=text, reason='No evidence.')]
    result = AnalysisValidator(support_profile()).validate(draft, text, semantic=True)
    assert not result.is_reliable
    assert any('Conflicting' in issue for issue in result.completeness_issues)


def test_batched_model_sees_original_offer_beyond_inherited_hints():
    from app.models.job import JobRequest
    from app.services.ollama_analysis import AnalysisInventory
    from tests.test_match_report_integrity import support_profile

    inventory = AnalysisInventory.build(JobRequest(company='Synthetic', role='IT', job_description=SOURCE), support_profile())
    pid = next(pid for pid, p in inventory.passages.items() if p['text'].startswith('At least'))
    assert inventory.payload([pid])['job_source'] == SOURCE
    assert inventory.passages[pid]['hints'] == ['responsibility']
    schema = inventory.keyed_schema([pid])
    definition = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    assert schema['$defs'][definition]['properties']['k']['enum'] == ['requirement']


def test_revalidation_allows_competencies_derived_from_responsibilities():
    from app.services.analysis_validator import AnalysisValidator
    from tests.test_match_report_integrity import support_profile

    text = 'Different role text\nDesign pipelines using Azure.\nExperience with PhotonStack.\nAnnual learning allowance.'
    first = classified_analysis(text, [('Experience with PhotonStack.', 'mandatory')], ['Design pipelines using Azure.'])
    assert first.is_reliable
    assert first.role_competencies
    second = AnalysisValidator(support_profile()).validate(first, text)
    third = AnalysisValidator(support_profile()).validate(second, text)
    assert second.is_reliable, second.completeness_issues
    assert third.is_reliable, third.completeness_issues
    assert first.requirement_counts == second.requirement_counts == third.requirement_counts
    assert len(first.responsibilities) == len(second.responsibilities) == len(third.responsibilities)
