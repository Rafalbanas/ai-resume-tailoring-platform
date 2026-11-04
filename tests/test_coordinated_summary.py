"""Keep coordinated activity grammar without guessing ambiguous action/object scope."""
import pytest

from app.models.candidate import Project
from app.services.fact_catalog import FactCatalog
from app.services.professional_summary import activity_clause, build_summary


@pytest.mark.parametrize('source,expected', [
    ('Built and tested local and VPS workflows.', 'building and testing local and VPS workflows'),
    ('Developed and deployed an API.', 'developing and deploying an API'),
    ('Built and tested local and VPS workflows combining Python, Docker and local inference.',
     'building and testing local and VPS workflows combining Python, Docker and local inference'),
    ('Integrated local models.', 'integrating local models'),
    ('Built workflows and tested them.', None),
    ('Integrated Python and tested packages.', None),
    ('Built workflows and wrote reports.', None),
    ('Built and benchmarked models.', None),
    ('Built but did not test workflows.', None),
    ('Plans to build models.', None),
])
def test_activity_clause_rules(source, expected):
    assert activity_clause(source) == expected


def test_build_summary_integration(profile):
    fact = 'Built and tested local and VPS workflows.'
    profile.summary_facts = []
    profile.projects = [Project(name='Workflow lab', facts=[fact])]
    catalog = FactCatalog(profile)
    source = next(e.source_id for e in catalog.prompt_entries if e.kind == 'project' and e.text == fact)
    summary, ids = build_summary(catalog, 'API developer\nLocal VPS workflows.', priorities={source: 100})
    assert 'Project work includes building and testing local and VPS workflows.' in summary
    assert 'building and tested' not in summary
    assert 'Support Engineer at Example Ltd.' in summary
    assert source in ids
    assert len(summary) <= 700


def test_build_summary_fallback_integration(profile):
    fact = 'Built workflows and tested them.'
    profile.summary_facts = []
    profile.projects = [Project(name='Workflow lab', facts=[fact])]
    catalog = FactCatalog(profile)
    source = next(e.source_id for e in catalog.prompt_entries if e.kind == 'project' and e.text == fact)
    summary, ids = build_summary(catalog, 'API developer\nLocal VPS workflows.', priorities={source: 100})
    assert 'Project work: Built workflows and tested them.' in summary
    assert 'Support Engineer at Example Ltd.' in summary
    assert source in ids
    assert len(summary) <= 700
