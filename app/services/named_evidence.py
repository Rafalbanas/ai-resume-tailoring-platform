"""Ceilings for explicit product/test scopes; adjacent technologies are not proof.

This does not discover qualifications or infer arbitrary semantic equivalence.
It only prevents a model's short English label from losing a named source scope.
"""
import re

from app.services.evidence_matching import NEGATIVE
from app.services.evidence_strength import evidence_strength

SCOPES = {
    'Postman': r'\bPostman\b',
    'prompt regression testing': r'\bprompt regression test\w*|test\w* regresj\w* prompt\w*',
    'LLM evaluation tools': r'\b(?:automated )?LLM evaluation tools\b|narzędz\w* do automatyczn\w* ewaluacj\w* LLM',
    'platform architecture ownership': r'\bfoundational platform decisions\b|\bgovern platform.level standards\b|\barchitectural oversight\b',
    'large-organization experience': r'\blarge (?:organization|company|enterprise)\b|\bduż\w* organizacj\w*\b',
    'AWS': r'\bAWS\b|\bAmazon Web Services\b',
    'GCP': r'\bGCP\b|\bGoogle Cloud(?: Platform)?\b',
    'ITIL': r'\bITIL\b',
    'XML': r'\bXML\b',
    'unstructured data': r'\bunstructured data\b|\bdany\w* nieustrukturyzowan\w*|\bnieustrukturyzowan\w*',
    'Microsoft Office': r'\b(?:Microsoft|MS) Office\b',
    'Microsoft Teams': r'\b(?:Microsoft|MS) Teams\b',
    'knowledge bases': r'\bknowledge bases?\b|\bbaz\w*\s+wiedz\w*',
    'Azure NSGs': r'\bNSGs?\b|\bnetwork security groups?\b',
    'Private Endpoints': r'\bprivate endpoints?\b',
    'ExpressRoute': r'\bExpressRoute\b',
    'ETL/data analytics platforms': r'\bETL\b|\bdata analytics platforms?\b',
    'LLM observability': r'\bLLM (?:observability|monitoring)\b|\bmonitor(?:ing|owania) (?:modeli )?LLM\b',
    'vulnerability assessment': r'\bvulnerabilit\w*|\bpodatnoś\w*',
    'privilege escalation': r'\bprivilege escalation\b|\beskalacj\w* uprawnień\b',
    'managed services': r'\bmanaged services\b',
    'business results': r'\bbusiness (?:results|outcomes)\b|\bwynik\w* biznesow\w*',
    'tight deadlines': r'\b(?:tight|strict) deadlines\b|\bunder (?:time|deadline) pressure\b',
    'project leadership': r'\b(?:lead|led|leading)\b[^.;\n]*\bprojects?\b',
    'customer project leadership': r'(?=[^\n]*\b(?:lead|led|leading)\b)(?=[^\n]*\bprojects?\b)(?=[^\n]*\b(?:customers?|clients?)\b)',
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
EVIDENCE_PATTERNS = {
    'LLM evaluation tools': r'\b(?:automated )?LLM evaluation tools\b|\b(?:promptfoo|DeepEval|RAGAS)\b|narzędz\w* do automatyczn\w* ewaluacj\w* LLM',
    # Named suite members can document Office use; generic Microsoft 365
    # administration and the ordinary word "teams" cannot prove app use.
    'Microsoft Office': (r'\b(?:Microsoft|MS) Office\b|\b(?:Microsoft|MS) (?:Word|Excel|PowerPoint)\b|'
                         r'(?-i:\bPowerPoint\b|\bExcel\b(?!\s+(?:at|in)\b)|'
                         r'\bWord\b(?!\s+(?:embeddings?|vectors?|tokens?)\b))'),
}


def literal_scope_entries(text, entries):
    """Keep cited named-source evidence when a broad matcher selects other facts."""
    required = _EXAMPLES.split(text, maxsplit=1)[0]
    patterns = [EVIDENCE_PATTERNS.get(label, pattern) for label, pattern in SCOPES.items()
                if re.search(pattern, required, re.I)]
    return [entry for entry in entries if not NEGATIVE.search(entry.text)
            and any(re.search(pattern, entry.text, re.I) for pattern in patterns)]


def named_scope_ceiling(text, entries):
    # Examples/alternatives are not cumulative product requirements. Existing
    # independently validated AND/OR components remain responsible for those.
    required = _EXAMPLES.split(text, maxsplit=1)[0]
    if re.search(r'\b(?:or|lub)\b', required, re.I):
        return None
    requested = [(label, pattern) for label, pattern in SCOPES.items() if re.search(pattern, required, re.I)]
    if not requested:
        return None
    practical = bool(re.search(r'experience|hands.on|practical|working|proficien|doświadczen|praktyczn|samodzieln\w*|test', required, re.I))
    missing = []
    for label, pattern in requested:
        pattern = EVIDENCE_PATTERNS.get(label, pattern)
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


def apply_source_ceiling(item, entries):
    """Final source ceiling, including after tenure/language arithmetic."""
    from app.models.job import RequirementStatus
    ceiling = named_scope_ceiling(getattr(item, 'source_quote', '') or item.name, entries)
    if item.status == RequirementStatus.STRONG and ceiling:
        item.status = RequirementStatus(ceiling[0])
        if ceiling[1] not in item.reason:
            item.reason += ' ' + ceiling[1]
        return True
    return False
