"""Rank documented content for a target role; never infer candidate capability."""
import re
from dataclasses import dataclass

from app.services.fact_catalog import normalized_tokens


def role_family(role):
    """Classify only the target title, never incidental tools in the posting."""
    title = role.splitlines()[0] if role.splitlines() else role
    if re.search(r'\bsupport\b|help.?desk|wsparci\w*|service desk', title, re.I):
        return 'support'
    if re.search(r'data scientist|machine learning|\bML engineer\b', title, re.I):
        return 'data_science'
    if re.search(r'data engineer|inżynier\w* danych', title, re.I):
        return 'data_engineering'
    if re.search(r'\b(?:AI|LLM|GenAI)\b|sztuczn\w* inteligenc', title, re.I):
        return 'ai'
    if re.search(r'automation|automatyzac', title, re.I):
        return 'automation'
    if re.search(r'forward.deployed engineer|software (?:engineer|developer)|backend (?:engineer|developer)', title, re.I):
        return 'software'
    if re.search(r'\b(?:DevOps|SRE|Site Reliability Engineer|Platform Engineer|Infrastructure Engineer)\b', title, re.I):
        return 'devops'
    if re.search(r'\b(?:(?:systems?|Linux|Windows) administrator|administrator(?: IT| systemów| systemow))\b', title, re.I):
        return 'system_administration'
    return 'other'


def role_focus_score(text, role):
    family = role_family(role)
    if family == 'data_science':
        if not re.search(r'machine learning|\bML\b|data pipeline|data processing|'
                         r'\b(?:pandas|scikit.learn|PyTorch|NumPy|XGBoost)\b|'
                         r'(?:train|evaluat|compar)\w*.*\bmodels?\b', text, re.I):
            return 0
        patterns = [r'machine learning|\bML\b', r'thesis|academic|coursework|studies',
                    r'data pipeline|data processing', r'(?:train|evaluat|compar)\w*.*\bmodels?\b',
                    r'\b(?:pandas|scikit.learn|PyTorch|NumPy|XGBoost)\b']
    elif family == 'data_engineering':
        patterns = [r'data pipeline|data processing|\bETL\b|\bELT\b',
                    r'\bSQL\b|database|data verification', r'\b(?:Python|pandas|PySpark|Airflow)\b']
    elif family == 'ai':
        patterns = [r'\bLLM\b|Ollama|local models', r'\bAPI\b|\bHTTPX\b|FastAPI',
                    r'guardrails|Pydantic|structured JSON', r'\bn8n\b|automation|automating',
                    r'AI.assisted|coding assistants|Codex', r'\bPython\b|machine learning']
    elif family in {'software', 'automation'}:
        weighted = [(r'\bPython\b|FastAPI|Pydantic', 2),
                    (r'\bAPI\b|HTTPX|structured JSON', 2),
                    (r'\bn8n\b|automation|automating|automated', 2),
                    (r'\btests?\b|CI/CD|GitHub Actions', 1),
                    (r'\bdeploy\w*\b|Docker', 1)]
        return sum(weight for pattern, weight in weighted if re.search(pattern, text, re.I))
    elif family == 'devops':
        patterns = [r'\b(?:Linux|Unix)\b', r'\b(?:Docker|Kubernetes|containers?)\b', r'CI/CD|\bGitLab\b|GitHub Actions',
                    r'\b(?:Bash|Python)\b|automat\w*|skrypt\w*', r'monitor\w*|\b(?:Prometheus|Grafana)\b', r'\b(?:networks?|networking|DNS)\b|TCP/IP|sieci']
    elif family == 'system_administration':
        patterns = [r'\b(?:Windows|Linux|Unix)\b', r'\bAD\b|Active Directory', r'\b(?:networks?|networking|DNS)\b|TCP/IP|sieci',
                    r'backup\w*|restor\w*|kopi\w* zapas', r'virtual\w*|wirtual\w*|\b(?:VMware|Proxmox)\b']
    else:
        return 0
    return sum(bool(re.search(pattern, text, re.I)) for pattern in patterns)


