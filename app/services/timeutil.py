from datetime import date, datetime, timedelta, timezone

# India has no daylight saving, so a fixed offset is exact (and needs no tzdata package on Windows)
IST = timezone(timedelta(hours=5, minutes=30), "IST")


def today_ist() -> date:
    """Today's date in India (licence expiry dates are Indian calendar dates)."""
    return datetime.now(IST).date()
