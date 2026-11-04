"""Do not improve style by borrowing duties or weakening summary provenance."""
from app.models.candidate import Experience, Project
from app.services.fact_catalog import FactCatalog
from app.services.professional_summary import build_summary


def test_project_work_editorial_quality(profile):
    """Test that multiple project facts are grouped under a single 'Project work includes' label."""
    profile.projects = [
        Project(name='API lab', facts=[
            'Integrated local models with Pydantic-validated JSON.',
            'Integrates REST API endpoints using Python and HTTPX.'
        ], technologies=['Python', 'HTTPX'])
    ]
    catalog = FactCatalog(profile)
    project_entries = [e for e in catalog.prompt_entries if e.kind == 'project' and ':fact:' in e.source_id]
    priorities = {e.source_id: 100 - i for i, e in enumerate(project_entries)}

    text, ids = build_summary(catalog, 'AI developer\nPython HTTPX REST API JSON local models.', priorities=priorities)

    assert text.count('Project work includes') == 1
    assert 'integrating' in text
    assert text.count('integrating') == 2
    assert '; integrates' not in text
    assert {e.source_id for e in project_entries} <= set(ids)
    assert len(text) <= 700


def test_previous_roles_editorial_quality(profile):
    """Test that earlier employment facts are grouped under 'Previous roles involved'."""
    profile.experience = [
        Experience(company='Current Ltd', title='Dev', start='2023', end='Present', facts=['Current fact.']),
        Experience(company='Earlier DB Ltd', title='DB', start='2020', end='2022', facts=['Used SQL and T-SQL queries for operational verification.']),
        Experience(company='Automation Ltd', title='Auto', start='2018', end='2019', facts=['Automated operational tasks with PowerShell and Python.'])
    ]
    catalog = FactCatalog(profile)
    old_entries = [e for e in catalog.prompt_entries if e.kind == 'experience' and e.owner_index in {1, 2}]
    priorities = {e.source_id: [100, 99][i] for i, e in enumerate(old_entries)}

    text, ids = build_summary(catalog, 'Data developer\nSQL PowerShell Python automation.', priorities=priorities)

    assert 'Previous roles involved' in text
    assert 'using sql' in text.lower()
    assert 'automating' in text.lower()
    assert 'Previous roles:' not in text
    assert all(e.source_id in ids for e in old_entries)


def test_broader_experience_editorial_quality(profile):
    """Test that global summary facts are categorized as broader experience."""
    profile.summary_facts = ['Automates selected workflows with Python.']
    catalog = FactCatalog(profile)

    summary_entries = [e for e in catalog.prompt_entries if e.kind == 'summary']
    assert summary_entries
    priorities = {summary_entries[0].source_id: 100}
    text, ids = build_summary(catalog, 'Automation developer\nPython workflows.', priorities=priorities)

    assert 'Broader experience includes automating' in text
    assert 'Background:' not in text
    assert summary_entries[0].source_id in ids


def test_negation_editorial_quality(profile):
    """Test that project facts with negations preserve exact wording and project scope."""
    profile.projects = [
        Project(name='Secure App', facts=['Does not deploy models commercially.'], technologies=['Security'])
    ]
    catalog = FactCatalog(profile)
    project_entries = [e for e in catalog.prompt_entries if e.kind == 'project' and ':fact:' in e.source_id]
    priorities = {e.source_id: 100 for e in project_entries}

    text, ids = build_summary(catalog, 'Security expert\nSecure app models.', priorities=priorities)

    assert 'Does not deploy models commercially.' in text
    assert 'Project work:' in text
    assert {e.source_id for e in project_entries} <= set(ids)
    assert len(text) <= 700


def test_planned_status_editorial_quality(profile):
    """Test that project facts with planned status preserve exact wording and project scope."""
    profile.projects = [
        Project(name='Future Lab', facts=['Plans to integrate models.'], technologies=['Future'])
    ]
    catalog = FactCatalog(profile)
    project_entries = [e for e in catalog.prompt_entries if e.kind == 'project' and ':fact:' in e.source_id]
    priorities = {e.source_id: 100 for e in project_entries}

    text, ids = build_summary(catalog, 'Future tech\nModel integration.', priorities=priorities)

    assert 'Plans to integrate models.' in text
    assert 'Project work:' in text
    assert {e.source_id for e in project_entries} <= set(ids)
