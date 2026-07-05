"""Time helpers — the only place the api asks for 'now'."""
from datetime import datetime, timezone


def now_utc() -> datetime:
    """Aware UTC now. Replaces the deprecated datetime.utcnow() everywhere."""
    return datetime.now(timezone.utc)
