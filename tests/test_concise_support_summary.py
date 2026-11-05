from app.services.fact_catalog import FactCatalog
from app.services.professional_summary import build_summary


def test_overlong_support_summary_uses_compact_source_composition(profile):
    profile = profile.model_copy(deep=True)
    profile.summary_facts = [
        'Provides Tier 2 support for Example partners across EMEA.',
        'Experienced in Windows, application and network troubleshooting, incident handling and cross-tier escalation.',
        'Analyzes application logs, errors and system behaviour to identify root causes of technical incidents and coordinate escalations with engineering teams.',
        'Uses English at B2 level in daily professional work.',
        'Automates selected operational tasks with PowerShell and Python.',
    ]
    profile.experience[0].facts.append('Used MS SQL Server and T-SQL for operational queries and data verification.')
    catalog = FactCatalog(profile)
    text, ids = build_summary(catalog, 'Technical Support Engineer')
    compact, compact_ids = build_summary(catalog, 'Technical Support Engineer', compact=True)
    assert len(text) <= 500
    assert text.endswith('.')
    assert text == compact
    assert ids == compact_ids
    assert all(catalog.get(source_id) for source_id in ids)
    assert 'English' in text


def test_short_summary_is_not_forced_to_lose_details(profile):
    text, ids = build_summary(FactCatalog(profile), 'Technical Support Engineer')
    assert text and text.endswith('.') and ids
