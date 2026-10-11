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
    operator: str = "single"
    alternatives: list[str] = field(default_factory=list)
    accepted_alternatives: list[str] = field(default_factory=list)
    uncertain: bool = False


PREFERRED = re.compile(r'^(?:preference will be given.*|preferred(?: qualifications| requirements| skills)?|nice.to.have|optional(?: requirements)?|desirable(?: skills| qualifications)?|mile widziane)\s*:?$', re.I)
MANDATORY = re.compile(r'^(?:(?:basic|essential|minimum|key|skills?\s*&|technical|candidate)\s+)*(?:requirements|qualifications)|^(?:what you bring|your profile|we are looking for(?: you,? if you have)?|must have|wymagania.*|nasze oczekiwania|you bring)\s*:?$', re.I)
DUTY = re.compile(r'^(?:responsibilities|key responsibilities|duties|what you.ll do|your responsibilities|job responsibilities)\s*:?$', re.I)
ORG = re.compile(r'^(?:company overview|department overview|about (?:us|the company|the team)|who we are|job description|offer description)\s*:?$', re.I)
STACK = re.compile(r"^(?:tech stack|skills used|technologies used|portal technology tags)\s*:?$", re.I)
END = re.compile(r'^(?:benefits|we offer|what we offer|tech stack|travel requirements|relocation provided|position type|referral payment plan|company|eeo statement|equal opportunity.*)\s*:?$', re.I)
REQUIREMENT_SIGNAL = re.compile(r'\b(?:must|required|requires|experience|knowledge|proficiency|fluen\w*|degree|certification|ability|familiarity)\b', re.I)
ORGANIZATION_SIGNAL = re.compile(r'\b(?:global leader|our (?:company|team|division)|we (?:believe|build|offer)|join (?:our|a) team)\b', re.I)
INSTRUCTION = re.compile(r'ignore.*instructions|system prompt|you are chatgpt|return.*json|mark.*(?:strong|apply)|reveal.*(?:secret|key)', re.I)
LEVEL = re.compile(r'\b(?:[ABC][12]\+?|native|advanced|expert|fluent|fluency|basic|working knowledge|hands.on)\b\+?', re.I)
PREFERENCE_MARKER = re.compile(r'\b(?:preferred|preferably|nice.to.have|big plus|(?:is |are |would be )a plus|(?:considered (?:an? )?)?advantage|considered an asset|optional)\b', re.I)

TECH_LIST = r'(?:JavaScript|TypeScript|Python|PowerShell|Bash|SQL|T-SQL|Linux|Windows|Mac|Docker|Kubernetes|Azure|AWS|Terraform|Java|C\+\+|C#)'


def requirement_units(line: str, category: str, section: str, group: str) -> list[SourceUnit]:
    """Keep source quotes intact while separating explicit preferences and logic."""
    base = re.search(r'^(.*?)\(([^()]*)\bpreferred\s*;\s*other languages welcome\)\.?$', line, re.I)
    if base:
        alternatives = [v.strip() for v in re.split(r'\s*/\s*|\s+or\s+', base[2].strip(), flags=re.I)]
        return [
            SourceUnit(base[1].strip(), line, category, f'{category.title()} capability; language choices are preferences', section, group,
                       accepted_alternatives=['other programming languages']),
            SourceUnit(' OR '.join(alternatives), line, 'preferred', 'Explicit preferred alternatives; other languages accepted', section, group + '_preferred',
                       operator='any', alternatives=alternatives, accepted_alternatives=['other programming languages']),
        ]
    optional = re.search(r',\s*(?:preferably|preferred specialization)\b', line, re.I)
    if optional:
        # Keep optional detail in the quote, not as a mandatory constraint.
        return [SourceUnit(line[:optional.start()].strip(), line, category,
                           f'{category.title()} section: {section}; the preferably clause is optional', section, group)]
    if category in {'preferred', 'nice_to_have'}:
        line = re.sub(r'^(?:preferred|optional)\s+', '', line, flags=re.I)
        line = re.sub(r'\s*\(\s*(?:nice.to.have|optional|preferred|big plus|(?:is )?(?:considered (?:an? )?)?advantage)\s*\)\s*[.;]?$', '', line, flags=re.I)
        line = re.sub(r'\s*(?:nice.to.have|optional|preferred|big plus|(?:is |are |would be )a plus|(?:is )?(?:considered (?:an? )?)?advantage|considered an asset)\s*[.;]?$', '', line, flags=re.I).strip(' .;')
    prefix = r'(?:(?:experience|knowledge|working knowledge)\s+(?:with|in|of)\s+)?'
    pure_and = re.fullmatch(rf'({prefix})({TECH_LIST})\s+and\s+({TECH_LIST}|[A-Za-z][A-Za-z0-9+#-]*)[.]?', line, re.I)
    if pure_and:
        return [SourceUnit(pure_and[1] + value, line, category, 'Explicit AND: every condition must be met', section, group,
                           operator='all') for value in (pure_and[2], pure_and[3])]
    unit = SourceUnit(line, line, category, f'{category.title()} section: {section}', section, group)
    pure_or = re.fullmatch(rf'({prefix})((?:{TECH_LIST},?\s+)*(?:{TECH_LIST}))\s+(?:or|and/or)\s+({TECH_LIST})[.]?', line, re.I)
    if pure_or:
        values = re.split(r',\s*', pure_or[2]) + [pure_or[3]]
        unit.operator, unit.alternatives = 'any', [pure_or[1] + v for v in values]
        unit.basis = 'Explicit OR: one suitably qualified alternative suffices'
    elif shared := re.fullmatch(rf'(.*?)({TECH_LIST})\s+(or|and/or|and)\s+({TECH_LIST})(.*?)', line, re.I):
        unit.operator = 'all' if shared[3].casefold() == 'and' else 'any'
        unit.alternatives = [shared[1] + value + shared[5] for value in (shared[2], shared[4])]
        unit.basis = 'Shared scope and proficiency apply to each explicit alternative' if unit.operator == 'any' else 'Shared scope applies to every AND condition'
    elif re.search(r'\band\b|\s&\s', line, re.I):
        unit.operator = 'all'
        if re.search(TECH_LIST, line) and re.search(r'\band\s+[A-Z]', line):
            unit.uncertain = True
            unit.basis += '; combined technical scopes need review'
    elif re.search(r'\bor\b|and/or', line, re.I):
        unit.operator = 'any'
    if '/' in line and not re.search(r'TCP/IP|CI/CD|and/or', line, re.I) and unit.operator == 'single':
        unit.operator, unit.uncertain = 'ambiguous', True
        unit.basis += '; slash meaning needs review'
    from app.services.evidence_matching import required_level
    unit.level = required_level(line)
    return [unit]


