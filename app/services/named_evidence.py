"""Ceilings for explicit product/test scopes; adjacent technologies are not proof.

This does not discover qualifications or infer arbitrary semantic equivalence.
It only prevents a model's short English label from losing a named source scope.
"""
import re

from app.services.evidence_matching import NEGATIVE
from app.services.evidence_strength import evidence_strength

SCOPES = {
    'Microsoft Entra ID': r'\b(?:Microsoft\s+)?Entra\s+ID\b|\bAzure\s+(?:AD|Active Directory)\b',
    'Conditional Access': r'\bConditional\s+Access\b',
    'MFA': r'\bMFA\b|\bmulti.factor\s+authentication\b|uwierzytelniani\w*\s+wieloskładnikow\w*',
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
IDENTITY_SCOPES = {'Microsoft Entra ID', 'Conditional Access', 'MFA'}


def unrealized_activity(prefix):
    return bool(re.search(
        r'\b(?:will|would|plan\w*\s+to|want\w*\s+to|intend\w*\s+to|learning\s+to|'
        r'not|never|without|hasn[’\x27]t|haven[’\x27]t|didn[’\x27]t)\b(?:\s+\w+){0,2}\s*$', prefix, re.I))


def practical_identity_scope(pattern, entry):
    """Bind practical activity to the product, not a neighboring service mention."""
    for statement in re.split(r'[.;\n]', entry.text):
        if NEGATIVE.search(statement):
            continue
        for action in re.finditer(
            r'\b(?:used|uses|using|configured|configures|configuring|administered|administers|administering|'
            r'managed|manages|implemented|deployed|maintained|integrated|troubleshot)\b', statement, re.I
        ):
            if unrealized_activity(statement[:action.start()]):
                continue
            clause = re.split(r'\b(?:for|without|not|instead\s+of|rather\s+than|connected\s+to|'
                              r'owned\s+by|provided\s+by|managed\s+by)\b',
                              statement[action.end():], maxsplit=1, flags=re.I)[0]
            if re.search(pattern, clause, re.I):
                return True
    return False


def literal_scope_entries(text, entries):
    """Keep cited named-source evidence when a broad matcher selects other facts."""
    required = _EXAMPLES.split(text, maxsplit=1)[0]
    patterns = [EVIDENCE_PATTERNS.get(label, pattern) for label, pattern in SCOPES.items()
                if re.search(pattern, required, re.I)]
    return [entry for entry in entries if not NEGATIVE.search(entry.text)
            and any(re.search(pattern, entry.text, re.I) for pattern in patterns)]


def named_scope_ceiling(text, entries):
    credential = certification_scope_ceiling(text, entries)
    if credential:
        return credential
    # Examples/alternatives are not cumulative product requirements. Existing
    # independently validated AND/OR components remain responsible for those.
    required = _EXAMPLES.split(text, maxsplit=1)[0]
    has_or = bool(re.search(r'\b(?:or|lub)\b', required, re.I))
    mixed_logic = has_or and bool(re.search(r'\b(?:and|oraz|i)\b|[&+]', required, re.I))
    if has_or and not mixed_logic:
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
            if label in IDENTITY_SCOPES:
                relevant = [entry for entry in relevant if practical_identity_scope(pattern, entry)]
        if not relevant:
            missing.append(label)
    if not missing:
        return None
    if mixed_logic:
        return ('partial' if entries else 'missing',
                'Mixed AND/OR named source scope needs component review; not every named branch is evidenced: '
                + ', '.join(missing) + '. No missing alternative is treated as a confirmed absence.')
    combined = bool(re.search(r'\band\b|\boraz\b|\bi\b|[,&+]', required, re.I))
    status = 'partial' if entries and combined else 'missing'
    return status, 'Named source scope is not confirmed: ' + ', '.join(missing) + '. Adjacent tools do not establish this product or test practice.'


def certification_scope_ceiling(text, entries):
    """Practice/training is not possession of a requested credential."""
    if not re.search(r'\b(?:must\s+hold|holds?|posiada\w*)\b[^\n]*\bcertificat\w*|'
                     r'^certyfikat\w*\s+(?:związane|z\s+(?:obszaru|zakresu))', text, re.I):
        return None
    # A literal continuation names alternatives. No list of vendor-specific
    # credentials is hard-coded; require an actual documented credential name.
    continuation = text.split(':', 1)[1] if ':' in text else text
    # A family label before specific parenthesized choices is not itself a
    # credential alternative ("DLP (SC-401 or EDU-222)"). Unknown vendor-only
    # lists need review rather than accepting an arbitrary unrelated certificate.
    choice_text = re.sub(r'\b[A-Z][\w /-]*\(([^()]*)\)', r'\1', continuation)
    choices = set(re.findall(r'\b[A-Z][A-Z0-9]*(?:-\d+)?\b', choice_text)) - {'OR', 'AND', 'IT', 'AI'}
    statements = [statement for entry in entries for statement in re.split(r'[.;\n]', entry.text)]
    supported = {choice for choice in choices if any(certification_statement(s, {choice}) for s in statements)}
    conjunctive = bool(re.search(r'\b(?:and|oraz|i)\b|[&+]', continuation, re.I))
    alternative = not conjunctive and bool(re.search(
        r'\b(?:or|lub|at\s+least\s+one|one\s+of)\b|\ba\s+(?:professional\s+)?certification\s+in:', text, re.I))
    if choices and (bool(supported) if alternative else supported == choices):
        return None
    if supported or (not choices and any(certification_statement(s, set()) for s in statements)):
        return 'partial', 'Credential source scope needs review; possession is documented but not every requested credential or alternative is established.'
    return 'missing', 'Possession of the requested certification is not documented; adjacent product use or training is not a credential or a confirmed absence.'


def certification_statement(statement, choices):
    if NEGATIVE.search(statement) or re.search(
            r'\b(?:expired|lapsed|planned|pending|expected|preparing|studying|pursuing|exam preparation)\b|'
            r'\b(?:not|never|without|no)\b[^.;\n]*\b(?:hold\w*|certificat\w*)\b|'
            r'\b(?:doesn[’\x27]t|hasn[’\x27]t)\b[^.;\n]*\b(?:hold\w*|certificat\w*)\b|'
            r'\b(?:nie\s+posiada\w*|brak\s+certyfikat\w*)\b', statement, re.I
    ):
        return False
    claims = re.finditer(
        r'\b(?:holds?|earned|obtained|awarded)\b[^.;\n]*?\bcertificat\w*\b'
        r'(?:\s+(?:in|for)\s+[^,.;\n]+)?|'
        r'\bcertified\s+(?:in|as)\s+[^,.;\n]+|'
        r'\b(?:posiada|uzyska\w*)\b[^.;\n]*?certyfikat\w*(?:\s+[^,.;\n]+)?', statement, re.I)
    for match in claims:
        if unrealized_activity(statement[:match.start()]):
            continue
        claim = re.split(r'\b(?:and|while|but)\s+(?=(?:has\s+)?(?:attend|stud|prep|plan|pursu|assist|learn)\w*)',
                         match[0], maxsplit=1, flags=re.I)[0]
        if not choices or any(re.search(r'(?<!\w)' + re.escape(choice) + r'(?!\w)', claim, re.I) for choice in choices):
            return True
    return False


def apply_source_ceiling(item, entries):
    """Final source ceiling, including after tenure/language arithmetic."""
    from app.models.job import RequirementStatus
    quotes = list(dict.fromkeys([getattr(item, 'source_quote', ''), *getattr(item, 'source_quotes', [])]))
    quotes = [q for q in quotes if q] or [item.name]
    # Examples/OR in one literal quote cannot exempt a separate source clause.
    ceiling = certification_scope_ceiling('\n'.join(quotes), entries)
    ceiling = ceiling or next((value for q in quotes if (value := named_scope_ceiling(q, entries))), None)
    if item.status == RequirementStatus.STRONG and ceiling:
        item.status = RequirementStatus(ceiling[0])
        if ceiling[1].startswith(('Mixed AND/OR', 'Credential source scope')) and hasattr(item, 'interpretation_uncertain'):
            item.interpretation_uncertain = True
        if ceiling[1] not in item.reason:
            item.reason += ' ' + ceiling[1]
        return True
    return False
