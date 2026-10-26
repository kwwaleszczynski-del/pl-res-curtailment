from datetime import date

import pytest

from pl_res_curtailment.calendar_pl import day_type, easter, holiday_name, public_holidays


@pytest.mark.parametrize("year, expected", [(2023, date(2023, 4, 9)), (2024, date(2024, 3, 31)),
                                            (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5)),
                                            (2027, date(2027, 3, 28))])
def test_easter(year, expected):
    assert easter(year) == expected


def test_movable_holidays_2026():
    h = public_holidays(2026)
    assert h[date(2026, 4, 6)] == "Easter Monday"
    assert h[date(2026, 5, 24)] == "Pentecost"
    assert h[date(2026, 6, 4)] == "Corpus Christi"
    assert len(h) == 14


def test_christmas_eve_from_2025():
    assert holiday_name(date(2024, 12, 24)) is None
    assert holiday_name(date(2025, 12, 24)) == "Christmas Eve"


def test_day_types():
    assert day_type(date(2026, 5, 1)) == "sunday_holiday"     # Friday, Labour Day
    assert day_type(date(2026, 5, 2)) == "saturday"
    assert day_type(date(2026, 5, 3)) == "sunday_holiday"     # Sunday and Constitution Day
    assert day_type(date(2026, 8, 15)) == "sunday_holiday"    # Saturday holiday counts as holiday
    assert day_type(date(2026, 5, 4)) == "workday"
