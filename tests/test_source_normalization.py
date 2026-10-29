from pathlib import Path

import pytest

from app.models.candidate import CandidateProfile
from app.models.job import JobRequest, JobRequirement
from app.services.analysis_validator import AnalysisValidator
from app.services.job_extractors.pasted import clean_pasted_offer
from app.services.job_sections import clean_source_line, extract_sections
from app.services.ollama_analysis import AnalysisInventory
from tests.test_evidence_matching import candidate

SOURCE = (Path(__file__).parent / 'fixtures' / 'lancesoft_saas.md').read_text()


@pytest.mark.parametrize(('raw', 'expected'), [
    ('> - **Required Technical Skills:**', 'Required Technical Skills:'),
    ('\ufeff##\u00a0**Professional Requirements**', 'Professional Requirements'),
    ('1. __Required Technical Skills__', 'Required Technical Skills'),
    ('● `JSON data formats and API payloads.`', 'JSON data formats and API payloads.'),
    ('▪ REST\u2060 API\u200b integration and troubleshooting.', 'REST API integration and troubleshooting.'),
    ('- C++ / C# / CI/CD / TCP/IP / .NET / Node.js / foo_bar / __init__',
     'C++ / C# / CI/CD / TCP/IP / .NET / Node.js / foo_bar / __init__'),
    ('Minimum 2 years; native-level English; B2+; 12 months.',
     'Minimum 2 years; native-level English; B2+; 12 months.'),
    ('-5 degrees', '-5 degrees'),
    ('> 2 years of SaaS experience', '> 2 years of SaaS experience'),
    ('>2 years of SaaS experience', '>2 years of SaaS experience'),
    ('3.14 version', '3.14 version'),
])
def test_presentation_cleanup_preserves_content(raw, expected):
    assert clean_source_line(raw) == expected
    assert clean_source_line(expected) == expected


@pytest.mark.parametrize('clean_first', [False, True])
def test_full_offer_keeps_all_qualification_sections(clean_first):
    text = clean_pasted_offer(SOURCE).job_description if clean_first else SOURCE
    units, _ = extract_sections(text)
    assert len([u for u in units if u.category == 'mandatory']) == 15
    assert len([u for u in units if u.category == 'responsibility']) == 7
    assert any(u.category == 'employment' and 'Work independently' in u.quote for u in units)
    assert units[-1].category == 'keywords'
    result = AnalysisValidator(CandidateProfile(personal={'name': 'Synthetic'})).validate(candidate(), text)
    assert len([r for r in result.requirements if r.priority == 'mandatory']) == 15
    overview = [r for r in result.requirements if 'We are seeking' in r.source_quote]
    assert len(overview) == 1 and overview[0].priority == 'unspecified'
    assert any('Native-level English' in r.name for r in result.requirements)
    assert any('Minimum 2 years' in r.name for r in result.requirements)
    assert any(c['category'] == 'keywords' for c in result.source_context)
    assert not result.completeness_issues


def test_cleaner_reads_bold_metadata_and_removes_markers():
    result = clean_pasted_offer(SOURCE)
    assert result.company == 'LanceSoft (Recruitment for an external client)'
    assert '**' not in result.job_description
    assert '\n## ' not in result.job_description
    assert '\n- ' not in result.job_description
    assert 'REQUIREMENTS\nMinimum 2 years' in result.job_description
    assert 'ATS KEYWORDS\nTechnical Implementation Specialist,' in result.job_description


def test_inventory_and_parser_share_formatted_heading_boundaries():
    text = '> **Required Technical Skills:**\n● Webhooks and event-driven integrations.\n## **ATS Keywords**\nWebhooks, JSON'
    job = JobRequest(company='Synthetic', role='Specialist', job_description=text)
    inv = AnalysisInventory.build(job, CandidateProfile(personal={'name': 'Synthetic'}))
    passages = list(inv.passages.values())
    assert next(p for p in passages if 'event-driven' in p['text'])['hints'] == ['mandatory']
    keyword = next(p for p in passages if p['text'] == 'Webhooks, JSON')
    assert keyword['context_only']
    assert keyword['hints'] == ['keywords']


def test_keyword_list_cannot_be_used_as_model_qualification():
    draft = candidate()
    draft.requirements = [JobRequirement(name='Webhooks', source_quote='Webhooks, JSON',
                                         status='missing', reason='Not documented')]
    result = AnalysisValidator(CandidateProfile(personal={'name': 'Synthetic'})).validate(
        draft, 'Required Technical Skills\nWebhooks integration.\nATS Keywords\nWebhooks, JSON', semantic=True,
    )
    assert not any(r.source_quote == 'Webhooks, JSON' for r in result.requirements)


@pytest.mark.parametrize('body', [
    '- Experience with **REST APIs**.',
    '● Experience\u00a0with REST\u2060 APIs.',
])
def test_normalized_model_quote_recovers_original_source_line(body):
    from app.services.semantic_requirements import resolve_source_quotes

    text = '## **Required Technical Skills**\n' + body
    quote = 'Experience with REST APIs.'
    assert resolve_source_quotes(quote, text) == [body]
    draft = candidate()
    draft.requirements = [JobRequirement(name='REST APIs', source_quote=quote,
                                         status='missing', reason='Not documented')]
    result = AnalysisValidator(CandidateProfile(personal={'name': 'Synthetic'})).validate(draft, text, semantic=True)
    assert len(result.requirements) == 1
    assert result.requirements[0].source_quote == body
    assert not result.completeness_issues


def test_source_cleanup_does_not_accept_a_changed_required_level():
    from app.services.semantic_requirements import resolve_source_quotes

    assert resolve_source_quotes('English B2.', 'Required Technical Skills\n- **English C2.**') == []
