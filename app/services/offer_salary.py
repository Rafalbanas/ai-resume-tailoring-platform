"""Literal compensation snippets; no model calls or inferred financial terms."""
import re

_CURRENCY = r'(?:PLN\b|EUR\b|USD\b|GBP\b|zł\b|[€$£])'
_AMOUNT = r'\d{1,9}(?:[ \u00a0\u202f,.]\d{3}){0,3}(?:[.,]\d{1,2})?(?:\s*[kK]\b)?'
_RANGE = rf'(?:\s*(?:[-–—]|\bto\b|\bdo\b)\s*(?:{_CURRENCY}\s*)?{_AMOUNT})?'
_CORE = rf'(?:{_CURRENCY}\s*{_AMOUNT}{_RANGE}|{_AMOUNT}(?:\s*{_CURRENCY})?{_RANGE}\s*{_CURRENCY})'
_TERM = (
    r'(?:umowa o pracę\b|umowa zlecenie\b|kontrakt B2B\b|'
    r'contract of employment\b|B2B contract\b|'
    r'netto\b|brutto\b|net\b|gross\b|VAT\b|B2B\b|UoP\b|'
    r'per\b|a\b|an\b|year(?:ly)?\b|annum\b|month(?:ly)?\b|hour(?:ly)?\b|day\b|'
    r'miesiąc\b|miesięcznie\b|mies\.|mth\.|godzin\w*\b|rocznie\b|h\b)'
)

_SALARY = re.compile(
    rf'(?<![\w\d])(?:(?:od|do|from|up\s+to)\s+)?{_CORE}'
    rf'(?:[\s+()/·|]*{_TERM})*[\s)]*', re.I,
)
_NOT_PAY = re.compile(r'\b(?:budget|budżet\w*|revenue|turnover|przych[oó]d\w*|referral|polecen\w*)\b', re.I)
_OTHER_OFFERS = re.compile(r'^(?:similar jobs|related jobs|podobne oferty|inne oferty)\b', re.I)

_QUALIFIER_LINE = re.compile(rf'(?:[\s+()/·|]*{_TERM})+[\s+()/·|]*', re.I)


def extract_offer_salary(text: str) -> str:
    """Keep stated currencies, periods, contract and tax qualifiers verbatim.

    Short source lines retain their labels; long prose yields bounded local
    snippets. Complete snippets are kept rather than truncating a financial term.
    """
    if not isinstance(text, str):
        return ''
    results, seen = [], set()
    # Pipes inside salary widgets separate tax/period and contract labels, not
    # necessarily different rates. Keep them with their original amounts.
    segments = re.split(r'[\n;]+', text)
    i = 0
    while i < len(segments):
        line = segments[i].strip()
        i += 1
        if _OTHER_OFFERS.match(line):
            break
        if not line or _NOT_PAY.search(line):
            continue
        if not _SALARY.search(line):
            continue
        # Only complete qualifier-only lines may extend a rate. Searching for
        # qualifier words would incorrectly attach requirements or benefits.
        while i < len(segments) and _QUALIFIER_LINE.fullmatch(segments[i].strip()):
            line += ' ' + segments[i].strip()
            i += 1
        matches = list(_SALARY.finditer(line))
        fragments = [line] if len(line) <= 80 else [match.group().strip() for match in matches]
        for fragment in fragments:
            key = fragment.casefold()
            if key in seen:
                continue
            if sum(map(len, results)) + len(results) + len(fragment) > 500:
                continue
            seen.add(key)
            results.append(fragment)
    return '\n'.join(results)
