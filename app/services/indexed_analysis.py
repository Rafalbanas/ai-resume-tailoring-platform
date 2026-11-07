"""Provider-neutral job coverage using literal passage IDs, never parser categories."""
from app.services.ai_provider import ProviderResponseError
from app.services.ollama_analysis import COMPACT_PROMPT, CompactInterpretation, OllamaAnalysisError, needs_assessment


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

# Gemini's portable primitive schema uses rows rather than dynamic object keys.
# Do not send two competing response contracts in the same system prompt.
ROWS_PROMPT = INDEXED_PROMPT.replace(
    'Return {"assessments": {PASSAGE_ID: assessment}}. Every passage ID is a required key exactly once. Omit p inside assessment values.',
    'Return {"rows": [assessment, ...]}. Include p inside every assessment.',
).replace(
    'The response is a keyed assessments object, never a rows array. Return every supplied\npassage ID exactly once.',
    'The response is a rows array. Return every supplied passage ID exactly once.',
)


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


async def indexed_interpretation(provider, inventory, *, validation_feedback=None, max_attempts=2):
    pending = inventory.unique_assessment_ids(list(inventory.passages))
    rows = []
    error_message = '; '.join(validation_feedback or [])
    for _attempt in range(max_attempts):
        prompt = ROWS_PROMPT
        if error_message:
            prompt += f"\nVALIDATION FEEDBACK: {error_message}. Correct the response for every supplied passage; do not invent evidence."
        try:
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
            error_message = f'Analysis left {len(pending)} source passages unassessed'
        except (ProviderResponseError, OllamaAnalysisError) as exc:
            if isinstance(exc, OllamaAnalysisError) and exc.kind not in {'schema', 'invalid_json'}:
                raise
            error_message = str(exc)
    raise ProviderResponseError(
        f"{getattr(provider, 'name', 'AI')} analysis failed after bounded recovery: {error_message}"
    )
