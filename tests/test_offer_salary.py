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
