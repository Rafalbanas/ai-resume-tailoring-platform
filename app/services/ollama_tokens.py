"""Optional pinned tokenizer: no network, no schema-as-prompt accounting.

The digest identifies the vocabulary/templates verified in the context audit.
Unconfigured installations keep the explicit conservative planning fallback.
"""

import hashlib
import json
from pathlib import Path

QWEN_TOKENIZER_SHA256 = "0997f410c57a1f4e53b09e4be8f4a172d90edd9564368fb0847030937229b9f3"


class QwenTokenCounter:
    def __init__(self, path, model):
        if model not in {"qwen3.5:9b", "qwen3.8-27b-iq2s", "qwen3.8-27b-iq2s:latest"}:
            raise ValueError("Exact tokenizer is not verified for this model")
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != QWEN_TOKENIZER_SHA256:
            raise ValueError("Unverified tokenizer; context planning refused")
        from tokenizers import Tokenizer

        self.tokenizer = Tokenizer.from_str(raw.decode())

    def count(self, text):
        return len(self.tokenizer.encode(text, add_special_tokens=False).ids)

    def prompt(self, system, payload):
        # Two messages and non-thinking assistant prefix, verified against Ollama.
        return self.count(system) + self.count(json.dumps(payload, ensure_ascii=False, separators=(",", ":"))) + 17
