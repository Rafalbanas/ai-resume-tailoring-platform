import re

from app.services.job_extractors.base import (
    BaseExtractor,
    ExtractionCandidate,
    cleaned_soup,
    first_text,
    normalized_text,
)

HEADINGS = {
    'technologie, których używamy': 'PORTAL TECHNOLOGY TAGS',
    'wymagane': 'PORTAL TECHNOLOGY TAGS',
    'system operacyjny': 'PORTAL TECHNOLOGY TAGS',
    'o projekcie': 'OFFER DESCRIPTION',
    'twój zakres obowiązków': 'RESPONSIBILITIES',
    'twoje zadania': 'RESPONSIBILITIES',
    'nasze wymagania': 'REQUIREMENTS',
    'wymagania': 'REQUIREMENTS',
    'mile widziane': 'NICE TO HAVE',
    'to oferujemy': None,
    'benefity': None,
    'etapy rekrutacji': None,
    'tak się u nas pracuje': None,
    'siedziba firmy': None,
    'technologies we use': 'PORTAL TECHNOLOGY TAGS',
    'expected': 'PORTAL TECHNOLOGY TAGS',
    'operating system': 'PORTAL TECHNOLOGY TAGS',
    'about the project': 'OFFER DESCRIPTION',
    'your responsibilities': 'RESPONSIBILITIES',
    'our requirements': 'REQUIREMENTS',
    'optional': 'NICE TO HAVE',
    'what we offer': None,
    'benefits': None,
    'recruitment stages': None,
    'this is how we organize our work': None,
    'this is how we work': None,
    '__cvtailor_section_end__': None,
}
EMPLOYMENT = re.compile(r'\b(?:umowa o pracę|kontrakt|b2b|pełny etat|część etatu|praca (?:stacjonarna|hybrydowa|zdalna)|mid\s*/\s*regular|junior|senior|śląskie|mazowieckie|małopolskie|wielkopolskie|pomorskie|dolnośląskie|łódzkie|podkarpackie|lubelskie|lubuskie|opolskie|podlaskie|świętokrzyskie|warmińsko.mazurskie|zachodniopomorskie|kujawsko.pomorskie)\b', re.I)
UI = {'pokaż więcej', 'pokaż mniej', 'zobacz', 'sprawdź', 'aplikuj', 'zapisz', 'o firmie', 'wymagane', 'system operacyjny'}
COMPANY_LABEL = r'o firmie|about the company'


def _line(value):
    value = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', value)
    value = re.sub(r'^\s*(?:#{1,6}\s+|[-*•]\s+)', '', value)
    return re.sub(r'\s+', ' ', value.rstrip('\\').strip()).strip()


class PracujExtractor(BaseExtractor):
    domains = ('pracuj.pl',)
    headings = HEADINGS
    employment_pattern = EMPLOYMENT
    prefer_over_jsonld = True
    # Unknown/blocked Pracuj pages must not fall through to a noisy whole-page import.
    allow_generic_fallback = False

    def extract_text(self, text: str) -> ExtractionCandidate:
        lines = [line for raw in text.splitlines() if (line := _line(raw))]
        sections = {}
        active = None
        started = False
        prelude = []
        for line in lines:
            heading = line.casefold().rstrip(':')
            if heading in self.headings:
                active = self.headings[heading]
                if heading != '__cvtailor_section_end__':
                    started = True
                continue
            if not started:
                prelude.append(line)
            if active and heading not in UI:
                section = sections.setdefault(active, [])
                if line not in section:
                    section.append(line)
        employment = [line for line in prelude if len(line) < 250
                      and not re.search(r'\.(?:pdf|docx?)\b|domyślne cv|dopasowanie cv', line, re.I)
                      and (self.employment_pattern.search(line) or line.casefold().endswith('śląskie'))]
        if employment:
            sections['EMPLOYMENT CONDITIONS'] = list(dict.fromkeys(employment))
        company = role = ''
        for index, line in enumerate(prelude):
            if re.search(COMPANY_LABEL, line, re.I):
                company = re.split(COMPANY_LABEL, line, flags=re.I)[0].strip()
                if not company and index:
                    company = prelude[index - 1]
                    role = prelude[index - 2] if index > 1 else ''
                elif company and index:
                    role = prelude[index - 1]
                break
        order = ('EMPLOYMENT CONDITIONS', 'PORTAL TECHNOLOGY TAGS', 'OFFER DESCRIPTION',
                 'RESPONSIBILITIES', 'REQUIREMENTS', 'NICE TO HAVE')
        description = '\n\n'.join(f'{heading}\n' + '\n'.join(sections[heading]) for heading in order if sections.get(heading))
        if not any(sections.get(key) for key in ('OFFER DESCRIPTION', 'RESPONSIBILITIES', 'REQUIREMENTS', 'NICE TO HAVE')):
            description = ''
        return ExtractionCandidate(company=company, role=role, job_description=description)

    def extract(self, html: str) -> ExtractionCandidate:
        soup = cleaned_soup(html)
        role = first_text(soup, ("[data-test='text-positionName']", 'main h1', 'h1'))
        company = first_text(soup, ("[data-test='text-employerName']", "[data-test='link-employer']"))
        if not company:
            title = soup.find('h1')
            next_heading = title.find_next('h2') if title else None
            if next_heading and next_heading.get_text(' ', strip=True).casefold() not in self.headings:
                company = next_heading.get_text(' ', strip=True)
        # Flatten complete blocks, preserving inline links/product names in one
        # sentence. Unknown section headings terminate the current offer section.
        for node in list(soup.select('h1,h2,h3,h4,p,li')):
            if node.decomposed or node.find_parent(['p','li']):
                continue
            text = node.get_text(' ', strip=True)
            if node.name != 'h1' and node.name.startswith('h') and text.casefold().rstrip(':') not in self.headings:
                text = '__cvtailor_section_end__'
            node.replace_with('\n' + text + '\n')
        candidate = self.extract_text(normalized_text(soup))
        candidate.company = re.split(COMPANY_LABEL, company or candidate.company, flags=re.I)[0].strip()
        candidate.role = role or candidate.role
        return candidate
