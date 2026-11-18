"""Fictional profile and offer-specific expectations for the quality benchmark."""

from app.models.candidate import CandidateProfile
from app.models.resume import ResumeBullet, ResumeExperience, TailoredResume
from app.services.fact_catalog import FactCatalog

SUPPORT = 'Delivered L1/L2 user support for about 170 users across five locations, troubleshooting VPN and workstation incidents.'
WINDOWS = 'Administered Active Directory and Group Policy for Windows Server and user workstations.'
WINDOWS_RESTORE = 'Tested Windows Server backup restoration and documented the recovery steps.'
PRODUCTION = 'Investigated production incidents by correlating application logs with read-only SQL queries.'
ESCALATION = 'Coordinated production incident escalations with engineering and documented recovery steps in runbooks.'
IMPLEMENTATION = 'Onboarded enterprise customers and configured SSO for SaaS integrations.'
API = 'Diagnosed failed REST API integrations by tracing OAuth token expiry and reviewing request logs with customers.'
DEVOPS = 'Maintained Linux deployment pipelines and investigated failed releases using GitLab CI job logs.'
MONITORING = 'Configured Prometheus alerts and monitored health checks for Linux services.'
AUTOMATION = 'Automated a recurring deployment check with Bash, cutting the observed run time from 25 minutes to 9 minutes.'


def profile():
    return CandidateProfile.model_validate({
        'personal': {'name': 'Alex Example', 'email': 'alex@example.com'},
        'summary_facts': ['Provides technical support for business customers.'],
        'skills': {'technical': ['Windows Server', 'Active Directory', 'Group Policy', 'Linux', 'GitLab CI',
            'Bash', 'Prometheus', 'SQL', 'REST API', 'OAuth', 'SSO', 'Docker', 'Basic Python']},
        'experience': [
            {'company': 'Example Services', 'title': 'IT Operations Analyst', 'start': '2022', 'end': 'Present',
             'facts': ['Handled daily operational tasks.', SUPPORT, WINDOWS, WINDOWS_RESTORE, PRODUCTION,
                       ESCALATION, IMPLEMENTATION, API, DEVOPS, MONITORING, AUTOMATION]},
            {'company': 'Example Systems', 'title': 'Support Technician', 'start': '2019', 'end': '2022',
             'facts': ['Provided general technical support.',
                       'Troubleshot VPN connectivity for remote users.',
                       'Documented workstation setup steps for the service desk.']},
        ],
        'education': [{'institution': 'Example University', 'qualification': 'BSc Computer Science', 'dates': '2019'}],
        'projects': [
            {'name': 'Personal container lab', 'description': 'Homelab for rehearsing container deployments.',
             'technologies': ['Docker', 'GitLab CI', 'Linux', 'Bash'],
             'facts': ['Built Docker images in a personal GitLab CI pipeline.',
                       'Tested container health checks and log collection on a Linux host.']},
            {'name': 'Personal calendar connector', 'description': 'Personal project linking a calendar and a task list.',
             'technologies': ['REST API', 'OAuth'],
             'facts': ['Configured OAuth token refresh for a calendar REST API in a personal project.',
                       'Documented configuration and verified webhook delivery in a test environment.']},
            {'name': 'Academic graph project', 'description': 'Academic coursework comparing graph traversal algorithms.',
             'technologies': [], 'facts': ['Compared traversal methods on synthetic graphs during coursework.']},
        ],
    })


def sparse_draft(candidate):
    catalog = FactCatalog(candidate)
    experience = []
    for index, owner in enumerate(candidate.experience):
        entry = catalog.get(f'experience:{index}:fact:0')
        experience.append(ResumeExperience(company=owner.company, title=owner.title, dates='',
            bullets=[ResumeBullet(text=entry.text, source_fact_ids=[entry.source_id])]))
    return TailoredResume(headline=candidate.experience[0].title,
                          professional_summary='Unsupported generic professional.',
                          core_skills=[], experience=experience)


def layout_profile():
    """Stress the page preference without making evidence mandatory by citation."""
    candidate = profile()
    source = candidate.experience[0]
    candidate.experience = [source.model_copy(update={
        'company': f'Fictional Network {i}', 'start': str(2024 - i),
        'end': 'Present' if not i else str(2025 - i),
        'facts': [
            f'Delivered L1 and L2 user support for {170 + i} users across five locations.',
            f'Restored VPN access for {50 + i} users after a client configuration incident.',
        ],
    }) for i in range(12)]
    return candidate


SCENARIOS = {
    'Technical Support Engineer': {
        'description': '''Responsibilities
Deliver L1/L2 user support across office locations.
Troubleshoot VPN and workstation incidents with end users.
Requirements
Professional experience with user support and VPN troubleshooting.
Benefits
Optional Docker and machine learning workshops.''',
        'employment': (SUPPORT,),
        'project': '',
    },
    'Windows Administrator': {
        'description': '''Responsibilities
Administer Windows Server, Active Directory and Group Policy.
Test Windows Server backup restoration and document recovery.
Requirements
Professional experience administering Active Directory and Windows Server.
Benefits
Optional machine learning workshops.''',
        'employment': (WINDOWS, WINDOWS_RESTORE),
        'project': '',
    },
    'Production Support Engineer': {
        'description': '''Responsibilities
Investigate production incidents with application logs and SQL queries.
Coordinate production incident escalations with engineering and maintain runbooks.
Requirements
Professional experience in production support and read-only SQL.
Benefits
Optional Windows administration workshops.''',
        'employment': (PRODUCTION, ESCALATION),
        'project': '',
    },
    'Technical Implementation Specialist': {
        'description': '''Responsibilities
Onboard enterprise customers and configure SSO for SaaS integrations.
Troubleshoot REST API integrations and OAuth authentication with customers.
Requirements
Professional experience with customer onboarding, OAuth and REST API integrations.
Benefits
Optional Linux administration workshops.''',
        'employment': (IMPLEMENTATION, API),
        'project': 'Personal calendar connector',
    },
    'Junior DevOps Engineer': {
        'description': '''Responsibilities
Maintain Linux deployment pipelines in GitLab CI and troubleshoot releases.
Automate deployment checks with Bash and monitor service health using Prometheus.
Requirements
Linux, GitLab CI and Bash scripting.
Kubernetes and Terraform.
Benefits
Optional Active Directory workshops.''',
        'employment': (DEVOPS, MONITORING, AUTOMATION),
        'project': 'Personal container lab',
    },
}