# Facets are shared by related jobs. A tool such as Linux or SQL on its own
# cannot make a posting an infrastructure or production support role.
_FACETS = {name: re.compile(pattern, re.I) for name, pattern in {
    'user_support': r'\b(?:help.?desk|service desk|end.users?|business users?|user support|desktop support|L[12]|VPN)\b',
    'customer_support': r'\b(?:customer.facing|customer support|technical support|support tickets?|business customers?|customer issues?)\b',
    'incidents': r'\b(?:incidents?|escalat\w*|root cause|outages?|on.call|triage)\b',
    'diagnostics': r'\b(?:diagnostic\w*|logs?|log analysis|troubleshoot\w*|debug\w*|reproduc\w*)\b',
    'data_checks': r'\b(?:SQL|T.SQL|queries|database\w*|data verification)\b',
    'production': r'\b(?:production support|application support|production (?:services?|incidents?|environments?|systems?)|runbooks?|service restoration)\b',
    'windows': r'\b(?:Windows(?: Server)?|Active Directory|GPO|Group Policy|Intune|PowerShell)\b',
    'linux': r'\b(?:Linux|Unix|systemd|Bash)\b',
    'infrastructure': r'\b(?:network\w*|DNS|DHCP|TCP/IP|servers?|virtuali[sz]\w*|VMware|Proxmox|backups?|restor\w*)\b',
    'implementation': r'\b(?:onboard\w*|rollouts?|implement\w*|customer (?:training|configuration)|go.live|configuration workshops?)\b',
    'integration': r'\b(?:integrat\w*|APIs?|REST|HTTPX|webhooks?|JSON|SaaS)\b',
    'identity': r'\b(?:authenticat\w*|SSO|SAML|OAuth2?|OIDC|OpenID Connect)\b',
    'delivery': r'\b(?:CI/CD|GitHub Actions|GitLab CI|deployment pipelines?|release pipelines?|container\w*|Docker|Kubernetes|Terraform|infrastructure.as.code)\b',
    'monitoring': r'\b(?:monitor\w*|observability|Prometheus|Grafana|health checks?|alert\w*)\b',
    'automation': r'\b(?:automat\w*|script\w*|Ansible|n8n|PowerShell)\b',
    'software': r'\b(?:backend|software (?:engineer\w*|develop\w*)|Python|FastAPI|unit tests?|microservices?|code review)\b',
    'data_platform': r'\b(?:ETL|ELT|data (?:engineering|pipelines?|processing)|Airflow|PySpark|data warehouse)\b',
    'ml': r'\b(?:machine learning|ML|scikit.learn|PyTorch|training models?|model evaluation|regression|cross.validation)\b',
    'ai': r'\b(?:LLMs?|Ollama|GenAI|large language models?|inference|model serving|AI)\b',
    'collaboration': r'\b(?:collaborat\w*|coordinat\w*|handoffs?|technical documentation|knowledge base|stakeholders?)\b',
}.items()}
_TITLE_FACETS = {
    'support': ('user_support', 'customer_support', 'incidents', 'diagnostics'),
    'production_support': ('production', 'incidents', 'diagnostics', 'data_checks', 'monitoring'),
    'implementation': ('implementation', 'integration', 'identity', 'customer_support'),
    'integration_support': ('integration', 'identity', 'diagnostics', 'customer_support'),
    'system_administration': ('windows', 'linux', 'infrastructure', 'identity'),
    'infrastructure': ('infrastructure', 'windows', 'linux', 'monitoring'),
    'devops': ('delivery', 'linux', 'monitoring', 'automation', 'infrastructure'),
    'automation': ('automation', 'software', 'integration', 'delivery'),
    'software': ('software', 'integration', 'data_checks', 'delivery'),
    'data_engineering': ('data_platform', 'data_checks', 'software', 'automation'),
    'data_science': ('ml', 'data_platform'),
    'ai': ('ai', 'ml', 'software', 'integration'),
}
_FAMILY_SIGNALS = {
    'support': ('user_support', 'customer_support'),
    'production_support': ('production', 'incidents'),
    'implementation': ('implementation', 'integration'),
    'integration_support': ('integration', 'identity'),
    'system_administration': ('windows', 'infrastructure'),
    'infrastructure': ('infrastructure', 'linux'),
    'devops': ('delivery', 'monitoring'),
    'automation': ('automation', 'software'),
    'software': ('software', 'integration'),
    'data_engineering': ('data_platform', 'data_checks'),
    'data_science': ('ml', 'data_platform'),
    'ai': ('ai', 'ml'),
}
_GENERIC_TERMS = set('work team teams new experience technical systems system skills support role '
                     'ability requirements responsibilities experience knowledge tools tasks use '
                     'we you our your will develop manage services service need business customer '
                     'environment relevant including required working must have'.split())
