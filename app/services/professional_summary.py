"""Select concise source sentences; job text influences order, never candidate facts."""
import re

from app.services.fact_catalog import FactCatalog, normalized_tokens


def build_summary(catalog: FactCatalog, role: str) -> tuple[str, list[str]]:
    entries = [e for e in catalog.prompt_entries if e.kind == 'summary']
    # Dates/tenure are particularly easy to overstate; experience dates remain visible.
    entries = [e for e in entries if not re.search(r'\byears?\b|\blat\b', e.text, re.I)]
    tokens = normalized_tokens(role)
    themes = {
        'support': {'support', 'troubleshooting', 'incident', 'english'},
        'windows': {'windows', 'powershell', 'automation', 'troubleshooting'},
        'python': {'python', 'automation', 'linux'},
        'erp': {'support', 'application', 'incident', 'english'},
        'sap': {'support', 'application', 'incident', 'english'},
    }
    for trigger, words in themes.items():
        if trigger in tokens:
            tokens |= words
    ordered = sorted(entries, key=lambda e: len(normalized_tokens(e.text) & tokens), reverse=True)
    # The current supported occupation gives the reader context even for stretch roles.
    identity = next((e for e in entries if 'support' in e.text.casefold()), None)
    selected = ([identity] if identity else []) + [e for e in ordered if e != identity]
    text, ids = '', []
    for entry in selected:
        sentence = entry.text.strip()
        if not sentence:
            continue
        sentence += '' if sentence[-1] in '.!?' else '.'
        if len(text) + len(sentence) + 1 > 700:
            continue
        text = f'{text} {sentence}'.strip()
        ids.append(entry.source_id)
        if len(ids) == 3:
            break
    if normalized_tokens(role) & {"python", "api", "integration", "integrations"}:
        api_fact = next((e for e in catalog.prompt_entries if e.kind == "project" and ":fact:" in e.source_id and "api" in e.text.casefold()), None)
        if api_fact and len(text) + len(api_fact.text) + 1 <= 570:
            text = f"{text} Project work: {api_fact.text}".strip()
            ids.append(api_fact.source_id)
    education = next((e for e in catalog.prompt_entries if e.kind == "education" and "computer science" in e.text.casefold() and ":fact:" not in e.source_id and ":thesis:" not in e.source_id), None)
    if education:
        source = catalog.profile.education[education.owner_index]
        sentence = f"{source.qualification}, {source.institution} ({source.dates})."
        if len(text) + len(sentence) + 1 <= 700:
            text = f"{text} {sentence}".strip()
            ids.append(education.source_id)
    return text, ids
