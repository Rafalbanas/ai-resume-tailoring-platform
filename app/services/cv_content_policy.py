"""Deterministic presentation rules independent of model approval."""
import re

from app.services.fact_catalog import FactCatalog

_INTERNAL = re.compile(
    r"\b(?:user|candidate|manually)[\s\-–—]+(?:confirmed|verified)\b"
    r"|\b(?:system prompt|source_fact_ids|return only json)\b", re.I)


def internal_annotation(text: str) -> bool:
    return bool(_INTERNAL.search(text))


def cv_catalog(profile, job):
    catalog = FactCatalog(profile)
    posting = f"{job.role}\n{job.job_description}"

    def allowed(entry):
        if internal_annotation(entry.text):
            return False
        if entry.kind != "experience" or entry.owner_index is None:
            return True
        terms = profile.experience[entry.owner_index].cv_fact_conditions.get(entry.text)
        return terms is None or any(
            term.strip() and re.search(r"(?<!\w)" + re.escape(term.strip()) + r"(?!\w)", posting, re.I)
            for term in terms)

    catalog.prompt_entries = [e for e in catalog.prompt_entries if allowed(e)]
    ids = {e.source_id for e in catalog.prompt_entries}
    catalog.entries = {key: e for key, e in catalog.entries.items() if e.source_id in ids}
    return catalog


def reviewable_bullet(bullet, profile):
    """A signature cannot waive annotation, citation or lexical evidence checks.

    This is a conservative floor, not a substitute for semantic review.
    """
    if internal_annotation(bullet.text):
        return False
    catalog = FactCatalog(profile)
    entries = catalog.valid(bullet.source_fact_ids, kind="experience")
    if not entries or any(not catalog.get(i) or catalog.get(i).kind != "experience"
                          for i in bullet.source_fact_ids):
        return False
    if len({e.owner_index for e in entries}) != 1:
        return False
    from app.services.content_quality import concepts
    claim = concepts(bullet.text)
    evidence = concepts(" ".join(e.text for e in entries))
    if not claim or len(claim & evidence) / len(claim) < 0.6:
        return False
    source = " ".join(e.text for e in entries).casefold()
    # Acronyms and profile technology names cannot migrate between citations.
    terms = {t for values in profile.skills.values() for t in values}
    terms.update(re.findall(r"\b[A-Z][A-Z0-9]{1,}\b", bullet.text))
    for term in terms:
        pattern = r"(?<!\w)" + re.escape(term) + r"(?!\w)"
        if re.search(pattern, bullet.text, re.I) and not re.search(pattern, source, re.I):
            return False
    return True


def check_export_content(resume):
    def texts(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                yield from texts(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                if key not in {"source_fact_ids", "summary_source_fact_ids", "selected_skill_ids", "selected_interest_ids", "skill_id"}:
                    yield from texts(item)
    if any(internal_annotation(text) for text in texts(resume.model_dump())):
        raise ValueError("Internal evidence annotation in CV content; export stopped.")
