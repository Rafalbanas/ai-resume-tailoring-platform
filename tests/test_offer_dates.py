from datetime import date

import pytest

from app.services.offer_dates import offer_deadline_view, parse_offer_date


@pytest.mark.parametrize("date_str, expected_date", [
    ("2026-11-30", date(2026, 11, 30)),
    ("2026-11-30T23:30:00+04:00", date(2026, 11, 30)),
    ("2026-11-30T23:30:00-04:00", date(2026, 11, 30)),
    ("2026-11-30T23:30Z", date(2026, 11, 30)),
    ("2026-11-30T23:30:00Z", date(2026, 11, 30)),
    ("30.11.2026", date(2026, 11, 30)),
])
def test_parse_offer_date_valid_formats(date_str, expected_date):
    assert parse_offer_date(date_str) == expected_date

@pytest.mark.parametrize("date_str, expected_date", [
    ("30 listopada 2026", date(2026, 11, 30)),
    ("30 Listopada 2026", date(2026, 11, 30)),
    ("30 LISTOPADA 2026", date(2026, 11, 30)),
    ("30 Września 2026", date(2026, 9, 30)),
    ("30 Października 2026", date(2026, 10, 30)),
    ("30 November 2026", date(2026, 11, 30)),
    ("30 NOVEMBER 2026", date(2026, 11, 30)),
    ("30 november 2026", date(2026, 11, 30)),
])
def test_parse_offer_date_months(date_str, expected_date):
    assert parse_offer_date(date_str) == expected_date

@pytest.mark.parametrize("date_str", [
    "2028-02-29",  # Valid leap year
])
def test_parse_offer_date_leap_year_valid(date_str):
    assert parse_offer_date(date_str) == date(2028, 2, 29)

@pytest.mark.parametrize("date_str", [
    "2026-02-29",  # Invalid leap year
    "20261130",    # Compact
    "2026-W44-3",  # Week
    "11/12/2026",  # Slash
    "30 days",      # Text
    "1715856000",   # Epoch string
    "True",         # Bool string
    "",              # Empty
    "invalid_date", # Random text
])
def test_parse_offer_date_invalid_formats(date_str):
    assert parse_offer_date(date_str) is None

@pytest.mark.parametrize("value", [
    1715856000,
    True,
    False,
    {"date": "2026-11-30"},
    None,
])
def test_parse_offer_date_invalid_types(value):
    assert parse_offer_date(value) is None

def test_parse_offer_date_trailing_garbage():
    # Should return None because of fullmatch
    assert parse_offer_date("30 listopada 2026 extra") is None

def test_offer_deadline_view_status():
    today = date(2026, 11, 30)
    
    # Date: 2026-11-28 (expired)
    res = offer_deadline_view("2026-11-28", today=today)
    assert res["date"] == "2026-11-28"
    assert res["expired"] is True
    
    # Date: 2026-11-30 (not expired)
    res = offer_deadline_view("2026-11-30", today=today)
    assert res["date"] == "2026-11-30"
    assert res["expired"] is False
    
    # Date: 2026-12-01 (not expired)
    res = offer_deadline_view("2026-12-01", today=today)
    assert res["date"] == "2026-12-01"
    assert res["expired"] is False
    
    # Unknown (not expired)
    res = offer_deadline_view("invalid", today=today)
    assert res["date"] is None
    assert res["expired"] is False

