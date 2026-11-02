"""Tests for Batch models."""

import pytest
from pydantic import ValidationError

from app.models.batch import BatchRequest, parse_url_file


def test_batch_request_valid():
    data = {
        "urls": ["https://example.com/1", "https://example.com/2"],
        "llm_provider": "ollama",
        "ollama_model": "llama3",
        "ollama_context": 65536,
        "template_name": "modern_sidebar",
        "tailoring_level": 0.5,
        "export": True
    }
    request = BatchRequest(**data)
    assert request.urls == ["https://example.com/1", "https://example.com/2"]
    assert request.llm_provider == "ollama"
    assert request.tailoring_level == 0.5

def test_batch_request_min_urls():
    with pytest.raises(ValidationError):
        BatchRequest(urls=[])

def test_batch_request_max_urls():
    urls = [f"https://example.com/{i}" for i in range(21)]
    with pytest.raises(ValidationError):
        BatchRequest(urls=urls)

def test_batch_request_deduplication():
    # Same URL should be deduplicated but keep order
    data = {
        "urls": [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/1",
            "https://example.com/3"
        ]
    }
    request = BatchRequest(**data)
    assert request.urls == ["https://example.com/1", "https://example.com/2", "https://example.com/3"]

def test_batch_request_invalid_url():
    with pytest.raises(ValidationError):
        BatchRequest(urls=["not-a-url"])

def test_batch_request_url_with_user_info():
    with pytest.raises(ValidationError):
        # http://user:pass@example.com
        BatchRequest(urls=["http://user:pass@example.com"])
    with pytest.raises(ValidationError):
        # http://user@example.com
        BatchRequest(urls=["http://user@example.com"])

def test_batch_request_url_with_fragment():
    with pytest.raises(ValidationError):
        # https://example.com/path#fragment
        BatchRequest(urls=["https://example.com/path#fragment"])

def test_batch_request_url_too_long():
    long_url = "https://" + ("a" * 2048)
    with pytest.raises(ValidationError):
        BatchRequest(urls=[long_url])

def test_batch_request_wrong_provider():
    with pytest.raises(ValidationError):
        BatchRequest(urls=["https://example.com"], llm_provider="invalid")

def test_batch_request_wrong_context():
    with pytest.raises(ValidationError):
        BatchRequest(urls=["https://example.com"], ollama_context=1234)

def test_batch_request_tailoring_level():
    with pytest.raises(ValidationError):
        BatchRequest(urls=["https://example.com"], tailoring_level=1.5)
    with pytest.raises(ValidationError):
        BatchRequest(urls=["https://example.com"], tailoring_level=-0.1)
    with pytest.raises(ValidationError):
        BatchRequest(urls=["https://example.com"], tailoring_level=float('inf'))

def test_batch_request_gemini_model_pattern():
    request = BatchRequest(urls=["https://example.com"], gemini_model="valid_model_123")
    assert request.gemini_model == "valid_model_123"
    with pytest.raises(ValidationError):
        BatchRequest(urls=["https://example.com"], gemini_model="invalid model!")

def test_parse_url_file_valid():
    content = b"https://example.com/1\nhttps://example.com/2   \thttps://example.com/3"
    urls = parse_url_file(content)
    assert urls == ["https://example.com/1", "https://example.com/2", "https://example.com/3"]

def test_parse_url_file_bom():
    content = b'\xef\xbb\xbfhttps://example.com/1'
    urls = parse_url_file(content)
    assert urls == ["https://example.com/1"]

def test_parse_url_file_empty():
    with pytest.raises(ValueError, match="File is empty"):
        parse_url_file(b"")

def test_parse_url_file_whitespace_only():
    with pytest.raises(ValueError, match="No URLs found in file"):
        parse_url_file(b"   \n  \t  ")

def test_parse_url_file_too_large():
    content = b"a" * (64 * 1024 + 1)
    with pytest.raises(ValueError, match="File is too large"):
        parse_url_file(content)

def test_parse_url_file_invalid_utf8():
    content = b"\xff\xfe\xfd"
    with pytest.raises(ValueError, match="File is not valid UTF-8"):
        parse_url_file(content)


@pytest.mark.parametrize('urls', [[' '], ['https://example.com', ' '], ['https://example.com#'],
                                 ['file:///etc/passwd'], ['https://example.com'] * 21])
def test_batch_request_rejects_empty_tokens_unsupported_schemes_and_oversized_input(urls):
    with pytest.raises(ValidationError):
        BatchRequest(urls=urls)


def test_batch_request_canonicalizes_and_deduplicates():
    assert BatchRequest(urls=[' HTTPS://EXAMPLE.COM ', 'https://example.com/']).urls == ['https://example.com/']
