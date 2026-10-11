import json
from collections.abc import Iterator

from bs4 import BeautifulSoup

from app.services.job_extractors.base import BaseExtractor, ExtractionCandidate, normalized_text


def _objects(value: object) -> Iterator[dict]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from _objects(child)


def _is_job_posting(item: dict) -> bool:
    item_type = item.get("@type")
    types = item_type if isinstance(item_type, list) else [item_type]
    return any(str(value).lower() == "jobposting" for value in types)


class JsonLdExtractor(BaseExtractor):
    def extract(self, html: str) -> ExtractionCandidate:
        soup = BeautifulSoup(html, "html.parser")
        candidates = []
        for script in soup.find_all("script", attrs={"type": lambda value: value and "ld+json" in value.lower()}):
            try:
                payload = json.loads(script.string or script.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            for item in _objects(payload):
                if not _is_job_posting(item):
                    continue
                organization = item.get("hiringOrganization")
                company = organization.get("name", "") if isinstance(organization, dict) else ""
                candidates.append(ExtractionCandidate(
                    company=normalized_text(str(company or "")),
                    role=normalized_text(str(item.get("title") or "")),
                    job_description=normalized_text(str(item.get("description") or "")),
                ))
        unique = {(c.company, c.role, c.job_description): c for c in candidates}
        if len(unique) > 1:
            return ExtractionCandidate(ambiguous=True)
        return next(iter(unique.values()), ExtractionCandidate())