_CROSS_ROLE_TERMS = set('investigate investigated coordinate coordinated maintain maintained document documented '
                        'troubleshooting troubleshoot incidents incident escalations diagnostic logs using '
                        'deployment deployments recovery steps operations operational configure configured'.split())


def _facets(text):
    return {name for name, pattern in _FACETS.items() if pattern.search(text)}


@dataclass(frozen=True)
class TargetFocus:
    title: str
    family: str
    families: tuple[str, ...]
    weights: dict[str, int]
    terms: frozenset[str]
    duties: tuple[str, ...]
    evidence_led: bool
    professional_required: bool

    @property
    def has_specific_duties(self):
        return any(_facets(duty) for duty in self.duties)

    def direct_terms(self, text):
        return (normalized_tokens(text) & self.terms) - _CROSS_ROLE_TERMS

    def score(self, text):
        if not self.evidence_led:
            return role_focus_score(text, self.title)
        # Match topics, not occurrence counts. Bound the advantage of long
        # tool lists: a third matching topic is only a tiebreaker.
        weights = sorted((self.weights.get(f, 0) for f in _facets(text)), reverse=True)
        return sum(weights[:2]) + min(1, sum(w > 0 for w in weights[2:]))


def target_focus(title, description='', analysis=None):
    """Derive presentation signals from the ad, never qualification or skill data."""
    from app.services.job_sections import extract_sections, relevance_text

    title = title.split('\n', 1)[0]
    family = role_family(title)
    for pattern, name in (
        (r'\b(?:production|application) support\b', 'production_support'),
        (r'\bimplementation\b', 'implementation'),
        (r'\b(?:SaaS|integration) support\b', 'integration_support'),
        (r'\binfrastructure engineer\b', 'infrastructure'),
    ):
        if re.search(pattern, title, re.I):
            family = name
            break
    units, _ = extract_sections(description)
    duties = tuple(dict.fromkeys(u.name for u in units if u.category == 'responsibility'))
    must = tuple(dict.fromkeys(u.name for u in units if u.category == 'mandatory'))
    if analysis and getattr(analysis, 'validation_version', 0) >= 2:
        # Source-review/validated semantic analysis also handles unheaded ads.
        # Check the original quote again; do not rank against candidate evidence.
        duties = tuple(dict.fromkeys([*duties, *(
            d['source_quote'] for d in analysis.responsibilities
            if d.get('source_quote') and d['source_quote'] in description)]))
        must = tuple(dict.fromkeys([*must, *(
            r.source_quote for r in analysis.requirements if r.priority == 'mandatory'
            and r.source_quote and r.source_quote in description)]))
    contextual = _facets(' '.join((*duties, *must)))
    extended_title = family in {'production_support', 'implementation', 'integration_support', 'infrastructure'}
    other_context = _facets(description) if not units else set()
    evidence_led = bool(_facets(' '.join(duties)) or (len(must) >= 2 and len(contextual) >= 2)
                        or extended_title or (family == 'other' and len(contextual or other_context) >= 2))
    observed = contextual or (other_context if evidence_led else set())
    if family == 'other' and any(set(signals) <= observed for signals in _FAMILY_SIGNALS.values()):
        family = next(name for name, signals in _FAMILY_SIGNALS.items() if set(signals) <= observed)
    families = tuple(name for name, signals in _FAMILY_SIGNALS.items()
                     if name != family and set(signals) <= observed)
    if family != 'other':
        families = (family, *families)
    weights = {facet: 1 for facet in _TITLE_FACETS.get(family, ()) if not observed or facet in observed}
    for facet in _facets(' '.join(must)):
        weights[facet] = 3
    for facet in _facets(' '.join(duties)):
        weights[facet] = 4 if weights.get(facet) == 3 else 3
    for facet in other_context if evidence_led else ():
        weights.setdefault(facet, 2)
    text = ' '.join((title, *duties, *must)) if duties or must else relevance_text(f'{title}\n{description}')
    professional_required = any(re.search(
        r'\b(?:commercial|professional|industry|paid|workplace|on.the.job) (?:\w+ )?experience\b'
        r'|\b(?:experience in (?:a )?(?:commercial|production)|doświadczenie zawodowe)\b', line, re.I)
        for line in must)
    return TargetFocus(title, family, families, weights, frozenset(normalized_tokens(text) - _GENERIC_TERMS),
                       duties, evidence_led, professional_required)
