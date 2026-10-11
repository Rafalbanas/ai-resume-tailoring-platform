"""Select concise source sentences; job text influences order, never candidate facts."""
import re

from app.services.fact_catalog import FactCatalog, normalized_tokens


def deduplicate_summary(value: str, catalog: FactCatalog) -> str:
    """Fuse repeated verified clauses; preserve the identity and every detail.

    Only verbatim source sentences qualify. Similar model paraphrases, negations,
    differing numbers and unknown wording remain subject to normal Truth Lock.
    """
    verified = {e.text.strip().rstrip(".!?") for e in catalog.prompt_entries}
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", value.strip())
    result: list[str] = []
    for sentence in sentences:
        raw = sentence.rstrip(".!?")
        merged = False
        if raw in verified:
            prefix, separator, detail = raw.partition(", ")
            tokens = normalized_tokens(prefix) - {"technical"}
            for index, previous in enumerate(result):
                prior = previous.rstrip(".!?")
                if prior not in verified or ", " in prior:
                    continue
                prior_tokens = normalized_tokens(prior) - {"technical"}
                # Additional identity information in the shorter source is kept.
                # No fuzzy threshold: every token of the repeated clause must exist.
                if (tokens and tokens <= prior_tokens
                        and re.findall(r"\d+", prefix) == re.findall(r"\d+", prior)
                        and re.findall(r"\b(?:not|never|no|without)\b", prefix, re.I)
                        == re.findall(r"\b(?:not|never|no|without)\b", prior, re.I)):
                    if "technical support" in prefix and "technical support" not in prior:
                        prior = prior.replace("support", "technical support", 1)
                    result[index] = prior + (separator + detail if separator else "") + "."
                    merged = True
                    break
        if not merged:
            result.append(sentence)
    return " ".join(result)


def build_summary(catalog: FactCatalog, role: str) -> tuple[str, list[str]]:
    entries = [e for e in catalog.prompt_entries if e.kind == 'summary' or (e.kind == 'experience' and ':fact:' in e.source_id)]
    # Dates/tenure are particularly easy to overstate; experience dates remain visible.
    entries = [e for e in entries if not re.search(r'\byears?\b|\blat\b', e.text, re.I)]
    tokens = normalized_tokens(role)
    themes = {
        'support': {'support', 'troubleshooting', 'troubleshoot', 'incident', 'english', 'customer', 'partner', 'documentation', 'salesforce', 'crm'},
        'crm': {'salesforce', 'crm', 'customer', 'partner', 'support'},
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
    identity = next((e for e in entries if e.kind == 'summary' and 'support' in e.text.casefold()), None)
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
    if education and tokens & {"degree", "education", "science", "bachelor", "msc"}:
        source = catalog.profile.education[education.owner_index]
        sentence = f"{source.qualification}, {source.institution} ({source.dates})."
        if len(text) + len(sentence) + 1 <= 700:
            text = f"{text} {sentence}".strip()
            ids.append(education.source_id)
    return deduplicate_summary(text, catalog), ids
