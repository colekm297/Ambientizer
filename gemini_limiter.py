"""
gemini_limiter.py — Local rate limiter for Gemini API calls.

Google doesn't expose a "remaining quota" API like ElevenLabs does.
Instead we track our own usage (RPM / RPD) locally and enforce limits
before calling the API.  When a 429 is returned we back off and retry.

Usage:
    from gemini_limiter import gemini_limiter
    gemini_limiter.wait_if_needed()          # blocks until safe to call
    gemini_limiter.record_call("ref_analysis")
"""

import json
import time
import threading
from pathlib import Path
from collections import deque

_LIMITER_DIR = Path("generated_samples")
_LIMITER_DIR.mkdir(parents=True, exist_ok=True)

# Paid Tier 1 defaults (Gemini 2.5 Pro).
# Override via POST /api/gemini-limits or set_limits().
_DEFAULT_RPM = 150      # requests per minute (Pro tier 1)
_DEFAULT_RPD = 1000     # requests per day (Pro tier 1)


class _GeminiRateLimiter:
    def __init__(self):
        self._lock = threading.Lock()
        self._rpm_limit = _DEFAULT_RPM
        self._rpd_limit = _DEFAULT_RPD
        self._recent_calls: deque = deque()   # timestamps of calls within last 60s
        self._daily_log_path = _LIMITER_DIR / "_gemini_daily.json"
        self._daily = self._load_daily()

    def set_limits(self, rpm: int | None = None, rpd: int | None = None):
        with self._lock:
            if rpm is not None:
                self._rpm_limit = rpm
            if rpd is not None:
                self._rpd_limit = rpd

    def _load_daily(self) -> dict:
        today = time.strftime("%Y-%m-%d")
        try:
            raw = json.loads(self._daily_log_path.read_text())
            if raw.get("date") == today:
                return raw
        except (FileNotFoundError, json.JSONDecodeError, KeyError):
            pass
        return {"date": today, "calls": 0}

    def _save_daily(self):
        try:
            self._daily_log_path.write_text(json.dumps(self._daily))
        except OSError:
            pass

    def _prune_old(self):
        cutoff = time.time() - 60
        while self._recent_calls and self._recent_calls[0] < cutoff:
            self._recent_calls.popleft()

    def get_usage(self) -> dict:
        """Return current usage stats for display in the UI."""
        with self._lock:
            self._prune_old()
            daily = self._load_daily()
            return {
                "rpm_used": len(self._recent_calls),
                "rpm_limit": self._rpm_limit,
                "rpd_used": daily["calls"],
                "rpd_limit": self._rpd_limit,
            }

    def wait_if_needed(self, timeout: float = 120.0) -> bool:
        """
        Block until we're under both RPM and RPD limits.
        Returns True if safe to proceed, False if timed out or daily limit hit.
        """
        deadline = time.time() + timeout
        with self._lock:
            self._daily = self._load_daily()
            if self._daily["calls"] >= self._rpd_limit:
                print(f"  [gemini] Daily limit reached ({self._daily['calls']}/{self._rpd_limit} RPD). "
                      f"Resets at midnight Pacific.", flush=True)
                return False

        while time.time() < deadline:
            with self._lock:
                self._prune_old()
                if len(self._recent_calls) < self._rpm_limit:
                    return True
            wait = max(0.5, 60 - (time.time() - self._recent_calls[0]) + 0.5)
            wait = min(wait, deadline - time.time())
            if wait <= 0:
                return False
            print(f"  [gemini] Rate limit: {len(self._recent_calls)}/{self._rpm_limit} RPM, "
                  f"waiting {wait:.0f}s...", flush=True)
            time.sleep(wait)

        return False

    def record_call(self, label: str = ""):
        """Record that we just made a Gemini API call."""
        with self._lock:
            now = time.time()
            self._recent_calls.append(now)
            self._daily = self._load_daily()
            self._daily["calls"] += 1
            self._save_daily()
            rpm_used = len(self._recent_calls)
            rpd_used = self._daily["calls"]
        tag = f" ({label})" if label else ""
        print(f"  [gemini] Call recorded{tag} | "
              f"RPM: {rpm_used}/{self._rpm_limit} | "
              f"RPD: {rpd_used}/{self._rpd_limit}", flush=True)

    def handle_429(self, attempt: int = 1) -> float:
        """
        Called when we get a 429. Returns the delay to wait (seconds).
        Uses exponential backoff: 15s, 30s, 60s.
        """
        delay = min(15 * (2 ** (attempt - 1)), 60)
        print(f"  [gemini] 429 rate-limited, backing off {delay}s (attempt {attempt})...", flush=True)
        return delay


# Singleton
gemini_limiter = _GeminiRateLimiter()
