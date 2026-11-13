"""Rank documented content for a target role; never infer candidate capability."""
import re


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
