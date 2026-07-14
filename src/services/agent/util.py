"""Small shared helper (timezone-aware now)."""
from datetime import datetime, timezone


def _utcnow() -> datetime:
    """Timezone-aware UTC now. datetime.utcnow() is deprecated because it
    returns a NAIVE datetime — comparing naive and aware datetimes raises
    TypeError, and naive timestamps silently shift meaning across servers
    in different timezones."""
    return datetime.now(timezone.utc)
