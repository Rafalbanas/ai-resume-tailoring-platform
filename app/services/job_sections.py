"""Source sections and auditable requirement units; never infer facts about a candidate."""
import re
from dataclasses import dataclass


@dataclass
class SourceUnit:
    name: str
    quote: str
    category: str
    basis: str
    section: str
    group: str


PREFERRED = re.compile(r'^(?:preference will be given.*|preferred(?: qualifications| requirements| skills)?|nice.to.have|optional(?: requirements)?|desirable(?: skills| qualifications)?|mile widziane)\s*:?$', re.I)
MANDATORY = re.compile(r'^(?:(?:basic|essential|minimum|key|skills?\s*&|technical|candidate)\s+)*(?:requirements|qualifications)|^(?:what you bring|your profile|we are looking for|must have|wymagania.*|nasze oczekiwania|you bring)\s*:?$', re.I)
DUTY = re.compile(r'^(?:responsibilities|key responsibilities|duties|what you.ll do|your responsibilities|job responsibilities)\s*:?$', re.I)
ORG = re.compile(r'^(?:company overview|department overview|about (?:us|the company|the team)|who we are|job description)\s*:?$', re.I)
END = re.compile(r'^(?:benefits|we offer|what we offer|tech stack|travel requirements|relocation provided|position type|referral payment plan|company|eeo statement|equal opportunity.*)\s*:?$', re.I)
REQUIREMENT_SIGNAL = re.compile(r'\b(?:must|required|requires|experience|knowledge|proficiency|fluen\w*|degree|certification|ability|familiarity)\b', re.I)
ORGANIZATION_SIGNAL = re.compile(r'\b(?:global leader|our (?:company|team|division)|we (?:believe|build|offer)|join (?:our|a) team)\b', re.I)


def extract_sections(text: str) -> tuple[list[SourceUnit], list[str]]:
    units, section, category, recognized = [], '', None, []
    for raw in text.splitlines():
        line = raw.strip().strip('•*- ').strip()
        if not line:
            continue
        heading = line.rstrip(':').strip()
        if PREFERRED.fullmatch(line):
            category = 'preferred'
        elif MANDATORY.fullmatch(heading):
            category = 'mandatory'
        elif DUTY.fullmatch(line):
            category = 'responsibility'
        elif ORG.fullmatch(line):
            category = 'organization'
        elif END.fullmatch(line):
            category = None
            section = heading
            continue
        else:
            if category is None:
                continue
            # An introductory category has no independently assessable condition.
            if line.endswith(':') and re.search(r'(?:following|knowledge with|skills and experience)', line, re.I):
                continue
            unit_category = category
            if category == 'mandatory' and re.search(r'^(?:preferred|preferably|nice.to.have)|(?:is a plus|considered an asset)\b', line, re.I):
                unit_category = 'preferred'
            group = f'source_{len(units) + 1}'
            pieces = [line]
            # Independent evidence: CRM and KCS must not be confirmed as one skill.
            if re.search(r'\bCRM\b', line, re.I) and re.search(r'\bKCS\b', line, re.I) and re.search(r'\band\b', line, re.I):
                pieces = re.split(r'\s+and\s+(?=working|knowledge|experience|KCS)', line, maxsplit=1, flags=re.I)
            elif 'Fluency' in line or re.search(r'\bfluent\b', line, re.I):
                pieces = re.split(r'(?<=[.!?])\s+(?=[A-Z])', line)
            for piece in pieces:
                basis = (f'{unit_category.title()} section: {section}' if unit_category == category else 'Explicit preference in source text')
                if unit_category == 'mandatory' and re.search(r',\s*preferably\b', piece, re.I):
                    basis += '; the preferably clause is optional'
                units.append(SourceUnit(piece, line, unit_category,
                                        basis,
                                        section, group))
            continue
        section = heading
        recognized.append(section)
    return units, list(dict.fromkeys(recognized))
