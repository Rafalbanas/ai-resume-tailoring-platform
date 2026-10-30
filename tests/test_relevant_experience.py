from app.models.candidate import Experience
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume
from app.services.fact_catalog import FactCatalog
from app.services.fact_validator import FactValidator
from app.services.professional_summary import build_summary


def scenario(profile):
    profile.experience[0].facts += [
        'Collaborates with first-line support and escalates complex cases to engineering through the issue tracker.',
        'Supports router networking and VPN tunnel operations.',
    ]
    analysis = JobAnalysis(company='Example', role='Integration Engineer', strong_matches=[], partial_matches=[],
        missing_requirements=[], recommendation='REVIEW', match_level='LOW')
    job = JobRequest(company='Example', role='Integration Engineer',
        job_description='Responsibilities: Collaborate with development teams. Configure network devices and diagnose IP networks.')
    resume = TailoredResume(headline='Support Engineer', professional_summary=profile.summary_facts[0],
        summary_source_fact_ids=['summary:0'], core_skills=['Python'], experience=[dict(
            company=profile.experience[0].company,title=profile.experience[0].title,dates='',bullets=[dict(
                text=profile.experience[0].facts[0],source_fact_ids=['experience:0:fact:0'])])])
    return job, analysis, resume


def test_topic_relevant_employment_facts_are_retained_without_analysis_citations(profile):
    job, analysis, resume = scenario(profile)
    result = FactValidator(profile, analysis=analysis).validate(resume, job).resume
    texts = [b.text for e in result.experience for b in e.bullets]
    assert profile.experience[0].facts[1] in texts
    assert profile.experience[0].facts[2] in texts
    assert all(FactCatalog(profile).supports_paraphrase(b.text,b.source_fact_ids) for e in result.experience for b in e.bullets)


def test_global_network_configuration_does_not_become_an_employer_claim(profile):
    job, analysis, resume = scenario(profile)
    global_fact = 'Has basic hands-on experience configuring addressing, NAT and DHCP on routers.'
    profile.summary_facts.append(global_fact)
    result = FactValidator(profile, analysis=analysis).validate(resume, job).resume
    assert all(global_fact not in b.text for e in result.experience for b in e.bullets)


def test_manual_content_and_unrelated_jobs_do_not_gain_optional_bullets(profile):
    job, analysis, resume = scenario(profile)
    validator = FactValidator(profile, analysis=analysis)
    manual = validator.validate(resume, job, preserve_skills=True).resume
    assert len(manual.experience[0].bullets)==1
    validator.validate(resume, job)
    unrelated = job.model_copy(update={'role':'Python Developer','job_description':'Requirements: Python operational automation and scripting.'})
    assert len(validator.validate(resume, unrelated).resume.experience[0].bullets)==1


def test_source_fallback_introduces_actual_role_before_network_details(profile):
    profile.summary_facts.append('Has basic hands-on experience configuring IP addressing and static routes on routers.')
    catalog = FactCatalog(profile)
    network = next(e for e in catalog.prompt_entries if 'static routes' in e.text)
    text, ids = build_summary(catalog, 'Integration Engineer\nIP addressing and static routes.', priorities={network.source_id:3})
    assert text.startswith('Support Engineer at Example Ltd.')
    assert 'Has basic hands-on experience' in text
    assert 'Integration Engineer' not in text
    assert network.source_id in ids


def test_fallback_does_not_present_past_employment_as_current(profile):
    profile.experience = [Experience(company='Past Ltd',title='Support Technician',end='2024',facts=['Supported network devices.'])]
    text,_ = build_summary(FactCatalog(profile),'Integration Engineer\nNetwork devices.')
    assert text.startswith('Experience as Support Technician at Past Ltd.')
