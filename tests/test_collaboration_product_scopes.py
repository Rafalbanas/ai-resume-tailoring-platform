import pytest

from app.models.candidate import CandidateProfile, Project
from app.models.job import JobRequirement
from app.services.analysis_validator import AnalysisValidator
from app.services.semantic_requirements import _facts


@pytest.mark.parametrize('name,quote,facts,missing', [
    ('Jira and Microsoft Office',
     'Znajomość systemu Jira i programów z rodziny Microsoft Office rozumiana jako umiejętność samodzielnego posługiwania się nimi.',
     ['Used Jira for incident escalation.', 'Supported Windows and Microsoft 365 users.'], 'Microsoft Office'),
    ('Atlassian collaboration', 'Experience with Atlassian / Jira and MS Teams.',
     ['Used Jira for incident escalation and collaborated with other teams.'], 'Microsoft Teams'),
    ('Data platforms', 'Experience with databases and knowledge bases.',
     ['Used SQL queries and SQLAlchemy for relational data modeling.'], 'knowledge bases'),
    ('Jira and Microsoft Office', 'Experience with Jira and Microsoft Office.',
     ['Used Jira for incident escalation.', 'Word embeddings were used in an NLP experiment.'], 'Microsoft Office'),
])
def test_related_tool_does_not_cover_the_other_explicit_conjunct(name, quote, facts, missing):
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'}, projects=[Project(name='Synthetic project', facts=facts)])
    validator = AnalysisValidator(profile)
    req = JobRequirement(name=name, source_quote=quote, status='strong', reason='Overbroad model confirmation.',
                         source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status != 'strong'
    assert missing in req.reason


@pytest.mark.parametrize('quote,fact', [
    ('Knowledge of Microsoft Office and Jira.', 'Used Microsoft Office (Word, Excel and PowerPoint) and Jira.'),
    ('Experience with Microsoft Office and Jira.', 'Used Word and Excel to prepare reports and Jira for escalation.'),
    ('Experience with Jira and MS Teams.', 'Used Jira and Microsoft Teams to coordinate incident resolution.'),
    ('Experience with databases and knowledge bases.', 'Used SQL and maintained a support knowledge base.'),
])
def test_exact_documented_scope_is_not_rejected(quote, fact):
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'}, projects=[Project(name='Synthetic project', facts=[fact])])
    validator = AnalysisValidator(profile)
    req = JobRequirement(name=quote, source_quote=quote, status='strong', reason='Both scopes documented.',
                         source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status == 'strong'
