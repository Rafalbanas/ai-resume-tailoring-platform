"""Ceilings for explicit product/test scopes; adjacent technologies are not proof.

This does not discover qualifications or infer arbitrary semantic equivalence.
It only prevents a model's short English label from losing a named source scope.
"""
import re

from app.services.evidence_matching import NEGATIVE
from app.services.evidence_strength import evidence_strength

SCOPES = {
    'Zendesk': r'\bZendesk\b',
    'Azure DevOps': r'\bAzure (?:DevOps|Pipelines)\b',
    'Azure Integration Services': r'\bAzure Integration Services\b',
    'Azure Logic Apps': r'\b(?:Azure )?Logic Apps\b',
    'Azure Functions': r'\bAzure Function(?:s| Apps)?\b',
    'Azure Service Bus': r'\b(?:Azure )?Service Bus\b',
    'Azure Event Hub': r'\bAzure Event Hubs?\b',
    'Azure API Management': r'\bAzure API Management\b|\bAPIM\b',
    'Microsoft Azure': r'\b(?:Microsoft )?Azure\b(?!\s+(?:DevOps|AD|Active Directory))',
    'SSO': r'\bSSO\b|\bsingle[ -]sign[ -]on\b',
    'performance testing': r'\bperformance test\w*|test\w* wydajności\w*',
    'load testing': r'\bload test\w*|test\w* obciążeni\w*',
}
_EXAMPLES = re.compile(r'\b(?:such as|for example|e\.g\.|takich jak|np\.)\s*', re.I)


def named_scope_ceiling(text, entries):
    # Examples/alternatives are not cumulative product requirements. Existing
    # independently validated AND/OR components remain responsible for those.
    required = _EXAMPLES.split(text, maxsplit=1)[0]
    if re.search(r'\b(?:or|lub)\b', required, re.I):
        return None
    requested = [(label, pattern) for label, pattern in SCOPES.items() if re.search(pattern, required, re.I)]
    if not requested:
        return None
    practical = bool(re.search(r'experience|hands.on|practical|working|proficien|doświadczen|praktyczn|test', required, re.I))
    missing = []
    for label, pattern in requested:
        relevant = [entry for entry in entries if re.search(pattern, entry.text, re.I) and not NEGATIVE.search(entry.text)]
        if practical:
            relevant = [entry for entry in relevant if evidence_strength(entry) not in
                        {'declaration', 'theoretical_knowledge', 'academic_knowledge'}]
        if not relevant:
            missing.append(label)
    if not missing:
        return None
    combined = bool(re.search(r'\band\b|\boraz\b|\bi\b|,', required, re.I))
    status = 'partial' if entries and combined else 'missing'
    return status, 'Named source scope is not confirmed: ' + ', '.join(missing) + '. Adjacent tools do not establish this product or test practice.'
