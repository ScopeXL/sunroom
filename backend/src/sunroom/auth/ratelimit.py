"""Failure-based rate limits (PLAN §12.2, §12.3, §12.7). Memory is enough: one process.

* Sign-in, pairing and pair codes: 5 failures in 15 minutes per address locks that address out
  until the oldest failure ages out; 50 failures in an hour pauses them all for 15 minutes.
* The parent PIN: the same numbers per device, plus a 1-second pause after the third failure.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sunroom.core.clock import Clock
from sunroom.core.lang import Words

PER_KEY_LIMIT = 5
PER_KEY_WINDOW = timedelta(minutes=15)
GLOBAL_LIMIT = 50
GLOBAL_WINDOW = timedelta(hours=1)
GLOBAL_PAUSE = timedelta(minutes=15)
SLOW_AFTER = 3


@dataclass
class FailureLimiter:
    clock: Clock
    _per_key: dict[str, deque[datetime]] = field(default_factory=dict[str, deque[datetime]])
    _global: deque[datetime] = field(default_factory=deque[datetime])
    _paused_until: datetime | None = None

    def _trim(self, now: datetime) -> None:
        while self._global and now - self._global[0] > GLOBAL_WINDOW:
            self._global.popleft()
        for key in list(self._per_key):
            failures = self._per_key[key]
            while failures and now - failures[0] > PER_KEY_WINDOW:
                failures.popleft()
            if not failures:
                del self._per_key[key]

    def retry_after_seconds(self, key: str) -> int | None:
        """None if an attempt is allowed now; otherwise seconds to wait."""
        now = self.clock.now()
        self._trim(now)
        if self._paused_until and now < self._paused_until:
            return math.ceil((self._paused_until - now).total_seconds())
        failures = self._per_key.get(key)
        if failures and len(failures) >= PER_KEY_LIMIT:
            return max(1, math.ceil((failures[0] + PER_KEY_WINDOW - now).total_seconds()))
        return None

    def recent_failures(self, key: str) -> int:
        self._trim(self.clock.now())
        return len(self._per_key.get(key, ()))

    def record_failure(self, key: str) -> None:
        now = self.clock.now()
        self._per_key.setdefault(key, deque()).append(now)
        self._global.append(now)
        self._trim(now)
        if len(self._global) >= GLOBAL_LIMIT:
            self._paused_until = now + GLOBAL_PAUSE

    def record_success(self, key: str) -> None:
        self._per_key.pop(key, None)

    def reset(self) -> None:
        self._per_key.clear()
        self._global.clear()
        self._paused_until = None


def wait_words(seconds: int) -> Words:
    """How long to wait, in whole minutes: a sentence of its own for one (no plurals on the
    server, ADR 0043)."""
    minutes = max(1, round(seconds / 60))
    if minutes == 1:
        return Words("api.auth.wait_one_minute")
    return Words("api.auth.wait_minutes", {"minutes": minutes})
