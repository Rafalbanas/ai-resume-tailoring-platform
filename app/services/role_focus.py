"""Rank documented content for a target role; never infer candidate capability."""
import re


def role_focus_score(text, role):
    title = role.splitlines()[0] if role.splitlines() else role
    if re.search(r'data scientist|machine learning|\bML engineer\b', title, re.I):
        if not re.search(r'machine learning|\bML\b|data pipeline|data processing|'
                         r'\b(?:pandas|scikit.learn|PyTorch|NumPy|XGBoost)\b|'
                         r'(?:train|evaluat|compar)\w*.*\bmodels?\b', text, re.I):
            return 0
        patterns = [r'machine learning|\bML\b', r'thesis|academic|coursework|studies',
                    r'data pipeline|data processing', r'(?:train|evaluat|compar)\w*.*\bmodels?\b',
                    r'\b(?:pandas|scikit.learn|PyTorch|NumPy|XGBoost)\b']
    elif re.search(r'data engineer|inżynier\w* danych', title, re.I):
        patterns = [r'data pipeline|data processing|\bETL\b|\bELT\b',
                    r'\bSQL\b|database|data verification', r'\b(?:Python|pandas|PySpark|Airflow)\b']
    elif re.search(r'\bAI (?:agent |solution )?(?:engineer|developer|specialist)\b', title, re.I):
        patterns = [r'\bLLM\b|Ollama|local models', r'\bAPI\b|\bHTTPX\b|FastAPI',
                    r'guardrails|Pydantic|structured JSON', r'\bn8n\b|automation|automating']
    else:
        return 0
    return sum(bool(re.search(pattern, text, re.I)) for pattern in patterns)
