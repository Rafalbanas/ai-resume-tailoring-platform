"""Extract The Protocol offers without treating page controls as job content."""

import re

from app.services.job_extractors.base import ExtractionCandidate
from app.services.job_extractors.pracuj import EMPLOYMENT, HEADINGS, PracujExtractor, _line


class TheProtocolExtractor(PracujExtractor):
    domains = ('theprotocol.it',)
    headings = {
        **HEADINGS,
        # This portal explicitly assigns priority to technology tags.
        'wymagania': None,
        'technologie wymagane': 'REQUIREMENTS',
        'technologie mile widziane': 'NICE TO HAVE',
        'required technologies': 'REQUIREMENTS',
        'optional technologies': 'NICE TO HAVE',
        'tak organizujemy naszą pracę': None,
        'tak pracujemy': None,
        'company': None,
    }
    employment_pattern = re.compile(
        EMPLOYMENT.pattern + r'|\b(?:hybrydowa|stacjonarna|zdalna)\b', re.I,
    )
    page_end = {'podsumowanie oferty', 'zgłaszam się do', 'brakuje ci informacji?', 'podobne oferty'}

    @staticmethod
    def recognizes_text(text: str) -> bool:
        lines = {_line(raw).casefold().rstrip(':') for raw in text.splitlines()}
        return 'technologie wymagane' in lines and 'technologie mile widziane' in lines

    def extract_text(self, text: str) -> ExtractionCandidate:
        lines = [line for raw in text.splitlines() if (line := _line(raw))]
        cleaned = []
        started = False
        for line in lines:
            heading = line.casefold().rstrip(':')
            if started and heading in self.page_end:
                break
            if heading in self.headings and self.headings[heading]:
                started = True
            # Copied pages put the label and value on separate lines.
            if cleaned and cleaned[-1].casefold().rstrip(':') in {'poziom', 'tryb pracy'}:
                cleaned[-1] += ' ' + line
            else:
                cleaned.append(line)
        candidate = super().extract_text('\n'.join(cleaned))
        for index, line in enumerate(cleaned):
            if line.casefold().rstrip(':') in self.headings:
                break
            company = re.fullmatch(r'(?:firma|company):\s*(.+)', line, re.I)
            if company:
                candidate.company = company[1].strip()
                if index:
                    candidate.role = cleaned[index - 1]
                break
        return candidate

    def extract(self, html: str) -> ExtractionCandidate:
        candidate = super().extract(html)
        candidate.company = re.sub(r'^(?:firma|company):\s*', '', candidate.company, flags=re.I)
        return candidate