@pytest.mark.parametrize("date_str, expected_date", [
    # Polish (Genitive) - Lower
    ("15 stycznia 2026", date(2026, 1, 15)),
    ("15 lutego 2026", date(2026, 2, 15)),
    ("15 marca 2026", date(2026, 3, 15)),
    ("15 kwietnia 2026", date(2026, 4, 15)),
    ("15 maja 2026", date(2026, 5, 15)),
    ("15 czerwca 2026", date(2026, 6, 15)),
    ("15 lipca 2026", date(2026, 7, 15)),
    ("15 sierpnia 2026", date(2026, 8, 15)),
    ("15 września 2026", date(2026, 9, 15)),
    ("15 października 2026", date(2026, 10, 15)),
    ("15 listopada 2026", date(2026, 11, 15)),
    ("15 grudnia 2026", date(2026, 12, 15)),
    # Polish (Genitive) - Upper
    ("15 STYCZNIA 2026", date(2026, 1, 15)),
    ("15 LUTEGO 2026", date(2026, 2, 15)),
    ("15 MARCA 2026", date(2026, 3, 15)),
    ("15 KWIETNIA 2026", date(2026, 4, 15)),
    ("15 MAJA 2026", date(2026, 5, 15)),
    ("15 CZERWCA 2026", date(2026, 6, 15)),
    ("15 LIPCA 2026", date(2026, 7, 15)),
    ("15 SIERPNIA 2026", date(2026, 8, 15)),
    ("15 WRZEŚNIA 2026", date(2026, 9, 15)),
    ("15 PAŹDZIERNIKA 2026", date(2026, 10, 15)),
    ("15 LISTOPADA 2026", date(2026, 11, 15)),
    ("15 GRUDNIA 2026", date(2026, 12, 15)),
    # Polish (Genitive) - Title
    ("15 Stycznia 2026", date(2026, 1, 15)),
    ("15 Lutego 2026", date(2026, 2, 15)),
    ("15 Marca 2026", date(2026, 3, 15)),
    ("15 Kwietnia 2026", date(2026, 4, 15)),
    ("15 Maja 2026", date(2026, 5, 15)),
    ("15 Czerwca 2026", date(2026, 6, 15)),
    ("15 Lipca 2026", date(2026, 7, 15)),
    ("15 Sierpnia 2026", date(2026, 8, 15)),
    ("15 Września 2026", date(2026, 9, 15)),
    ("15 Października 2026", date(2026, 10, 15)),
    ("15 Listopada 2026", date(2026, 11, 15)),
    ("15 Grudnia 2026", date(2026, 12, 15)),
    # English - Lower
    ("15 january 2026", date(2026, 1, 15)),
    ("15 february 2026", date(2026, 2, 15)),
    ("15 march 2026", date(2026, 3, 15)),
    ("15 april 2026", date(2026, 4, 15)),
    ("15 may 2026", date(2026, 5, 15)),
    ("15 june 2026", date(2026, 6, 15)),
    ("15 july 2026", date(2026, 7, 15)),
    ("15 august 2026", date(2026, 8, 15)),
    ("15 september 2026", date(2026, 9, 15)),
    ("15 october 2026", date(2026, 10, 15)),
    ("15 november 2026", date(2026, 11, 15)),
    ("15 december 2026", date(2026, 12, 15)),
    # English - Upper
    ("15 JANUARY 2026", date(2026, 1, 15)),
    ("15 FEBRUARY 2026", date(2026, 2, 15)),
    ("15 MARCH 2026", date(2026, 3, 15)),
    ("15 APRIL 2026", date(2026, 4, 15)),
    ("15 MAY 2026", date(2026, 5, 15)),
    ("15 JUNE 2026", date(2026, 6, 15)),
    ("15 JULY 2026", date(2026, 7, 15)),
    ("15 AUGUST 2026", date(2026, 8, 15)),
    ("15 SEPTEMBER 2026", date(2026, 9, 15)),
    ("15 OCTOBER 2026", date(2026, 10, 15)),
    ("15 NOVEMBER 2026", date(2026, 11, 15)),
    ("15 DECEMBER 2026", date(2026, 12, 15)),
    # English - Title
    ("15 January 2026", date(2026, 1, 15)),
    ("15 February 2026", date(2026, 2, 15)),
    ("15 March 2026", date(2026, 3, 15)),
    ("15 April 2026", date(2026, 4, 15)),
    ("15 May 2026", date(2026, 5, 15)),
    ("15 June 2026", date(2026, 6, 15)),
    ("15 July 2026", date(2026, 7, 15)),
    ("15 August 2026", date(2026, 8, 15)),
    ("15 September 2026", date(2026, 9, 15)),
    ("15 October 2026", date(2026, 10, 15)),
    ("15 November 2026", date(2026, 11, 15)),
    ("15 December 2026", date(2026, 12, 15)),
])
def test_parse_offer_date_all_months_variations(date_str, expected_date):
    assert parse_offer_date(date_str) == expected_date
