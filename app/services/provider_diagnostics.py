"""Fixed diagnostic reasons derived from untrusted upstream errors, never raw bodies."""
import hashlib
import re

HTTP_REASONS = {
    'context_budget': 'The input exceeds the model context limit.',
    'memory_exhausted': 'The model server could not allocate enough memory.',
    'model_not_found': 'The requested model is not available on the model server.',
    'invalid_schema': 'The model server rejected the structured output schema or grammar.',
    'authentication': 'The model server rejected authentication or access.',
    'rate_limited': 'The model server rejected the request due to rate limiting.',
    'endpoint_not_found': 'The model server endpoint was not found.',
    'invalid_request': 'The model server rejected the request parameters.',
    'server_error': 'The model server returned an internal or upstream service error.',
    'http_error': 'The model server returned an unsuccessful HTTP response.',
}


def http_error_details(response):
    """Read only the bounded response in memory; emit allowlisted descriptions."""
    text = response.text[:65536].casefold()
    status = response.status_code
    if status in {401, 403}:
        code = 'authentication'
    elif status == 429:
        code = 'rate_limited'
    elif re.search(r'prompt too long|exceed\w*[^\n]{0,80}context|context[^\n]{0,80}(?:exceed|too long|limit)', text):
        code = 'context_budget'
    elif re.search(r'out of memory|not enough memory|requires more[^\n]{0,60}memory|(?:failed|unable) to allocate|cuda[^\n]{0,40}alloc', text):
        code = 'memory_exhausted'
    elif re.search(r'model[^\n]{0,100}(?:not found|does not exist|not available)', text):
        code = 'model_not_found'
    elif re.search(r'(?:invalid|unsupported)[^\n]{0,60}(?:schema|grammar)|(?:schema|grammar)[^\n]{0,60}(?:invalid|unsupported)', text):
        code = 'invalid_schema'
    elif status == 404:
        code = 'endpoint_not_found'
    elif status >= 500:
        code = 'server_error'
    elif status in {400, 422}:
        code = 'invalid_request'
    else:
        code = 'http_error'
    return {
        'http_status': status, 'error_code': code, 'error_summary': HTTP_REASONS[code],
        'response_bytes': len(response.content),
        'response_sha256': hashlib.sha256(response.content).hexdigest(),
    }
