from app.models.candidate import CandidateProfile, Project
from app.models.job import JobRequest
from app.services.analysis_validator import AnalysisValidator
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment


def profile():
    return CandidateProfile(personal={'name': 'Synthetic Candidate'},
                            projects=[Project(name='Synthetic application', facts=['Used Python for an automation script.'])])


def analysis_from(job, classify):
    inv = AnalysisInventory.build(job, profile())
    evidence = list(inv.evidence)
    rows = [classify(pid, passage['text'], evidence) for pid, passage in inv.passages.items()]
    return inv.expand(rows).to_analysis(job)


def test_work_arrangement_context_and_derived_personal_clarification_are_stable():
    quote = 'Hybrid way of working (not less than 2 times per week in the office)'
    job = JobRequest(company='Synthetic', role='Support', job_description='Requirements\nKnowledge of Python\n' + quote)
    def classify(pid, text, ids):
        return (CompactAssessment(p=pid, k='requirement', n='Python knowledge', s='strong', f=ids, why='Documented use.')
                if text == 'Knowledge of Python' else CompactAssessment(p=pid, k='context'))
    candidate = analysis_from(job, classify)
    text = job.role + '\n' + job.job_description
    validator = AnalysisValidator(profile())
    for _ in range(3):
        candidate = validator.validate(candidate, text, semantic=True)
        assert candidate.is_reliable, candidate.completeness_issues
        arrangements = [r for r in candidate.requirements if r.source_quote == quote]
        assert arrangements and all(r.status == 'missing' and not r.source_fact_ids for r in arrangements)
        assert 'personal confirmation' in arrangements[0].reason


def test_portal_tags_do_not_duplicate_mandatory_qualifications_on_revalidation():
    job = JobRequest(company='Synthetic', role='Support', job_description=(
        'Requirements\nKnowledge of Python\nKnowledge of Azure\nTECH STACK\nOffice 365\njunior\nAzure\njunior'))
    def classify(pid, text, ids):
        if text == 'Knowledge of Azure':
            return CompactAssessment(p=pid, k='requirement', n='Azure knowledge', priority='mandatory',
                                     s='missing', why='This explicit qualification is not documented.')
        if text in {'Knowledge of Python', 'Office 365', 'Azure'}:
            return CompactAssessment(p=pid, k='requirement', n=text, priority='mandatory',
                                     s='strong', f=ids, why='Overbroad model interpretation.')
        return CompactAssessment(p=pid, k='context')
    candidate = analysis_from(job, classify)
    text = job.role + '\n' + job.job_description
    validator = AnalysisValidator(profile())
    for _ in range(3):
        candidate = validator.validate(candidate, text, semantic=True)
        assert candidate.is_reliable, candidate.completeness_issues
        assert {r.source_quote for r in candidate.requirements} == {'Knowledge of Python', 'Knowledge of Azure'}
        assert next(r for r in candidate.requirements if r.source_quote == 'Knowledge of Azure').status == 'missing'
        tags = {r.source_quote: r for r in candidate.role_competencies}
        assert {'Office 365', 'Azure'} <= tags.keys()
        assert all(tags[tag].priority == 'unspecified' for tag in ['Office 365', 'Azure'])
        assert all(tags[tag].status != 'strong' for tag in ['Office 365', 'Azure'])
