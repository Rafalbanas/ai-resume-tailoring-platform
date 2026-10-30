"""Provider-neutral job coverage using literal passage IDs, never parser categories."""
from app.services.ollama_analysis import COMPACT_PROMPT, CompactInterpretation, needs_assessment


def interpretation_payload(inventory, ids):
    payload = inventory.payload(ids)
    # Incorrect inherited sections must not prime either model's interpretation.
    payload['passages'] = [{'id': pid, 'text': inventory.passages[pid]['text']} for pid in ids]
    return payload


INDEXED_PROMPT = COMPACT_PROMPT + """
The response is a keyed assessments object, never a rows array. Return every supplied
passage ID exactly once. Use job_source to interpret surrounding meaning and priority.
There are no parser categories to follow. Headings, benefit text and standalone level
labels are context. Explicit qualifications are requirements; duties are responsibilities.
Technology tags are competencies with unspecified priority, not mandatory qualifications.
Never assess promotional headings as candidate skills. Preserve the source AND/OR scope;
a slash between related APIs does not automatically make the condition uncertain.
"""


def reference_schema(inventory, ids):
    # Explicit primitive schema: no nullable unions or conditional branches that
    # a provider schema converter could silently erase.
    text = {'type': 'string'}
    facts = {'type': 'array', 'items': {'type': 'string'}}
    status = {'type': 'string', 'enum': ['strong', 'partial', 'missing', 'absent']}
    component = {'type': 'object', 'properties': {
        'n': text, 's': status, 'f': facts, 'why': text, 'lvl': text,
    }, 'required': ['n', 's', 'f', 'why']}
    row = {'type': 'object', 'properties': {
        'p': {'type': 'string', 'enum': ids},
        'k': {'type': 'string', 'enum': ['requirement', 'competency', 'responsibility', 'context']},
        'n': text, 'priority': {'type': 'string', 'enum': ['mandatory', 'preferred', 'nice_to_have', 'unspecified']},
        's': status, 'f': facts, 'why': text,
        'op': {'type': 'string', 'enum': ['single', 'all', 'any', 'ambiguous']},
        'c': {'type': 'array', 'items': component}, 'lvl': text, 'uncertain': {'type': 'boolean'},
    }, 'required': ['p', 'k', 'n', 'priority', 's', 'f', 'why', 'op', 'c', 'lvl', 'uncertain']}
    return {'type': 'object', 'properties': {'rows': {'type': 'array', 'items': row}}, 'required': ['rows']}


async def indexed_interpretation(provider, inventory):
    pending = list(inventory.passages)
    rows = []
    for _attempt in range(2):
        prompt = INDEXED_PROMPT + "\nFor this response return {rows: [assessment, ...]} with p inside each row. Exactly one row for each supplied passage ID, including all context and headings."
        response = await provider._chat(
            CompactInterpretation, prompt, interpretation_payload(inventory, pending),
            _schema=reference_schema(inventory, pending),
        )
        verified = inventory.validate_rows(response.rows, pending)
        valid = [row for row in verified if row.k not in {'context', 'responsibility'}
                 or not needs_assessment(inventory.passages[row.p])]
        rows.extend(valid)
        covered = {row.p for row in valid}
        pending = [pid for pid in pending if pid not in covered]
        if not pending:
            return inventory.expand(rows)
    from app.services.ai_provider import ProviderResponseError
    raise ProviderResponseError(f'Analysis left {len(pending)} source passages unassessed after targeted recovery.')
