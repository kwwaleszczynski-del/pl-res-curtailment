"""Polish public holidays and day types.

Statutory non-working days (ustawa o dniach wolnych od pracy): 1 and 6 January, Easter Sunday and Monday, 1 and 3 May,
Pentecost Sunday, Corpus Christi, 15 August, 1 and 11 November, 25 and 26 December, and 24 December from 2025 on.

Usage:
    public_holidays(2026)[date(2026, 5, 1)]       # 'Labour Day'
    day_type(date(2026, 5, 3))                    # 'sunday_holiday'
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

DAY_TYPES = ("workday", "saturday", "sunday_holiday")


def easter(year: int) -> date:
    """Easter Sunday of the Gregorian calendar (anonymous algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month, day = divmod(h + m - 7 * n + 114, 31)
    return date(year, month, day + 1)


@lru_cache(maxsize=None)
def public_holidays(year: int) -> dict[date, str]:
    e = easter(year)
    days = {
        date(year, 1, 1): "New Year",
        date(year, 1, 6): "Epiphany",
        e: "Easter Sunday",
        e + timedelta(days=1): "Easter Monday",
        date(year, 5, 1): "Labour Day",
        date(year, 5, 3): "Constitution Day",
        e + timedelta(days=49): "Pentecost",
        e + timedelta(days=60): "Corpus Christi",
        date(year, 8, 15): "Assumption Day",
        date(year, 11, 1): "All Saints' Day",
        date(year, 11, 11): "Independence Day",
        date(year, 12, 25): "Christmas Day",
        date(year, 12, 26): "Second Day of Christmas",
    }
    if year >= 2025:
        days[date(year, 12, 24)] = "Christmas Eve"
    return days


def holiday_name(d: date) -> str | None:
    return public_holidays(d.year).get(d)


def day_type(d: date) -> str:
    """'workday', 'saturday' or 'sunday_holiday' (a holiday on a Saturday counts as a holiday)."""
    if d.weekday() == 6 or d in public_holidays(d.year):
        return "sunday_holiday"
    return "saturday" if d.weekday() == 5 else "workday"
