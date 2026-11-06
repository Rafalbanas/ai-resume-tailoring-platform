from app.models.candidate import CandidateProfile, Experience
from app.models.job import JobAnalysis, JobRequirement
from app.services.analysis_validator import AnalysisValidator


def test_revalidation_does_not_duplicate_language_and_tenure_explanations():
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'},
        summary_facts=['Uses English at B2 level in daily professional work.'],
        experience=[Experience(company='Example Ltd', title='Support Engineer', start='2020-01', end='2025-01',
                               facts=['Provided technical IT support to customers.'])])
    validator = AnalysisValidator(profile)
    ids = [e.source_id for e in validator.matcher.entries if e.kind == 'experience']
    quotes = ['Minimum 2 years of experience in IT support.', 'English B2.']
    analysis = JobAnalysis(company='Synthetic', role='Support', strong_matches=[], partial_matches=[], missing_requirements=[],
        recommendation='REVIEW', match_level='LOW', requirements=[
            JobRequirement(name='IT support experience', source_quote=quotes[0], source_fact_ids=ids, status='strong', reason='Source-backed support experience.'),
            JobRequirement(name='English B2', source_quote=quotes[1], status='partial', reason='Documented level.')])
    job_text = 'Requirements\n' + '\n'.join(quotes)
    first = validator.validate(analysis, job_text, semantic=True)
    second = validator.validate(first, job_text, semantic=True)
    third = validator.validate(second, job_text, semantic=True)
    assert [r.reason for r in first.requirements] == [r.reason for r in second.requirements] == [r.reason for r in third.requirements]
    assert all(r.reason.count('LLM-selected dated employment supports') <= 1 for r in third.requirements)
    assert all(r.reason.count('English: documented') <= 1 for r in third.requirements)
