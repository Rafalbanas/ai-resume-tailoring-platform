import json
import re

from bs4 import BeautifulSoup, Tag

from app.services.job_extractors.base import (
    BaseExtractor,
    ExtractionCandidate,
    cleaned_soup,
    first_text,
    normalized_text,
)

SECTION_SPECS = (
    ("MUST HAVE", ("[commonpostingrequirements][branch='musts']",), ("must have", "mandatory")),
    ("NICE TO HAVE", ("[commonpostingrequirements][branch='nices']",), ("nice to have", "optional")),
    (
        "REQUIREMENTS",
        (),
        ("requirements description",),
    ),
    (
        "RESPONSIBILITIES",
        ("#posting-tasks", "[commonpostingtasks]"),
        ("your responsibilities", "your daily tasks on the job"),
    ),
    (
        "OFFER DESCRIPTION",
        ("#posting-description", "[commonpostingdescription][id*='project' i]"),
        ("offer description", "brief job description"),
    ),
)

UI_LINES = {
    "show all",
    "show less",
    "show more",
    "original text",
    "show translation",
    "technology image",
    "show on map",
}
STOP_MARKERS = ("what you get in return", "benefits", "job details", "offer valid until")


class NoFluffExtractor(BaseExtractor):
    domains = ("nofluffjobs.com",)
    prefer_over_jsonld = True

    def extract(self, html: str) -> ExtractionCandidate:
        soup = cleaned_soup(html)
        posting = self._server_posting(html)
        if posting:
            return self._extract_posting(posting, soup)
        sections = []
        for output_heading, selectors, heading_aliases in SECTION_SPECS:
            node = self._find_section(soup, selectors, heading_aliases)
            text = self._section_text(node, heading_aliases, stop_at_noise=output_heading == "OFFER DESCRIPTION")
            if text:
                sections.append(f"{output_heading}\n{text}")
        return ExtractionCandidate(
            company=first_text(
                soup,
                ("[data-cy='company-name']", "[class*='company-name']", "nfj-posting-header h2", "h1 + a"),
            ),
            role=first_text(soup, ("[data-cy='posting-title']", "nfj-posting-header h1", "main h1", "h1")),
            job_description="\n\n".join(sections),
        )

    def _extract_posting(self, posting: dict, soup: BeautifulSoup) -> ExtractionCandidate:
        requirements = posting.get("requirements") if isinstance(posting.get("requirements"), dict) else {}
        specs = posting.get("specs") if isinstance(posting.get("specs"), dict) else {}
        musts = self._tag_values(requirements.get("musts"))
        musts.extend(self._language_values(requirements.get("languages")))
        nices = self._tag_values(requirements.get("nices"))
        requirements_text = self._html_text(requirements.get("description"), stop_markers=("joining this project",))
        tasks = specs.get("dailyTasks") if isinstance(specs.get("dailyTasks"), list) else []
        responsibilities = "\n".join(str(value).strip() for value in tasks if str(value).strip())
        offer_node = self._find_section(soup, ("#posting-description",), ("offer description", "brief job description"))
        offer = self._section_text(
            offer_node,
            ("offer description", "brief job description"),
            stop_at_noise=True,
        )
        section_values = (
            ("MUST HAVE", "\n".join(musts)),
            ("NICE TO HAVE", "\n".join(nices)),
            ("REQUIREMENTS", requirements_text),
            ("RESPONSIBILITIES", responsibilities),
            ("OFFER DESCRIPTION", offer),
        )
        company = posting.get("company") if isinstance(posting.get("company"), dict) else {}
        return ExtractionCandidate(
            company=normalized_text(str(company.get("name") or "")),
            role=normalized_text(str(posting.get("title") or "")),
            job_description="\n\n".join(f"{heading}\n{text}" for heading, text in section_values if text),
        )

    @classmethod
    def _server_posting(cls, html: str) -> dict | None:
        soup = BeautifulSoup(html, "html.parser")
        script = soup.select_one("script#serverApp-state[type='application/json']")
        if not script:
            return None
        try:
            payload = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            return None
        return cls._find_posting(payload)

    @classmethod
    def _find_posting(cls, value: object) -> dict | None:
        if isinstance(value, dict):
            if (
                isinstance(value.get("requirements"), dict)
                and isinstance(value.get("specs"), dict)
                and isinstance(value.get("title"), str)
            ):
                return value
            for child in value.values():
                found = cls._find_posting(child)
                if found:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = cls._find_posting(child)
                if found:
                    return found
        return None

    @staticmethod
    def _tag_values(value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [
            normalized_text(str(item.get("value") or ""))
            for item in value
            if isinstance(item, dict) and item.get("value")
        ]

    @staticmethod
    def _language_values(value: object) -> list[str]:
        names = {"en": "English", "pl": "Polish", "de": "German", "fr": "French", "es": "Spanish"}
        if not isinstance(value, list):
            return []
        return [
            names.get(str(item.get("code", "")).casefold(), str(item.get("code", "")).upper())
            for item in value
            if isinstance(item, dict) and str(item.get("type", "")).upper() == "MUST" and item.get("code")
        ]

    @staticmethod
    def _html_text(value: object, stop_markers: tuple[str, ...] = ()) -> str:
        lines = []
        soup = BeautifulSoup(str(value or ""), "html.parser")
        values = NoFluffExtractor._block_texts(soup) or normalized_text(soup).splitlines()
        for line in values:
            folded = line.casefold()
            if any(folded.startswith(marker) for marker in stop_markers):
                break
            if line and (not lines or line != lines[-1]):
                lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _find_section(soup: BeautifulSoup, selectors: tuple[str, ...], heading_aliases: tuple[str, ...]) -> Tag | None:
        for selector in selectors:
            node = soup.select_one(selector)
            if isinstance(node, Tag):
                return node
        aliases = {value.casefold() for value in heading_aliases}
        for heading in soup.find_all(re.compile(r"^h[1-6]$")):
            if normalized_text(heading).casefold() in aliases:
                parent = heading.find_parent(["section", "article"])
                return parent or heading.parent
        return None

    @staticmethod
    def _section_text(node: Tag | None, heading_aliases: tuple[str, ...], stop_at_noise: bool) -> str:
        if node is None:
            return ""
        if stop_at_noise:
            markup = str(node)
            folded_markup = markup.casefold()
            positions = [folded_markup.find(marker) for marker in STOP_MARKERS if folded_markup.find(marker) >= 0]
            if positions:
                node = BeautifulSoup(markup[: min(positions)], "html.parser")
        heading_values = {value.casefold() for value in heading_aliases}
        lines = []
        values = NoFluffExtractor._block_texts(node) or normalized_text(node).splitlines()
        for raw_line in values:
            line = re.sub(r"\s+", " ", raw_line).strip()
            folded = line.casefold().strip(" :")
            if not line or folded in heading_values or folded in UI_LINES:
                continue
            if stop_at_noise and any(folded.startswith(marker) for marker in STOP_MARKERS):
                break
            if line.casefold().startswith("image: technology image"):
                continue
            if not lines or line != lines[-1]:
                lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _block_texts(node: BeautifulSoup | Tag) -> list[str]:
        block_names = ("h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "div")
        values = []
        for block in node.find_all(block_names):
            if block.find(block_names):
                continue
            text = re.sub(r"\s+", " ", block.get_text(" ", strip=True)).strip()
            text = re.sub(r"\s+([,.;:!?])", r"\1", text)
            if text and (not values or text != values[-1]):
                values.append(text)
        return values
