import re
from dataclasses import dataclass
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag


@dataclass(slots=True)
class ExtractionCandidate:
    company: str = ""
    role: str = ""
    job_description: str = ""

    @property
    def usable(self) -> bool:
        return len(self.job_description) >= 80


class BaseExtractor:
    domains: tuple[str, ...] = ()
    prefer_over_jsonld = False

    def matches(self, url: str) -> bool:
        hostname = (urlparse(url).hostname or "").lower().rstrip(".")
        return any(hostname == domain or hostname.endswith(f".{domain}") for domain in self.domains)

    def extract(self, html: str) -> ExtractionCandidate:
        raise NotImplementedError


NOISE_TERMS = (
    "cookie",
    "consent",
    "navigation",
    "navbar",
    "footer",
    "related-job",
    "similar-job",
    "recommended-job",
    "newsletter",
    "social-share",
    "marketing",
    "advertisement",
)


def normalized_text(value: str | Tag | None) -> str:
    if value is None:
        return ""
    raw = (
        value.get_text("\n", strip=True)
        if isinstance(value, Tag)
        else BeautifulSoup(value, "html.parser").get_text("\n")
    )
    lines: list[str] = []
    for line in raw.splitlines():
        clean = re.sub(r"\s+", " ", line).strip()
        if clean and (not lines or clean != lines[-1]):
            lines.append(clean)
    return "\n".join(lines).strip()


def cleaned_soup(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    for node in soup.select("script, style, noscript, nav, footer, aside, form, svg, canvas, button"):
        node.decompose()
    for node in list(soup.find_all(True)):
        marker = " ".join([str(node.get("id", "")), *(str(item) for item in node.get("class", []))]).lower()
        if any(term in marker for term in NOISE_TERMS):
            node.decompose()
    cookie_phrases = ("accept all cookies", "manage cookies", "cookie policy", "ustawienia plików cookie")
    for text_node in list(soup.find_all(string=True)):
        text = re.sub(r"\s+", " ", str(text_node)).strip().lower()
        if text and len(text) <= 500 and any(phrase in text for phrase in cookie_phrases):
            parent = text_node.parent
            if parent and parent.name not in {"main", "article", "body", "html"}:
                parent.decompose()
    return soup


def first_text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        text = normalized_text(node)
        if text:
            return text
    return ""


def longest_text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str:
    values = (normalized_text(node) for selector in selectors for node in soup.select(selector))
    return max(values, key=len, default="")
