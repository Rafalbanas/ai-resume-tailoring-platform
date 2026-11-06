import pytest

from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume
from app.services.fact_validator import FactValidator


def checked(profile, skills, headline, *, analysis=False, occupation='Support Engineer'):
    profile.experience[0].title = occupation
    profile.skills = {'technical': skills}
    job = JobRequest(company='Synthetic', role='AI Engineer',
                     job_description='Requirements\nPython, REST API and technical troubleshooting.')
    report = JobAnalysis(company=job.company, role=job.role, strong_matches=[], partial_matches=[],
                         missing_requirements=[], recommendation='REVIEW', match_level='LOW') if analysis else None
    draft = TailoredResume(headline=headline, professional_summary='Draft requiring validation.',
                           core_skills=skills, experience=[])
    return FactValidator(profile, analysis=report).validate(draft, job)


@pytest.mark.parametrize('skills,expected', [
    (['Python', 'Linux'], 'Support Engineer | Python · Linux'),
    (['REST API integration', 'Technical troubleshooting'], 'Support Engineer | REST API integration'),
    (['An explicitly documented skill label that cannot fit the budget', 'Python'], 'Support Engineer | Python'),
    (['An explicitly documented skill label that cannot fit the budget'], 'Support Engineer'),
    (['Basic academic Python knowledge', 'Linux'], 'Support Engineer | Basic academic Python knowledge · Linux'),
])
def test_model_selected_suffixes_share_budget_and_remain_whole(profile, skills, expected):
    headline = 'Support Engineer | ' + ' · '.join(skills)
    result = checked(profile, skills, headline)
    assert result.resume.headline == expected
    assert len(result.resume.headline) <= 64


def test_advertised_title_fallback_uses_the_same_budget(profile):
    result = checked(profile, ['REST API integration', 'Technical troubleshooting'], 'AI Engineer', analysis=True)
    assert result.resume.headline == 'Support Engineer | REST API integration'
    assert 'AI Engineer' not in result.resume.headline


@pytest.mark.parametrize('occupation', ['Senior engineer for a highly specialised technical support organisation',
                                       'Verified occupation with documented responsibilities across several technical systems'])
def test_full_long_occupation_is_never_truncated(profile, occupation):
    result = checked(profile, ['Python'], occupation + ' | Python', occupation=occupation)
    assert len(occupation) > 64
    assert result.resume.headline == occupation


@pytest.mark.parametrize('headline', ['Support Engineer', 'Support Engineer | Unsupported skill',
                                    'AI Engineer | Python', 'AI Engineer'])
def test_new_suffix_is_not_invented_outside_existing_acceptance_paths(profile, headline):
    result = checked(profile, ['Python'], headline)
    assert result.resume.headline == 'Support Engineer'
    if headline not in {'Support Engineer', 'AI Engineer'}:
        assert any('headline' in warning for warning in result.warnings)