def extract_sections(text: str) -> tuple[list[SourceUnit], list[str]]:
    # Legacy portal exports used MUST HAVE for short tags alongside a separate
    # prose REQUIREMENTS section. Preserve those tags with unspecified priority.
    tag_block = re.search(r'(?im)^MUST HAVE\s*\n(.*?)\n\s*(?:NICE TO HAVE\s*\n.*?)?^REQUIREMENTS\s*$', text, re.S | re.M)
    legacy_tags = bool(tag_block and all(len(v.split()) <= 3 and not REQUIREMENT_SIGNAL.search(v) for v in tag_block[1].splitlines() if v.strip()))
    if legacy_tags:
        text = text[:tag_block.start()] + text[tag_block.start():].replace('MUST HAVE', 'PORTAL TECHNOLOGY TAGS', 1)
    units, section, category, recognized = [], '', None, ['MUST HAVE'] if legacy_tags else []
    for raw in text.splitlines():
        line = re.sub(r'^(?:->|[•*−–>-])\s*', '', raw.strip()).strip()
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
            if INSTRUCTION.search(line):
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
            group = f'source_{len(units) + 1}'
            # Semicolons delimit independently qualified clauses. Retain the
            # entire source sentence on every row for review.
            pieces = [p.strip(' ;') for p in re.split(r';(?![^()]*\))', line) if p.strip(' ;')]
            if re.search(r'\bCRM\b', line, re.I) and re.search(r'\bKCS\b', line, re.I) and re.search(r'\band\b', line, re.I):
                pieces = re.split(r'\s+and\s+(?=working|knowledge|experience|KCS)', line, maxsplit=1, flags=re.I)
            elif re.search(r'\bfluen\w*\b|would be a plus|is a plus', line, re.I):
                pieces = re.split(r'(?<=[.!?])\s+(?=[A-Z])', line.rstrip(';'))
            for piece_index, piece in enumerate(pieces):
                piece_category = category
                # A preferred parenthesis must not weaken the main capability.
                parenthesis = re.search(r'\(([^()]*)\)', piece)
                if re.search(r'preferred\s*;\s*other languages welcome', piece, re.I):
                    parsed = requirement_units(piece, category, section, group + f'_{piece_index}')
                    for unit in parsed:
                        unit.quote = line
                    units.extend(parsed)
                    continue
                if category in {'mandatory', 'preferred', 'nice_to_have'} and parenthesis and PREFERENCE_MARKER.search(parenthesis[1]) and not re.fullmatch(r'\s*(?:big plus|optional|preferred|nice.to.have|(?:is )?(?:considered (?:an? )?)?advantage)\s*', parenthesis[1], re.I):
                    main = (piece[:parenthesis.start()] + piece[parenthesis.end():]).strip(' .;')
                    detail = parenthesis[1].strip()
                    parsed = requirement_units(main, category, section, group + f'_{piece_index}')
                    parsed += requirement_units(detail, 'nice_to_have' if re.search(r'\boptional\b', detail, re.I) else 'preferred', section, group + f'_{piece_index}_preferred')
                    for unit in parsed:
                        unit.quote = line
                        unit.basis += '; parenthetical preference separated from the main condition'
                    units.extend(parsed)
                    continue
                if category in {'mandatory', 'preferred', 'nice_to_have'} and PREFERENCE_MARKER.search(piece):
                    piece_category = 'nice_to_have' if re.search(r'\boptional\b', piece, re.I) else 'preferred'
                basis = f'{piece_category.title()} section: {section}' if piece_category == category else 'Explicit optional condition in source text' if piece_category == 'nice_to_have' else 'Explicit preference in source text'
                if category == 'mandatory' and re.search(r',\s*(?:preferably|preferred specialization)\b', piece, re.I):
                    piece_category = category
                    basis = f'Mandatory section: {section}; the preferably clause is optional'
                piece_group = group if re.search(r'\bCRM\b.*\band\b.*\bKCS\b', line, re.I) else group + f'_{piece_index}'
                parsed = requirement_units(piece.strip(' ;'), piece_category, section, piece_group)
                for unit in parsed:
                    unit.quote = line
                    if len(parsed) == 1 and unit.operator == 'single' and not unit.basis.endswith('optional'):
                        unit.basis = basis + ('; slash meaning needs review' if unit.uncertain else '')
                units.extend(parsed)
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
