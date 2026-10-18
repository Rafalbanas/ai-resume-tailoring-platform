"""Clean copied offers without fetching a URL or inventing missing details."""

import re

from app.services.job_extractors.base import ExtractionCandidate
from app.services.job_extractors.eldorado import EldoradoExtractor
from app.services.job_extractors.pracuj import HEADINGS, PracujExtractor, _line
from app.services.job_extractors.theprotocol import TheProtocolExtractor
from app.services.job_sections import CONTEXT_HEADINGS, DUTY, MANDATORY, NEEDED, ORG, PREFERRED, STACK

NOISE = {
    "apply", "apply now", "save", "save job", "share", "share this job", "sign in", "log in",
    "register", "menu", "search jobs", "accept all cookies", "reject all cookies", "manage cookies",
    "cookie policy", "privacy policy", "terms of use", "show more", "show less",
    "aplikuj", "aplikuj teraz", "zapisz", "zapisz ofertę", "udostępnij", "zaloguj się",
    "zarejestruj się", "szukaj ofert", "akceptuj wszystkie", "odrzuć wszystkie",
    "polityka prywatności", "pokaż więcej", "pokaż mniej",
}
PAGE_END = {
    "similar jobs", "related jobs", "recommended jobs", "other jobs", "you may also like",
    "podobne oferty", "podobne oferty pracy", "inne oferty pracy", "polecane oferty",
}
SECTION_PATTERNS = (
    (PREFERRED, "NICE TO HAVE"),
    (MANDATORY, "REQUIREMENTS"),
    (NEEDED, "REQUIREMENTS"),
    (DUTY, "RESPONSIBILITIES"),
    (ORG, "OFFER DESCRIPTION"),
    (STACK, "PORTAL TECHNOLOGY TAGS"),
    (CONTEXT_HEADINGS["employment"], "EMPLOYMENT CONDITIONS"),
)


def clean_generic_text(text: str) -> ExtractionCandidate:
    lines: list[str] = []
    skipping = False
    company = role = ""
    for raw in text.splitlines():
        line = _line(raw.replace("\u200b", "").replace("\ufeff", ""))
        if not line:
            continue
        folded = line.casefold().rstrip(":").strip()
        if folded in PAGE_END:
            break
        if folded in NOISE:
            continue
        # Keep explicit metadata; do not guess names from navigation or prose.
        metadata = re.fullmatch(r"(company|employer|firma|pracodawca|role|job title|stanowisko):\s*(.+)", line, re.I)
        if metadata:
            if metadata[1].casefold() in {"company", "employer", "firma", "pracodawca"}:
                company = company or metadata[2]
            else:
                role = role or metadata[2]
        heading = next((name for pattern, name in SECTION_PATTERNS if pattern.fullmatch(folded)), None)
        if not heading and folded in HEADINGS:
            heading = HEADINGS[folded]
        if heading:
            skipping = False
            line = heading
        elif (
            (folded in HEADINGS and HEADINGS[folded] is None)
            or CONTEXT_HEADINGS["benefits"].fullmatch(folded)
            or CONTEXT_HEADINGS["recruitment"].fullmatch(folded)
        ):
            skipping = True
            continue
        if not skipping and (not lines or lines[-1] != line):
            lines.append(line)
    return ExtractionCandidate(company=company, role=role, job_description="\n".join(lines))


def clean_pasted_offer(text: str, url: str = "") -> ExtractionCandidate:
    theprotocol = TheProtocolExtractor()
    if theprotocol.matches(url) or theprotocol.recognizes_text(text):
        return theprotocol.extract_text(text)
    eldorado = EldoradoExtractor()
    folded = text.casefold()
    if eldorado.matches(url) or any(marker in folded for marker in (
        "tech stack / keywords", "firma i stanowisko", "czyjesteldorado",
    )):
        candidate = eldorado.extract_text(text)
        if candidate.usable:
            return candidate
    pracuj = PracujExtractor()
    if pracuj.matches(url) or "o firmie" in folded:
        candidate = pracuj.extract_text(text)
        if candidate.usable:
            return candidate
    return clean_generic_text(text)
