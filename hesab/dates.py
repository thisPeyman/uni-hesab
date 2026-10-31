"""Jalali UI boundaries; Gregorian ISO dates are used only for storage."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

import jdatetime

MONTHS = (
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)
DIGIT_MAP = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def today() -> date:
    return datetime.now(ZoneInfo("Asia/Tehran")).date()


def latin_digits(value: str) -> str:
    return value.translate(DIGIT_MAP)


def parse_jalali(value: str) -> date:
    try:
        parts = latin_digits(value.strip()).replace("-", "/").split("/")
        if len(parts) != 3:
            raise ValueError
        year, month, day = map(int, parts)
        if not 1200 <= year <= 1600:
            raise ValueError
        return jdatetime.date(year, month, day).togregorian()
    except (TypeError, ValueError) as exc:
        raise ValueError("تاریخ شمسی معتبر وارد کنید؛ مانند 1405/08/09.") from exc


def jalali(value: date | str) -> str:
    if isinstance(value, str):
        value = date.fromisoformat(value)
    return jdatetime.date.fromgregorian(date=value).strftime("%Y/%m/%d")


def month_key(value: date) -> str:
    return jalali(value)[:7].replace("/", "-")


def month_bounds(key: str) -> tuple[date, date]:
    """Half-open Gregorian range for a Jalali month, including leap Esfand."""
    try:
        year, month = map(int, key.split("-"))
        start = jdatetime.date(year, month, 1).togregorian()
        end = jdatetime.date(year + (month == 12), month % 12 + 1, 1).togregorian()
        return start, end
    except (ValueError, TypeError) as exc:
        raise ValueError("ماه شمسی معتبر نیست.") from exc


def shift_month(key: str, offset: int) -> str:
    year, month = map(int, key.split("-"))
    year, index = divmod(year * 12 + month - 1 + offset, 12)
    return f"{year:04d}-{index + 1:02d}"


def month_label(key: str) -> str:
    year, month = map(int, key.split("-"))
    return f"{MONTHS[month - 1]} {year}"
