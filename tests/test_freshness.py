from datetime import datetime, timedelta

from homelab_status.freshness import classify


def test_freshness_boundaries(now: datetime) -> None:
    assert classify(None, now, 1800, 7200) == "missing"
    assert classify(now - timedelta(seconds=1800), now, 1800, 7200) == "fresh"
    assert classify(now - timedelta(seconds=1801), now, 1800, 7200) == "stale"
    assert classify(now - timedelta(seconds=7200), now, 1800, 7200) == "stale"
    assert classify(now - timedelta(seconds=7201), now, 1800, 7200) == "missing"

