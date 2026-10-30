"""Preserve user restrictions on publishing individual employment facts.

Analysis still sees all facts; these conditions control CV presentation only.
"""

import re

from app.services.fact_catalog import FactCatalog


def cv_catalog(profile, job):
    catalog = FactCatalog(profile)
    posting = f"{job.role}\n{job.relevance_text}"

    def allowed(entry):
        if entry.kind != "experience" or entry.owner_index is None:
            return True
        terms = profile.experience[entry.owner_index].cv_fact_conditions.get(entry.text)
        return terms is None or any(
            term.strip() and re.search(r"(?<!\w)" + re.escape(term.strip()) + r"(?!\w)", posting, re.I)
            for term in terms
        )

    catalog.prompt_entries = [e for e in catalog.prompt_entries if allowed(e)]
    ids = {e.source_id for e in catalog.prompt_entries}
    catalog.entries = {key: entry for key, entry in catalog.entries.items() if entry.source_id in ids}
    return catalog
