import re

from bs4 import BeautifulSoup, Tag

from app.services.job_extractors.base import BaseExtractor, ExtractionCandidate, cleaned_soup, first_text

ALLOWED_SECTIONS = {
    "department overview": "DEPARTMENT OVERVIEW",
    "job description": "JOB DESCRIPTION",
    "what you’ll be doing / responsibilities": "RESPONSIBILITIES",
    "what you'll be doing / responsibilities": "RESPONSIBILITIES",
    "what you’ll be doing": "RESPONSIBILITIES",
    "what you'll be doing": "RESPONSIBILITIES",
    "responsibilities": "RESPONSIBILITIES",
    "basic requirements": "BASIC REQUIREMENTS",
    "what you need to succeed": "WHAT YOU NEED TO SUCCEED",
    "bonus points if you have": "BONUS POINTS IF YOU HAVE",
    "preferred requirements": "PREFERRED REQUIREMENTS",
}
EXCLUDED_SECTIONS = {
    "company overview",
    "benefits",
    "what we offer",
    "travel requirements",
    "relocation provided",
    "position type",
    "referral payment plan",
    "eeo statement",
    "equal employment opportunity statement",
}


class WorkdayExtractor(BaseExtractor):
    domains = ("myworkdayjobs.com", "workday.com")
    prefer_over_jsonld = True

    def extract(self, html: str) -> ExtractionCandidate:
        soup = cleaned_soup(html)
        description_node = soup.select_one(
            "[data-automation-id='jobPostingDescription'], [data-automation-id='job-posting-details']"
        )
        description = self._preferred_sections(description_node)
        location = first_text(soup, ("[data-automation-id='locations']", "[data-automation-id='location']"))
        requisition = first_text(
            soup,
            ("[data-automation-id='jobPostingId']", "[data-automation-id='requisitionNumber']"),
        )
        metadata = []
        if location:
            metadata.append(f"LOCATION\n{location}")
        if requisition:
            metadata.append(f"REQUISITION\n{requisition}")
        if description:
            metadata.append(description)

        return ExtractionCandidate(
            company=first_text(
                soup,
                ("[data-automation-id='company']", "[data-automation-id='jobPostingCompany']"),
            )
            or self._meta_content(soup, "meta[property='og:site_name']"),
            role=first_text(
                soup, ("[data-automation-id='jobPostingHeader']", "[data-automation-id='jobPostingTitle']", "h1")
            ),
            job_description="\n\n".join(metadata),
        )

    @staticmethod
    def _preferred_sections(node: Tag | None) -> str:
        if node is None:
            return ""
        sections: list[tuple[str, list[str]]] = []
        current: list[str] | None = None
        for block in node.find_all(("h1", "h2", "h3", "h4", "h5", "h6", "p", "li")):
            if block.find(("h1", "h2", "h3", "h4", "h5", "h6", "p", "li")):
                continue
            line = re.sub(r"\s+", " ", block.get_text(" ", strip=True)).strip()
            folded = line.casefold().strip(" :")
            if folded in ALLOWED_SECTIONS:
                current = []
                sections.append((ALLOWED_SECTIONS[folded], current))
                continue
            if folded in EXCLUDED_SECTIONS:
                current = None
                continue
            if line and current is not None and (not current or line != current[-1]):
                current.append(line)
        return "\n\n".join(f"{heading}\n{'\n'.join(lines)}" for heading, lines in sections if lines)

    @staticmethod
    def _meta_content(soup: BeautifulSoup, selector: str) -> str:
        node = soup.select_one(selector)
        return str(node.get("content", "")).strip() if isinstance(node, Tag) else ""
