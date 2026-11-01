"""Conservative experimental projection; the original job is never overwritten."""
import hashlib
import re

from app.services.job_sections import (
    REQUIREMENT_SIGNAL,
    WORK_CONDITION,
    clean_source_line,
    extract_sections,
    normalize_source_layout,
)

CLEANER_VERSION = 'context-projection-v2'
CONSTRAINT = re.compile(r'\b(?:[ABC][12]|B2B|contract|employment|remote|hybrid|salary|certif\w*|umow\w*|godzin\w*|zdaln\w*|zmianow\w*|wynagrodzen\w*)\b|24/7', re.I)
DUTY_SIGNAL = re.compile(r'\b(?:responsib\w*|administ\w*|maintain\w*|troubleshoot\w*|monitor\w*|support\w*)\b', re.I)


def normalize_offer_lines(text):
    return normalize_source_layout(text)


def clean_offer_text(text):
    normalized = normalize_offer_lines(text)
    units, _ = extract_sections(normalized)
    categories = {}
    for unit in units:
        categories.setdefault(clean_source_line(unit.quote), set()).add(unit.category)
    retained, removed = [], []
    for original in normalized.splitlines():
        line = clean_source_line(original)
        kinds = categories.get(line, set())
        expendable = bool(kinds) and kinds <= {'benefits', 'organization', 'recruitment'}
        protected = REQUIREMENT_SIGNAL.search(line) or WORK_CONDITION.search(line) or CONSTRAINT.search(line) or DUTY_SIGNAL.search(line)
        if expendable and not protected:
            removed.append(original)
        else:
            retained.append(original)
    cleaned = '\n'.join(retained).strip()
    return cleaned, {
        'version': CLEANER_VERSION, 'original_characters': len(text), 'cleaned_characters': len(cleaned),
        'removed_lines': len(removed), 'removed_characters': sum(len(line) for line in removed),
        'original_sha256': hashlib.sha256(text.encode()).hexdigest(),
        'cleaned_sha256': hashlib.sha256(cleaned.encode()).hexdigest(),
        'normalizes_inline_bullets': True,
    }
