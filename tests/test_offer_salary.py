import pytest

from app.services.offer_salary import extract_offer_salary


def test_extract_offer_salary_positive():
    # Test standard cases
    assert extract_offer_salary('10 000–15 000 PLN netto + VAT / miesiąc (B2B)') == '10 000–15 000 PLN netto + VAT / miesiąc (B2B)'
    assert extract_offer_salary('Salary: 60,000–80,000 EUR per year') == 'Salary: 60,000–80,000 EUR per year'
    assert extract_offer_salary('100–150 zł/h') == '100–150 zł/h'

    # Test single rate
    assert extract_offer_salary('Salary: 5000 PLN') == 'Salary: 5000 PLN'

    # Test multiple variants (should preserve both as separate fragments if on separate lines/segments)
    input_multi = "10 000 PLN B2B\n12 000 PLN UoP"
    assert "10 000 PLN B2B" in extract_offer_salary(input_multi)
    assert "12 000 PLN UoP" in extract_offer_salary(input_multi)

    # Test deduplication
    input_dup = "10 000 PLN\n10 000 PLN"
    assert extract_offer_salary(input_dup) == "10 000 PLN"

def test_extract_offer_salary_negative():
    # Should return empty string for no salary info
    assert extract_offer_salary("") == ""
    assert extract_offer_salary("No salary information provided.") == ""

    # Should ignore "competitive salary" without numbers
    assert extract_offer_salary("We offer a competitive salary for this role.") == ""

    # Should ignore unrelated numbers (experience, phone, employees)
    assert extract_offer_salary("Requires 5 years of experience.") == ""
    assert extract_offer_salary("Contact us at +48 123 456 789.") == ""
    assert extract_offer_salary("Company has 500 employees.") == ""

def test_extract_offer_salary_long_line():
    # Test isolating fragment from long line
    long_line = "We are looking for a Senior Developer with 10 000–15 000 PLN netto + VAT / miesiąc (B2B) for our high-performance team."
    # Since it's long, it should ideally extract the fragment
    result = extract_offer_salary(long_line)
    assert "10 000–15 000 PLN netto + VAT / miesiąc (B2B)" in result
    assert "Senior Developer" not in result # Should exclude the start of the sentence if it's long enough

def test_extract_offer_salary_max_length():
    # Test 500 character truncation
    long_text = "Salary: " + "A" * 1000 + " PLN"
    assert len(extract_offer_salary(long_text)) <= 500

def test_currency_must_be_adjacent_to_amount():
    assert extract_offer_salary('5 years of experience. Salary in EUR discussed later.') == ''
    assert extract_offer_salary('Training budget: 5 000 PLN per year') == ''
    assert extract_offer_salary('Support workflows\nSimilar jobs\n20 000 PLN B2B') == ''

def test_open_ranges_symbols_and_repeated_currency():
    for text in ['od 10 000 PLN brutto', 'do 150 zł/h', '$60,000–80,000 gross per year',
                  '100 PLN – 150 PLN / h B2B', '£60k–£80k per year', '12\u00a0000–15\u00a0000 PLN']:
        assert extract_offer_salary(text) == text

def test_extract_offer_salary_regressions():
    # Multi-line fragments (PL and EN)
    multiline_1 = '11 000 – 13 000 zł\ngross / mth. | contract of employment'
    assert 'gross / mth.' in extract_offer_salary(multiline_1)
    assert 'contract of employment' in extract_offer_salary(multiline_1)

    multiline_2 = '14 000–18 000 zł\nnetto (+ VAT) / mth. | B2B contract'
    assert 'netto (+ VAT) / mth.' in extract_offer_salary(multiline_2)
    assert 'B2B contract' in extract_offer_salary(multiline_2)

    multiline_3 = '12 000 PLN\numowa zlecenie'
    assert 'umowa zlecenie' in extract_offer_salary(multiline_3)

    # Identical amount for different contracts
    input_same_amount = "10 000 PLN B2B\n10 000 PLN UoP"
    result = extract_offer_salary(input_same_amount)
    assert "10 000 PLN B2B" in result
    assert "10 000 PLN UoP" in result

    # Do not capture normal text
    assert extract_offer_salary("10000 PLN\nWe offer yearly training and monthly team meetings.") == "10000 PLN"
    assert extract_offer_salary("Just some numbers 1234567890") == ""


@pytest.mark.parametrize('suffix', ['We offer yearly training.', 'B2B experience required.',
                                  'Training budget: 5000 PLN per year', 'Requires 5 years of experience.'])
def test_qualifier_words_in_prose_are_not_attached(suffix):
    assert extract_offer_salary('10 000 PLN\n' + suffix) == '10 000 PLN'


def test_long_line_retains_all_contracts_and_tax_terms():
    text = ('Our compensation options for the successful candidate are '
            '10 000–14 000 PLN brutto / mies. | umowa o pracę and '
            '14 000–18 000 PLN netto (+ VAT) / mies. | kontrakt B2B.')
    value = extract_offer_salary(text)
    assert '10 000–14 000 PLN brutto / mies. | umowa o pracę' in value
    assert '14 000–18 000 PLN netto (+ VAT) / mies. | kontrakt B2B' in value
    assert 'Our compensation' not in value


def test_separate_qualifier_nodes_keep_same_amount_for_different_contracts():
    text = '10 000 PLN\nbrutto\n/ mies.\numowa o pracę\n10 000 PLN\nnetto (+ VAT)\n/ mies.\nkontrakt B2B'
    assert extract_offer_salary(text).splitlines() == [
        '10 000 PLN brutto / mies. umowa o pracę',
        '10 000 PLN netto (+ VAT) / mies. kontrakt B2B',
    ]
