import pytest

from app.models.job import JobRequest
from app.models.resume import TailoredResume
from app.services.cv_content_policy import check_export_content, networking_terminology_issue
from app.services.fact_validator import FactValidator
from app.services.summary_review import sign_summary


@pytest.mark.parametrize('text', [
    'Configured routing protocols (static routes, NAT, DHCP, VPN) on routers.',
    'Routing protocols: NAT, DHCP and VPN.',
    'Configured routing protocols including static routing.',
    'Configured routing protocols such as DHCP.',
])
def test_invalid_network_lists_cannot_be_exported(text, profile, resume_payload):
    assert networking_terminology_issue(text)
    resume = TailoredResume.model_validate(resume_payload)
    resume.professional_summary = text
    with pytest.raises(ValueError, match='Invalid networking terminology'):
        check_export_content(resume)


@pytest.mark.parametrize('text', [
    'Configured IP addressing, static routes, NAT, DHCP and VPN on routers.',
    'Configured routing protocols (OSPF, BGP), NAT and DHCP.',
    'Configured routing protocols: OSPF and BGP. Configured NAT and DHCP.',
    'Configured static routes and network services (NAT, DHCP and VPN).',
    'No experience with routing protocols. Configured NAT and DHCP.',
])
def test_separate_routing_and_network_services_are_not_rejected(text):
    assert not networking_terminology_issue(text)


def test_signed_model_summary_cannot_bypass_terminology_validation(profile, resume_payload):
    resume = TailoredResume.model_validate(resume_payload)
    resume.professional_summary = 'Configured routing protocols (static routes, NAT, DHCP, VPN).'
    resume.summary_attestation = sign_summary(resume, profile, 'secret')
    job = JobRequest(company='Example', role='Support', job_description='Requirements: Python operational automation and support.')
    result = FactValidator(profile, review_key='secret').validate(resume, job).resume
    assert 'routing protocols' not in result.professional_summary
    assert result.professional_summary.endswith(profile.summary_facts[0])
