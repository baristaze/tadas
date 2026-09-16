"""The ping interval and the load balancer idle timeout are pinned in one
shared file, so the client and the server cannot drift apart."""

import json
from pathlib import Path

from tadas.services.api.realtime.envelopes import IDLE_TIMEOUT_SECONDS, PING_INTERVAL_SECONDS

TIMEOUTS = Path(__file__).resolve().parents[3] / "deployment" / "realtime-timeouts.json"


def test_ping_interval_matches_the_shared_file() -> None:
    pinned = json.loads(TIMEOUTS.read_text())
    assert PING_INTERVAL_SECONDS == pinned["ping_interval_seconds"]
    assert PING_INTERVAL_SECONDS < pinned["load_balancer_idle_timeout_seconds"]
    assert IDLE_TIMEOUT_SECONDS >= pinned["load_balancer_idle_timeout_seconds"]
