"""Cost caps that live in the app: per-user limits, and a global daily cap with a ladder.

    guard = CostGuard.from_env()
    verdict = guard.check(user_id, estimate_usd)    # BEFORE the call
    ...
    guard.record(user_id, real_cost_usd)            # AFTER the call

Two kinds of per-user limit:
  - a RATE limit counts requests      (USER_PER_MINUTE, default 10 a minute): stops floods and scripts
  - a SPEND limit counts rupees        (USER_DAILY_INR, default ₹20 a day): catches huge messages
Over either one, the app answers 429 with a Retry-After header.

And one GLOBAL daily cap (GLOBAL_DAILY_INR, default ₹36,000), with a ladder, not a cliff:
   80%  alert   the team gets a log line (once a day), nothing changes for users
   90%  degrade the small model, shorter answers
  100%  lite    no new model calls: order status from the database, FAQs, a way to reach a human

The counters here are in memory, so they're right for ONE copy of the app. With more copies,
keep them in a shared store like Redis (ElastiCache or Valkey), with the same logic.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

from shopkart.pricing import USD_TO_INR

ALERT_AT, DEGRADE_AT, LITE_AT = 0.80, 0.90, 1.00


@dataclass
class Verdict:
    allowed: bool
    mode: str = "normal"            # normal | degraded | lite
    reason: str | None = None       # why a request was refused: rate_limit | user_daily_spend
    retry_after_s: int | None = None


@dataclass
class CostGuard:
    user_per_minute: int = 10
    user_daily_usd: float = 20 / USD_TO_INR
    global_daily_usd: float = 36_000 / USD_TO_INR
    clock: callable = time.time
    _day: str = ""
    _global_usd: float = 0.0
    _user_usd: dict = field(default_factory=lambda: defaultdict(float))
    _user_calls: dict = field(default_factory=lambda: defaultdict(deque))
    _alerted: bool = False
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @classmethod
    def from_env(cls) -> CostGuard:
        inr = lambda name, default: float(os.environ.get(name, default)) / USD_TO_INR  # noqa: E731
        return cls(user_per_minute=int(os.environ.get("USER_PER_MINUTE", "10")),
                   user_daily_usd=inr("USER_DAILY_INR", "20"),
                   global_daily_usd=inr("GLOBAL_DAILY_INR", "36000"))

    # ---- the day rolls over at midnight UTC: counters start again -----------

    def _today(self) -> None:
        day = datetime.fromtimestamp(self.clock(), timezone.utc).date().isoformat()
        if day != self._day:
            self._day, self._global_usd, self._alerted = day, 0.0, False
            self._user_usd.clear()
            self._user_calls.clear()

    def _seconds_to_midnight(self) -> int:
        now = self.clock()
        return int(86_400 - now % 86_400) + 1

    # ---- the global ladder ---------------------------------------------------

    def share_used(self) -> float:
        # rounded, so 79 + 1 rupees of a 100 rupee cap is 80%, not 79.99999%
        return round(self._global_usd / self.global_daily_usd, 9) if self.global_daily_usd else 1.0

    def mode(self) -> str:
        self._today()
        used = self.share_used()
        return "lite" if used >= LITE_AT else "degraded" if used >= DEGRADE_AT else "normal"

    # ---- before and after each call ------------------------------------------

    def check(self, user_id: str, estimate_usd: float) -> Verdict:
        """BEFORE a call. `estimate_usd` is the worst case: input tokens plus max_tokens out."""
        with self._lock:
            self._today()
            now = self.clock()
            calls = self._user_calls[user_id]
            while calls and calls[0] <= now - 60:
                calls.popleft()
            if len(calls) >= self.user_per_minute:
                return Verdict(False, self.mode(), "rate_limit", int(calls[0] + 60 - now) + 1)
            if self._user_usd[user_id] + estimate_usd > self.user_daily_usd:
                return Verdict(False, self.mode(), "user_daily_spend", self._seconds_to_midnight())
            calls.append(now)
            return Verdict(True, self.mode())

    def record(self, user_id: str, cost_usd: float) -> str | None:
        """AFTER a call: add the REAL cost. Returns "budget_alert" the first time spend passes 80%."""
        with self._lock:
            self._today()
            self._user_usd[user_id] += cost_usd
            self._global_usd += cost_usd
            if not self._alerted and self.share_used() >= ALERT_AT:
                self._alerted = True
                return "budget_alert"
        return None

    def status(self) -> dict:
        with self._lock:
            self._today()
            return {"day": self._day, "mode": self.mode(),
                    "spent_inr": round(self._global_usd * USD_TO_INR, 4),
                    "cap_inr": round(self.global_daily_usd * USD_TO_INR, 4),
                    "used": f"{self.share_used():.0%}", "users_today": len(self._user_usd)}
