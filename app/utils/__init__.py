"""HCS Utilities."""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """Return timezone-naive UTC datetime to prevent Python 3.12+ warnings and DB mismatch."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
