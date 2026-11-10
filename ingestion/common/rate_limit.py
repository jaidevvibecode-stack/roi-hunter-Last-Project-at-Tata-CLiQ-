"""
ingestion/common/rate_limit.py
-------------------------------
Monitor Meta Insights rate-limit response headers and back off when approaching limits.

Headers watched:
  x-business-use-case-usage  — JSON dict keyed by business use case; each entry has
                               {call_count, total_cputime, total_time, type, estimated_time_to_regain_access}
  x-fb-ads-insights-throttle — JSON: {app_id_util_pct, acc_id_util_pct}

We back off when any percentage exceeds BACKOFF_THRESHOLD (75%).
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

BACKOFF_THRESHOLD = 75  # percent
CRITICAL_THRESHOLD = 90  # percent — longer back-off


@dataclass
class RateLimitState:
    """Mutable state shared across a batch of API calls for one account."""

    account_id: str
    max_pct: float = 0.0
    estimated_regain_seconds: int = 0
    last_checked: float = field(default_factory=time.monotonic)

    def update(self, headers: dict[str, str]) -> None:
        """Parse rate-limit headers and update state."""
        self.last_checked = time.monotonic()
        pcts: list[float] = []

        # x-business-use-case-usage
        raw_buc = headers.get("x-business-use-case-usage", "")
        if raw_buc:
            try:
                buc: dict[str, list[dict[str, Any]]] = json.loads(raw_buc)
                for entries in buc.values():
                    for entry in entries:
                        pcts.extend(
                            [
                                entry.get("call_count", 0),
                                entry.get("total_cputime", 0),
                                entry.get("total_time", 0),
                            ]
                        )
                        self.estimated_regain_seconds = max(
                            self.estimated_regain_seconds,
                            entry.get("estimated_time_to_regain_access", 0),
                        )
            except json.JSONDecodeError:
                log.warning("Could not parse x-business-use-case-usage header")

        # x-fb-ads-insights-throttle
        raw_throttle = headers.get("x-fb-ads-insights-throttle", "")
        if raw_throttle:
            try:
                throttle: dict[str, float] = json.loads(raw_throttle)
                pcts.extend(
                    [
                        throttle.get("app_id_util_pct", 0),
                        throttle.get("acc_id_util_pct", 0),
                    ]
                )
            except json.JSONDecodeError:
                log.warning("Could not parse x-fb-ads-insights-throttle header")

        self.max_pct = max(pcts, default=0.0)
        log.debug(
            "Rate limit state updated",
            extra={"account_id": self.account_id, "max_pct": self.max_pct},
        )

    def should_backoff(self) -> bool:
        return self.max_pct >= BACKOFF_THRESHOLD

    def backoff_seconds(self) -> float:
        """How long to sleep before the next call."""
        if self.max_pct >= CRITICAL_THRESHOLD:
            # Use server estimate if available, else 120s
            secs = self.estimated_regain_seconds or 120
        elif self.max_pct >= BACKOFF_THRESHOLD:
            secs = self.estimated_regain_seconds or 30
        else:
            secs = 0
        return float(secs)

    def wait_if_needed(self) -> None:
        """Block the current thread if rate limit threshold is exceeded."""
        if self.should_backoff():
            secs = self.backoff_seconds()
            log.warning(
                "Rate limit threshold exceeded — backing off",
                extra={
                    "account_id": self.account_id,
                    "max_pct": self.max_pct,
                    "sleep_seconds": secs,
                },
            )
            time.sleep(secs)


# ── Global registry: one state per account_id ────────────────────────────────
_states: dict[str, RateLimitState] = {}


def get_state(account_id: str) -> RateLimitState:
    if account_id not in _states:
        _states[account_id] = RateLimitState(account_id=account_id)
    return _states[account_id]


def update_and_wait(account_id: str, headers: dict[str, str]) -> None:
    """Convenience: update state from headers and sleep if needed."""
    state = get_state(account_id)
    state.update(headers)
    state.wait_if_needed()
