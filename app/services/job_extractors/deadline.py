"""Read explicitly labelled closing dates, never infer them from publication age."""
import re

from app.services.job_extractors.base import cleaned_soup
from app.services.job_sections import clean_source_line
from app.services.offer_dates import parse_offer_date

_LABEL = re.compile(
    r'^(?:oferta\s+ważna\s+do|ważna\s+do|aplikuj\s+do|offer\s+valid\s+until|'
    r'valid\s+through|expires\s+on|application\s+deadline)\s*:?\s*(.*)$', re.I)
_RELATED = re.compile(
    r'^(?:similar (?:jobs|offers)|related (?:jobs|offers)|recommended (?:jobs|offers)|'
    r'other (?:jobs|offers)|you may also like|podobne oferty|polecane oferty|inne oferty)(?:\s.*|:)?$', re.I)
_COUNTDOWN = re.compile(r'\d+\s+days?\s+left\s*\(until\s+(\d{2}\.\d{2}\.\d{4})\)', re.I)
_NFJ_SUFFIX = re.compile(r'(.+?)\s*\(zosta[łl](?:o|y)?\s+\d+\s+(?:dni|dzień|dzien)\)', re.I)


def labelled_dates(text):
    lines = [clean_source_line(line) for line in text.splitlines() if line.strip()]
    dates = set()
    for index, line in enumerate(lines):
        if _RELATED.fullmatch(line):
            break
        match = _LABEL.fullmatch(line)
        if match:
            value = match[1] or (lines[index + 1] if index + 1 < len(lines) else '')
            suffix = _NFJ_SUFFIX.fullmatch(value)
            if suffix:
                value = suffix[1]
            parsed = parse_offer_date(value)
            if parsed:
                dates.add(parsed)
        countdown = _COUNTDOWN.fullmatch(line)
        if countdown:
            parsed = parse_offer_date(countdown[1])
            if parsed:
                dates.add(parsed)
    return dates


def labelled_deadline(text):
    dates = labelled_dates(text)
    return next(iter(dates)) if len(dates) == 1 else None


def html_deadlines(html, *, justjoin=False):
    soup = cleaned_soup(html)
    dates = set()
    if justjoin:
        # JJ's own application countdown is outside <main>. Require its progress
        # indicator, not arbitrary dates in job descriptions or recommended cards.
        for node in soup.select('[role="progressbar"]'):
            if node.parent:
                dates.update(labelled_dates(node.parent.get_text('\n', strip=True)))
    scope = soup.select_one('main') or soup.select_one('nfj-posting-header')
    if scope is None:
        return dates  # Do not take generic dates from unrelated page chrome.
    for node in scope.select('[class*="related"], [class*="similar"], [class*="recommended"], aside'):
        node.decompose()
    for node in scope.select('h1, h2, h3, h4, h5, h6, [itemprop="validThrough"], [data-cy="posting-valid-until"], [data-test-id="offer-valid-until"]'):
        if node.name in {'h1', 'h2', 'h3', 'h4', 'h5', 'h6'}:
            if _RELATED.fullmatch(node.get_text(' ', strip=True)):
                break
            continue
        value = node.get('datetime') or node.get('content') or node.get_text(' ', strip=True)
        parsed = parse_offer_date(value)
        if parsed:
            dates.add(parsed)
        dates.update(labelled_dates(value))
    dates.update(labelled_dates(scope.get_text('\n', strip=True)))
    return dates


def html_deadline(html):
    dates = html_deadlines(html)
    return next(iter(dates)) if len(dates) == 1 else None


def same_posting(left, right):
    """Do not attach JSON-LD metadata belonging to a different offer."""
    comparisons = [(a.casefold().strip(), b.casefold().strip())
                   for a, b in [(left.company, right.company), (left.role, right.role)] if a and b]
    return bool(comparisons) and all(a == b for a, b in comparisons)
