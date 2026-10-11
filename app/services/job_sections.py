"""Source sections and auditable requirement units; never infer facts about a candidate."""
import re
from dataclasses import dataclass, field


@dataclass
class SourceUnit:
    name: str
    quote: str
    category: str
    basis: str
    section: str
    group: str
    supporting_quotes: list[str] = field(default_factory=list)
    level: str = ""


PREFERRED = re.compile(r'^(?:preference will be given.*|preferred(?: qualifications| requirements| skills)?|nice.to.have|optional(?: requirements)?|desirable(?: skills| qualifications)?|mile widziane)\s*:?$', re.I)
MANDATORY = re.compile(r'^(?:(?:basic|essential|minimum|key|skills?\s*&|technical|candidate)\s+)*(?:requirements|qualifications)|^(?:what you bring|your profile|we are looking for|must have|wymagania.*|nasze oczekiwania|you bring)\s*:?$', re.I)
DUTY = re.compile(r'^(?:responsibilities|key responsibilities|duties|what you.ll do|your responsibilities|job responsibilities)\s*:?$', re.I)
ORG = re.compile(r'^(?:company overview|department overview|about (?:us|the company|the team)|who we are|job description)\s*:?$', re.I)
STACK = re.compile(r"^(?:tech stack|skills used|technologies used)\s*:?$", re.I)
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
        elif STACK.fullmatch(line):
            category = 'competency'
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
            if re.match(r'develop yourself\b', line, re.I):
                category = 'organization'
            if category == 'competency' and re.fullmatch(r'regular|basic|intermediate|advanced|expert|junior|senior|B[12]|C[12]', line, re.I) and units and units[-1].category == 'competency':
                units[-1].level = line
                units[-1].supporting_quotes.append(line)
                continue
            unit_category = category
            if category == 'mandatory' and re.search(r'^(?:preferred|preferably|nice.to.have)|(?:is a plus|considered an asset)\b', line, re.I):
                unit_category = 'preferred'
            group = f'source_{len(units) + 1}'
            pieces = [line]
            # Independent evidence: CRM and KCS must not be confirmed as one skill.
            if re.search(r'\bCRM\b', line, re.I) and re.search(r'\bKCS\b', line, re.I) and re.search(r'\band\b', line, re.I):
                pieces = re.split(r'\s+and\s+(?=working|knowledge|experience|KCS)', line, maxsplit=1, flags=re.I)
            elif 'Fluency' in line or re.search(r'\bfluent\b|would be a plus|is a plus', line, re.I):
                pieces = re.split(r'(?<=[.!?])\s+(?=[A-Z])', line)
            for piece in pieces:
                piece_category = 'preferred' if unit_category == 'mandatory' and re.search(r'would be a plus|is a plus|considered an asset', piece, re.I) else unit_category
                basis = (f'{piece_category.title()} section: {section}' if piece_category == category else 'Explicit preference in source text')
                if unit_category == 'mandatory' and re.search(r',\s*preferably\b', piece, re.I):
                    basis += '; the preferably clause is optional'
                units.append(SourceUnit(piece, line, piece_category,
                                        basis,
                                        section, group))
            continue
        section = heading
        recognized.append(section)
    return units, list(dict.fromkeys(recognized))


def semantic_key(name: str) -> tuple[str, ...]:
    """Conservative equivalence: retain product, action, level and tenure conditions."""
    text = name.casefold()
    for pattern, replacement in (
        (r"\bcustomer service\b", "customer support"),
        (r"\bproblem solving\b", "troubleshooting"),
        (r"\bincident management\b", "incident handling"),
        (r"\bcrm systems?\b", "crm"),
        (r"\bknowledge of\b|\bfamiliarity with\b", "knowledge"),
        (r"\bexperience (?:with|in|using)\b", "experience"),
    ):
        text = re.sub(pattern, replacement, text)
    return tuple(sorted(set(re.findall(r"[a-z0-9+#]+", text)) - {"a", "an", "the", "of", "with", "in", "is", "required", "must", "have"}))


def role_competency_units(units: list[SourceUnit]) -> list[SourceUnit]:
    """List skills plus literal named tools in duties; never infer prerequisites.

    Repeated long/short product references share one competency. Configuration
    and other actions stay in the separately preserved responsibility quotes.
    """
    candidates = [u for u in units if u.category == 'competency']
    for unit in units:
        if unit.category != 'responsibility':
            continue
        # Capitalized tool names following use/operation context. A version or
        # product number ends the family name; retain the full duty as evidence.
        for match in re.finditer(r'\b(?:using|within|with|on|via)\s+((?:[A-Z][A-Za-z+#-]*\s+){0,3}[A-Z][A-Za-z+#-]*(?:\s+\d+(?:\.\d+)*)?)', unit.name):
            name = match.group(1).strip()
            candidates.append(SourceUnit(name, unit.quote, 'competency',
                'Named product used in a responsibility; prior experience and level unspecified', unit.section, unit.group))
    merged = []
    for unit in candidates:
        equivalent = next((u for u in merged if semantic_key(u.name) == semantic_key(unit.name)
                           or u.name.casefold().endswith(' ' + unit.name.casefold())
                           or unit.name.casefold().endswith(' ' + u.name.casefold())), None)
        if equivalent is None:
            merged.append(unit)
        elif unit.quote not in [equivalent.quote, *equivalent.supporting_quotes]:
            equivalent.supporting_quotes.append(unit.quote)
    return merged
