import re

from bs4 import BeautifulSoup, Tag

from app.services.job_extractors.base import (
    BaseExtractor,
    ExtractionCandidate,
    cleaned_soup,
    first_text,
    normalized_text,
)

DESCRIPTION_HEADINGS = {"job description"}
DESCRIPTION_STOP_HEADINGS = {
    "co oferujemy",
    "co oferujemy?",
    "benefits",
    "why this one is worth a look",
    "office location",
    "about company",
}
TECH_STACK_HEADINGS = {"tech stack", "technologies"}
UI_LINES = {"apply", "save", "show more", "show less", "similar offers"}


class JustJoinExtractor(BaseExtractor):
    domains = ("justjoin.it",)
    prefer_over_jsonld = True

    def extract(self, html: str) -> ExtractionCandidate:
        soup = cleaned_soup(html)
        description_node = self._find_section(
            soup,
            ("[data-test-id='job-description']", "[data-test-id*='description']", "[class*='job-description']"),
            ("job description",),
        )
        tech_stack_node = self._find_section(
            soup,
            ("[data-test-id='tech-stack']", "[data-test-id*='tech-stack']"),
            ("tech stack",),
        )
        description = self._section_text(description_node, DESCRIPTION_HEADINGS, DESCRIPTION_STOP_HEADINGS)
        tech_stack = self._section_text(tech_stack_node, TECH_STACK_HEADINGS, set())
        seniority = first_text(soup, ("[data-test-id='experience-level']", "[data-test-id*='seniority']"))
        work_mode = first_text(soup, ("[data-test-id='workplace-type']", "[data-test-id*='work-mode']"))

        sections = []
        if seniority:
            sections.append(f"SENIORITY\n{seniority}")
        if work_mode:
            sections.append(f"WORK MODE\n{work_mode}")
        if description:
            sections.append(f"JOB DESCRIPTION\n{description}")
        if tech_stack:
            sections.append(f"TECH STACK\n{tech_stack}")

        return ExtractionCandidate(
            company=first_text(
                soup,
                ("[data-test-id='company-name']", "[data-test-id*='company']", "[class*='company'] a", "main h2"),
            ),
            role=first_text(soup, ("[data-test-id='offer-title']", "[data-test-id*='title']", "main h1", "h1")),
            job_description="\n\n".join(sections),
        )

    @staticmethod
    def _find_section(soup: BeautifulSoup, selectors: tuple[str, ...], headings: tuple[str, ...]) -> Tag | None:
        for selector in selectors:
            node = soup.select_one(selector)
            if isinstance(node, Tag):
                return node
        expected = {heading.casefold() for heading in headings}
        for heading in soup.find_all(re.compile(r"^h[1-6]$")):
            if normalized_text(heading).casefold().strip(" :") not in expected:
                continue
            sibling = heading.find_next_sibling()
            if isinstance(sibling, Tag):
                return sibling
            return heading.parent if isinstance(heading.parent, Tag) else None
        return None

    @staticmethod
    def _section_text(node: Tag | None, ignored_headings: set[str], stop_headings: set[str]) -> str:
        if node is None:
            return ""
        ignored = {value.casefold().strip(" :") for value in ignored_headings}
        lines = []
        for block in node.find_all(("h1", "h2", "h3", "h4", "h5", "h6", "p", "li")):
            if block.find(("h1", "h2", "h3", "h4", "h5", "h6", "p", "li")):
                continue
            line = re.sub(r"\s+", " ", block.get_text(" ", strip=True)).strip()
            folded = line.casefold().strip(" :")
            heading = re.sub(r"^[^\w]+", "", folded).strip(" :")
            if heading in stop_headings:
                break
            if not line or heading in ignored or heading in UI_LINES:
                continue
            if not lines or line != lines[-1]:
                lines.append(line)
        if not lines:
            return normalized_text(node)
        return "\n".join(lines)
