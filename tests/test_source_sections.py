from app.models.job import JobAnalysis
from app.services.analysis_validator import AnalysisValidator
from app.services.job_sections import extract_sections


def empty_analysis():
    return JobAnalysis(company='Example',role='Support',strong_matches=[],partial_matches=[],missing_requirements=[],
                       recommendation='SKIP',match_level='LOW')


def evaluate(text,profile):
    return AnalysisValidator(profile).validate(empty_analysis(),text)


def test_sections_without_colons_and_preferences(profile):
    text='Company Overview\nExample is a global leader in software.\nResponsibilities:\nWrite knowledge base articles.\nBasic Requirements\nEssential Skills & Requirements\nPython\nPreference will be given to candidates with the following skills and experience:\nIT certifications such as CCNA, CCNP, or Microsoft credentials.\nTools: Experience using CRM systems and working in environments using the KCS methodology.\nBenefits\nPaid leave.'
    result=evaluate(text,profile)
    assert len(result.requirements)==4
    assert not any('global leader' in r.name for r in result.requirements)
    assert len(result.organization_context)==1 and len(result.responsibilities)==1
    assert result.requirement_counts['mandatory']==1 and result.requirement_counts['preferred']==3
    assert all(r.source_quote in text and r.classification_basis for r in result.requirements)
    assert result.is_reliable


def test_windows_mac_or_linux_is_one_alternative(profile):
    profile.skills={'systems':['Linux']}
    result=evaluate('Requirements\nWindows, Mac or Linux',profile)
    assert len(result.requirements)==1 and result.requirements[0].status=='strong'


def test_crm_and_kcs_require_independent_evidence(profile):
    profile.experience[0].facts.append('Manages customer support cases using Salesforce CRM.')
    result=evaluate('Preferred qualifications\nTools: Experience using CRM systems and working in environments using the KCS methodology.',profile)
    assert len(result.requirements)==2
    assert result.requirements[0].status=='strong'
    assert result.requirements[1].status=='missing'
    assert result.requirements[0].group_id==result.requirements[1].group_id


def test_b2_and_daily_english_do_not_prove_fluency(profile):
    profile.skills['languages']=['English B2, used daily']
    result=evaluate('Requirements\nFluency in English (written and oral) is essential.',profile)
    assert result.requirements[0].status=='partial'
    assert result.recommendation!='APPLY'


def test_incomplete_source_coverage_never_produces_skip(profile):
    text='Requirements\nPython\nMust have experience and'
    result=evaluate(text,profile)
    assert not result.is_reliable and result.recommendation=='RETRY'
    assert result.match_level=='UNRELIABLE'
    assert 'Incomplete analysis — review required' in result.reasoning_summary


def test_model_omissions_recovered_from_source_sections(profile):
    result=evaluate('Requirements\nPython\nDocker\nPreferred qualifications\nAWS',profile)
    assert len(result.requirements)==3
    counts=result.requirement_counts
    assert counts['confirmed']+counts['partial']+counts['not_confirmed']+counts['confirmed_absence']==len(result.requirements)
    assert counts['mandatory']+counts['preferred']==len(result.requirements)
    assert not result.missing_requirements or result.recommendation!='SKIP'


def test_confirmed_absence_requires_explicit_evidence(profile):
    profile.summary_facts.append('No experience with Kubernetes.')
    result=evaluate('Requirements\nKubernetes\nAWS',profile)
    assert result.requirements[0].status=='absent'
    assert result.requirements[1].status=='missing'
    assert result.recommendation=='SKIP'


def test_responsibilities_not_required_prior_experience(profile):
    result=evaluate('Responsibilities\nProvide after-hours support.\nRequirements\nPython',profile)
    assert len(result.requirements)==1
    assert len(result.responsibilities)==1


def test_section_classification_not_specific_to_one_employer():
    units,_=extract_sections('About us\nWe build tools.\nMinimum qualifications\nPython\nDesirable skills\nDocker\nDuties\nMaintain scripts.')
    assert [u.category for u in units]==['organization','mandatory','preferred','responsibility']


def test_certifications_are_examples_not_cumulative_conditions(profile):
    from app.models.candidate import Certification
    profile.certifications=[Certification(name='CompTIA A+')]
    result=evaluate('Preferred qualifications\nIT certifications such as CompTIA A+, Network+, or CCNA.',profile)
    assert result.requirements[0].priority=='preferred'
    assert result.requirements[0].status=='strong'


def test_preferably_clause_is_not_a_mandatory_qualifier(profile):
    profile.skills={'systems':['Linux']}
    result=evaluate('Requirements\nLinux, preferably expert level.',profile)
    assert result.requirements[0].status=='strong'
    assert 'optional' in result.requirements[0].classification_basis
    assert result.requirements[0].source_quote=='Linux, preferably expert level.'


def test_uncovered_requirement_before_a_recognized_section(profile):
    result=evaluate('Must have experience with Kubernetes.\nRequirements\nPython',profile)
    assert not result.is_reliable
    assert result.recommendation=='RETRY'
def test_optional_sections_and_benefit_intro_do_not_become_requirements():
    from app.services.job_sections import extract_sections

    text = """Must have:
Linux administration
Could have:
PostgreSQL experience
\u200bSoft skills:
Communication skills
Experience:
1+ years in a related role
In return for your expertise, we’ll support you with development.
Also, to reward your hard work you’ll get:
Life insurance
Parking space
Development opportunities"""
    units, sections = extract_sections(text)
    assert next(u for u in units if u.name == 'PostgreSQL experience').category == 'preferred'
    assert next(u for u in units if u.name == '1+ years in a related role').category == 'unknown'
    assert not any(u.name.endswith(':') for u in units)
    assert all(u.category == 'benefits' for u in units if u.name in {'Life insurance', 'Parking space', 'Development opportunities'})
    assert 'Soft skills' in sections



def test_model_cannot_score_section_titles_or_benefits(profile):
    from app.models.job import JobRequirement

    text = 'Requirements\nPython\nCould have:\nDocker\nExperience:\n1+ years in a related role\nAlso, to reward your hard work you’ll get:\nLife insurance'
    candidate = empty_analysis()
    candidate.requirements = [
        JobRequirement(name=name, source_quote=name, priority='mandatory', status='missing', reason='No evidence')
        for name in ['Python', 'Docker', 'Experience:', 'Life insurance']
    ]
    result = AnalysisValidator(profile).validate(candidate, text, semantic=True)
    assert not any(r.name in {'Experience:', 'Life insurance'} for r in result.requirements)
    assert next(r for r in result.requirements if r.name == 'Docker').priority == 'preferred'
    assert any(c['source_quote'] == 'Life insurance' for c in result.source_context)
