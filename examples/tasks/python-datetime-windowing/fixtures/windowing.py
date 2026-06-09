"""Timestamp windowing."""

from datetime import datetime


def bucket_start(timestamp, window_minutes):
    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    minute = (dt.minute // window_minutes) * window_minutes
    bucketed = dt.replace(minute=minute, second=0, microsecond=0)
    if timestamp.endswith("Z"):
        return bucketed.replace(tzinfo=None).isoformat() + "Z"
    return bucketed.isoformat()
