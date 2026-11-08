"""A capability section label is provenance, never evidence of competence."""
import pytest

from app.models.candidate import CandidateProfile
from app.models.job import JobRequest
from app.services.analysis_validator import AnalysisValidator
from app.services.job_sections import extract_sections
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment
from app.services.source_dispositions import source_heading


@pytest.mark.parametrize('heading', ['Technical Capabilities', 'technical capabilities', 'TECHNICAL CAPABILITIES'])
@pytest.mark.parametrize('colon', ['', ':'])
def test_heading_preserves_section_boundaries_and_exact_quotes(heading, colon):
    source = (f'Tech Stack\nPython\n{heading}{colon}\nKnowledge of Linux\nPreferred\n'
              'Knowledge of Rust\nDuties\nMaintain integrations.')
    units, headings = extract_sections(source)
    assert heading in headings
    assert {u.quote: u.category for u in units} == {
        'Python': 'competency', 'Knowledge of Linux': 'mandatory',
        'Knowledge of Rust': 'preferred', 'Maintain integrations.': 'responsibility',
    }


def test_sentence_containing_heading_words_is_not_a_heading():
    assert not source_heading('Technical capabilities include application troubleshooting.')


@pytest.mark.parametrize('normalize_rows', [False, True])
def test_false_heading_confirmation_is_removed_in_compact_and_independent_paths(normalize_rows):
    profile = CandidateProfile(personal={'name': 'Synthetic'})
    job = JobRequest(company='Synthetic', role='Engineer',
                     job_description='Technical Capabilities\nKnowledge of Linux')
    inv = AnalysisInventory.build(job, profile)
    rows = []
    for pid, p in inv.passages.items():
        if p['text'] == 'Technical Capabilities':
            rows.append(CompactAssessment(p=pid, k='requirement', n='Technical Capabilities',
                                          s='strong', priority='mandatory', why='Incorrect heading confirmation.'))
        elif p['text'] == 'Knowledge of Linux':
            rows.append(CompactAssessment(p=pid, k='requirement', n='Linux',
                                          s='missing', priority='mandatory', why='Not documented.'))
        else:
            rows.append(CompactAssessment(p=pid, k='context'))
    if normalize_rows:
        rows = inv.validate_rows(rows, list(inv.passages))
        heading_id = next(pid for pid, p in inv.passages.items() if p['text'] == 'Technical Capabilities')
        assert next(row for row in rows if row.p == heading_id).k == 'context'
    report = AnalysisValidator(profile).validate(
        inv.expand(rows).to_analysis(job), job.role + '\n' + job.job_description, semantic=True)
    assert report.is_reliable, report.completeness_issues
    assert len(report.requirements) == 1
    assert report.requirements[0].source_quote == 'Knowledge of Linux'
    assert report.requirements[0].status == 'missing'
