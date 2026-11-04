from app.services.job_sections import DUTY, extract_sections


def test_polish_source_headings_synthetic():
    offer = """Sprawdzisz się w tej roli, jeżeli:
Masz doświadczenie w programowaniu w Pythonie, minimum 5 lat doświadczenia w software engineering.
Mile widziane:
Znajomość niemieckiego
Zadania, które na Ciebie czekają:
Projektowanie aplikacji AI.
Nasz proces rekrutacji
Rozmowa z rekruterem
Potrzebujesz więcej informacji?
Skontaktuj się z nami: hiring@example.invalid
Co oferujemy
Szkolenia techniczne
Requirements
Knowledge of Linux
"""
    units, _ = extract_sections(offer)

    actual = {u.quote: u.category for u in units}

    expected = {
        "Masz doświadczenie w programowaniu w Pythonie, minimum 5 lat doświadczenia w software engineering.": "mandatory",
        "Znajomość niemieckiego": "preferred",
        "Projektowanie aplikacji AI.": "responsibility",
        "Rozmowa z rekruterem": "recruitment",
        "Skontaktuj się z nami: hiring@example.invalid": "recruitment",
        "Szkolenia techniczne": "benefits",
        "Knowledge of Linux": "mandatory"
    }

    assert actual == expected


def test_polish_source_headings_parameterized():
    # Test headers with/without colons and case insensitivity
    # They should be in recognized but NOT in units.
    headers = [
        "Sprawdzisz się w tej roli, jeżeli:",
        "sprawdzisz się w tej roli, jeżeli",
        "Zadania, które na Ciebie czekają:",
        "zadania, które na ciebie czekają"
    ]

    for h in headers:
        units, recognized = extract_sections(h)
        # Since extract_sections rstrips the colon, we check the stripped version
        stripped = h.rstrip(':').strip()
        assert stripped in recognized
        assert len(units) == 0


def test_polish_source_headings_false_positive():
    # "Opisuje zadania, które na Ciebie czekają w zespole."
    sentence = "Opisuje zadania, które na Ciebie czekają w zespole."
    assert DUTY.fullmatch(sentence) is None

    units, _ = extract_sections(sentence)
    assert len(units) == 0
