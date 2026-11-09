"""Literal compensation snippets; no model calls or inferred financial terms."""
import re

_CURRENCY = r'(?:PLN\b|EUR\b|USD\b|GBP\b|zł\b|[€$£])'
_AMOUNT = r'\d{1,9}(?:[ \u00a0\u202f,.]\d{3}){0,3}(?:[.,]\d{1,2})?(?:\s*[kK]\b)?'
_RANGE = rf'(?:\s*(?:[-–—]|\bto\b|\bdo\b)\s*(?:{_CURRENCY}\s*)?{_AMOUNT})?'
_CORE = rf'(?:{_CURRENCY}\s*{_AMOUNT}{_RANGE}|{_AMOUNT}(?:\s*{_CURRENCY})?{_RANGE}\s*{_CURRENCY})'
_TERM = (
    r'(?:netto\b|brutto\b|net\b|gross\b|VAT\b|B2B\b|UoP\b|'
    r'per\b|a\b|an\b|year(?:ly)?\b|annum\b|month(?:ly)?\b|hour(?:ly)?\b|day\b|'
    r'miesiąc\b|miesięcznie\b|mies\.|godzin\w*\b|rocznie\b|h\b)'
)
_SALARY = re.compile(
    rf'(?<![\w\d])(?:(?:od|do|from|up\s+to)\s+)?{_CORE}'
    rf'(?:\s*(?:[+/(·]|\))?\s*{_TERM}\s*\)?)*', re.I,
)
_NOT_PAY = re.compile(r'\b(?:budget|budżet\w*|revenue|turnover|przych[oó]d\w*|referral|polecen\w*)\b', re.I)
_OTHER_OFFERS = re.compile(r'^(?:similar jobs|related jobs|podobne oferty|inne oferty)\b', re.I)


def extract_offer_salary(text: str) -> str:
    """Keep stated currencies, periods, contract and tax qualifiers verbatim.

    Short source lines retain their labels; long prose yields bounded local
    snippets. Complete snippets are kept rather than truncating a financial term.
    """
    if not isinstance(text, str):
        return ''
    results, seen = [], set()
    for line in re.split(r'[\n;|]+', text):
        line = line.strip()
        if _OTHER_OFFERS.match(line):
            break
        if not line or _NOT_PAY.search(line):
            continue
        matches = list(_SALARY.finditer(line))
        if not matches:
            continue
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
