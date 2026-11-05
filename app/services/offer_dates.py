"""Publisher calendar dates: explicit formats only, with no timezone conversion."""
import re
from datetime import date, datetime, timezone

_ISO_DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}')
_ISO_DATETIME = re.compile(
    r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}'
    r'(?::[0-9]{2}(?:\.[0-9]+)?)?(?:Z|[+-][0-9]{2}:?[0-9]{2})?')
_DOTTED = re.compile(r'([0-9]{2})\.([0-9]{2})\.([0-9]{4})')
_NAMED = re.compile(r'([0-9]{1,2})\s+([^\W\d_]+)\s+([0-9]{4})')
_MONTHS = {
    name: month for names in (
        'january february march april may june july august september october november december',
        'stycznia lutego marca kwietnia maja czerwca lipca sierpnia września października listopada grudnia',
    ) for month, name in enumerate(names.split(), 1)
}


def parse_offer_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value or len(value) > 128:
        return None
    try:
        if _ISO_DATE.fullmatch(value):
            return date.fromisoformat(value)
        if _ISO_DATETIME.fullmatch(value):
            return datetime.fromisoformat(value).date()
        if match := _DOTTED.fullmatch(value):
            return date(int(match[3]), int(match[2]), int(match[1]))
        if match := _NAMED.fullmatch(value):
            month = _MONTHS.get(match[2].casefold())
            if month:
                return date(int(match[3]), month, int(match[1]))
    except ValueError:
        return None
    return None


def offer_deadline_view(value: object, today: date | None = None) -> dict:
    parsed = parse_offer_date(value)
    today = today if today is not None else datetime.now(timezone.utc).date()
    return {'date': parsed.isoformat() if parsed else None, 'expired': parsed is not None and parsed < today}
