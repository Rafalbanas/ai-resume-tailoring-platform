from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.job_extractors.pasted import clean_pasted_offer
from tests.test_recording_demo import sign_in


@pytest.mark.parametrize("url", ["", "https://jobs.example.org/support", "https://justjoin.it/job/support"])
def test_unknown_portal_preserves_requirements_and_optional_priority(url):
    result = clean_pasted_offer("""Menu
Company: Example Ltd
Job title: Support Engineer
Apply now
Responsibilities
Support Linux servers and investigate customer incidents.
Requirements
Two years of production support experience and English at B2 level.
Nice to have
Knowledge of Kubernetes is optional.
Benefits
Private healthcare and sports card.
Employment conditions
Remote work, full-time contract.
Similar jobs
Unrelated Java Developer requiring ten years of experience.
""", url)
    assert result.usable
    assert result.company == "Example Ltd"
    assert result.role == "Support Engineer"
    assert "REQUIREMENTS\nTwo years" in result.job_description
    assert "NICE TO HAVE\nKnowledge of Kubernetes is optional." in result.job_description
    assert "Remote work, full-time contract." in result.job_description
    for noise in ("Apply now", "Menu", "healthcare", "Java Developer"):
        assert noise not in result.job_description


def test_plain_description_keeps_unrecognized_content_without_guessing_names():
    text = "We need a technician to support our customers.\nCustom working arrangements\nTravel is required twice a month."
    result = clean_pasted_offer(text)
    assert result.job_description == text
    assert result.company == result.role == ""
    assert "Eldorado" not in result.job_description


def test_polish_sections_and_pracuj_regression_without_url():
    result = clean_pasted_offer("""Nasze oczekiwania
Znajomość Linux oraz minimum dwa lata doświadczenia we wsparciu użytkowników.
Mile widziane
Znajomość Docker będzie dodatkowym atutem.
To oferujemy
Karta sportowa.
""")
    assert "REQUIREMENTS\nZnajomość Linux" in result.job_description
    assert "NICE TO HAVE\nZnajomość Docker" in result.job_description
    assert "sportowa" not in result.job_description
    pracuj = clean_pasted_offer(Path("tests/fixtures/pracuj/media_expert_support.txt").read_text())
    assert pracuj.company == "Media Expert"
    assert "Intune" in pracuj.job_description
    assert "Medicover" not in pracuj.job_description


def test_generic_cleaning_endpoint_requires_csrf_and_does_not_fetch(monkeypatch):
    async def forbidden_fetch(*args, **kwargs):
        pytest.fail("Cleaning pasted text must not fetch a URL")

    with TestClient(app) as client:
        sign_in(client)
        monkeypatch.setattr(app.state.job_extractor, "extract", forbidden_fetch)
        payload = {
            "text": "Requirements\nExperience supporting Linux servers and diagnosing network incidents is required.\nApply now",
            "url": "https://careers.example.org/support",
        }
        assert client.post("/api/clean-job-text", json=payload).status_code == 403
        response = client.post("/api/clean-job-text", json=payload,
                               headers={"X-CSRF-Token": client.cookies.get("csrf_token")})
        assert response.status_code == 200
        result = response.json()
        assert result["extraction_method"] != "manual_required"
        assert "Linux" in result["job_description"]
        assert "Apply now" not in result["job_description"]


def test_only_page_controls_are_not_an_offer():
    assert not clean_pasted_offer("Menu\nApply now\nSign in\nAccept all cookies\nSimilar jobs").usable
