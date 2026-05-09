"""
Provider health monitor.

--- Header Doc ---
Purpose: Track provider health and apply lightweight circuit-breaker behavior.
Caller: provider router.
Dependencies: dataclasses, datetime.
Main Functions: HealthMonitor.record_success/failure/is_available.
Side Effects: In-memory state mutation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict


@dataclass
class ProviderHealthState:
    consecutive_failures: int = 0
    unavailable_until: datetime | None = None


class HealthMonitor:
    def __init__(self, failure_threshold: int = 3, cooldown_seconds: int = 60):
        self.failure_threshold = max(1, failure_threshold)
        self.cooldown_seconds = max(1, cooldown_seconds)
        self._states: Dict[str, ProviderHealthState] = {}

    def _state(self, provider_id: str) -> ProviderHealthState:
        if provider_id not in self._states:
            self._states[provider_id] = ProviderHealthState()
        return self._states[provider_id]

    def record_success(self, provider_id: str) -> None:
        st = self._state(provider_id)
        st.consecutive_failures = 0
        st.unavailable_until = None

    def record_failure(self, provider_id: str) -> None:
        st = self._state(provider_id)
        st.consecutive_failures += 1
        if st.consecutive_failures >= self.failure_threshold:
            st.unavailable_until = datetime.now(timezone.utc) + timedelta(seconds=self.cooldown_seconds)

    def is_available(self, provider_id: str) -> bool:
        st = self._state(provider_id)
        if st.unavailable_until is None:
            return True
        return datetime.now(timezone.utc) >= st.unavailable_until
