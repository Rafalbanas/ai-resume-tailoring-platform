import pytest

from app.services.role_focus import role_family, role_focus_score


@pytest.mark.parametrize("role_title, expected_family", [
    ("DevOps Engineer", "devops"),
    ("SRE", "devops"),
    ("Site Reliability Engineer", "devops"),
    ("Platform Engineer", "devops"),
    ("Infrastructure Engineer", "devops"),
    ("System Administrator", "system_administration"),
    ("Systems Administrator", "system_administration"),
    ("Linux Administrator", "system_administration"),
    ("Windows Administrator", "system_administration"),
    ("Administrator IT", "system_administration"),
    ("Administrator systemów", "system_administration"),
    ("Data Scientist", "data_science"),
    ("Support Specialist", "support"),
    ("Software Engineer", "software")
])
def test_role_family_classification(role_title, expected_family):
    assert role_family(role_title) == expected_family

@pytest.mark.parametrize("keyword", [
    "Linux", "Docker", "Kubernetes", "CI/CD", "Bash", "Prometheus", "DNS"
])
def test_devops_score_positive(keyword):
    role = "DevOps Engineer"
    text = f"Experience with {keyword}."
    assert role_focus_score(text, role) > 0

def test_devops_full_score():
    role = "DevOps Engineer"
    text = "Expertise in Linux, Docker, Kubernetes, CI/CD, Bash, Prometheus, and DNS."
    assert role_focus_score(text, role) == 6

def test_system_administration_score():
    role = "System Administrator"
    text = "Expert in Windows, AD, networks, backup, and VMware."
    assert role_focus_score(text, role) == 5

def test_role_focus_score_no_reclassification_by_content():
    role = "Data Scientist"
    text = "Proficient in Windows and manage networks."
    assert role_focus_score(text, role) == 0

def test_negative_unknown_job():
    # Unknown job\nDevOps Engineer -> other
    role = "Unknown job\nDevOps Engineer"
    # Note: role_family uses first line. First line is "Unknown job".
    assert role_family(role) == "other"

def test_negative_support_with_devops_content():
    # Technical Support Engineer\nLinux Docker -> support and score=0
    role = "Technical Support Engineer\nLinux Docker"
    # role_family sees "Technical Support Engineer" first line -> support
    # score for support is always 0.
    assert role_family(role) == "support"
    assert role_focus_score("Linux Docker extra content", role) == 0

def test_devops_over_support():
    role = "DevOps Engineer"
    support_text = "Experienced in help desk and service desk support."
    devops_text = "Managed Docker and Kubernetes."
    assert role_focus_score(devops_text, role) > role_focus_score(support_text, role)
