import re


def ml_terminology_issue(text: str) -> bool:
    """
    Detects if a machine learning library is incorrectly referred to as a 'model'.

    Flags:
    - Libraries named exactly as 'scikit-learn', 'scikit learn', 'sklearn', 'numpy', 'pandas'
    - Within list patterns like 'models including...', 'models such as...', 'models like...', 'models: ...'
    - In direct statements like 'X is a machine learning model' (without 'not').
    """
    if not text:
        return False

    text_lower = text.lower()
    libraries = {'scikit-learn', 'scikit learn', 'sklearn', 'numpy', 'pandas'}

    # 1. Check for list patterns
    # patterns: models? (including|such as|like|:) [content]
    # content stops at ., ;, \n or end of string.
    # Use finditer to catch all occurrences.
    pattern = r"\bmodels?\s*(?:including\b|such\s+as\b|like\b|:)\s*([^.;\n]+)"

    for match in re.finditer(pattern, text_lower):
        content = match.group(1)
        # Split by comma or "and"/"or" (with surrounding whitespace)
        items = re.split(r',|\s+(?:and|or)\s+', content)
        for item in items:
            item = item.strip()
            # Flag only if the item is EXACTLY a library name
            if item in libraries:
                return True

    # 2. Check for direct "X is a model" statements
    for lib in libraries:
        # pattern: {lib} is (not) a (machine learning) model
        pattern = rf"\b{re.escape(lib)}\b\s+is\s+(?:a|an)\s+(?:machine\s+learning\s+)?model\b"
        if re.search(pattern, text_lower):
            return True

    return False
