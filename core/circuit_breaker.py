import threading
import time
from typing import Dict, List, Optional

from requests import RequestException

from .security_layer import SecurityLayer, SecurityViolationError


class CircuitBreaker:
    """Thread-safe circuit breaker with optional timed half-open recovery.

    With the default ``recovery_timeout=None``, an open circuit continues to
    require an explicit ``reset`` just as it did before this extension.
    """

    def __init__(
        self,
        api_endpoints: List[str],
        security_layer: Optional[SecurityLayer] = None,
        failure_threshold: int = 1,
        recovery_timeout: Optional[float] = None,
        half_open_max_calls: int = 1,
        success_threshold: int = 1,
    ):
        if api_endpoints is None or not isinstance(api_endpoints, list):
            raise TypeError("api_endpoints must be a list of URL strings")
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be greater than 0")
        if recovery_timeout is not None and recovery_timeout <= 0:
            raise ValueError("recovery_timeout must be greater than 0")
        if half_open_max_calls <= 0:
            raise ValueError("half_open_max_calls must be greater than 0")
        if success_threshold <= 0:
            raise ValueError("success_threshold must be greater than 0")
        if success_threshold > half_open_max_calls:
            raise ValueError("success_threshold cannot exceed half_open_max_calls")

        self.api_endpoints = api_endpoints
        self.security_layer = security_layer or SecurityLayer()
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.success_threshold = success_threshold
        self._lock = threading.RLock()
        self.failures: Dict[str, int] = {self._key(ep): 0 for ep in api_endpoints}
        self.open_state: Dict[str, bool] = {self._key(ep): False for ep in api_endpoints}
        self._states: Dict[str, str] = {self._key(ep): "CLOSED" for ep in api_endpoints}
        self._opened_at: Dict[str, Optional[float]] = {self._key(ep): None for ep in api_endpoints}
        self._half_open_in_flight: Dict[str, int] = {self._key(ep): 0 for ep in api_endpoints}
        self._half_open_successes: Dict[str, int] = {self._key(ep): 0 for ep in api_endpoints}

    @staticmethod
    def _key(endpoint: str) -> str:
        return str(endpoint).strip() if isinstance(endpoint, str) else str(endpoint)

    def _refresh_state_locked(self, key: str, now: Optional[float] = None) -> str:
        state = self._states.get(key, "CLOSED")
        opened_at = self._opened_at.get(key)
        current_time = time.monotonic() if now is None else now
        if (
            state == "OPEN"
            and self.recovery_timeout is not None
            and opened_at is not None
            and current_time - opened_at >= self.recovery_timeout
        ):
            self._states[key] = "HALF_OPEN"
            self.open_state[key] = False
            self._half_open_in_flight[key] = 0
            self._half_open_successes[key] = 0
        return self._states.get(key, "CLOSED")

    def check_circuit_breaker(self, endpoint: str) -> bool:
        key = self._key(endpoint)
        with self._lock:
            state = self._refresh_state_locked(key)
            if state == "OPEN":
                return False
            if state == "HALF_OPEN":
                in_flight = self._half_open_in_flight.get(key, 0)
                if in_flight >= self.half_open_max_calls:
                    return False
                self._half_open_in_flight[key] = in_flight + 1
            return True

    def record_failure(self, endpoint: str) -> None:
        key = self._key(endpoint)
        with self._lock:
            state = self._refresh_state_locked(key)
            if state == "OPEN":
                return
            self.failures[key] = self.failures.get(key, 0) + 1
            if state == "HALF_OPEN" or self.failures[key] >= self.failure_threshold:
                self._states[key] = "OPEN"
                self.open_state[key] = True
                self._opened_at[key] = time.monotonic()
                self._half_open_in_flight[key] = 0
                self._half_open_successes[key] = 0
    def cancel_half_open_probe(self, endpoint: str) -> None:
        """Release a reserved probe when validation fails before downstream work."""
        key = self._key(endpoint)
        with self._lock:
            if self._refresh_state_locked(key) == "HALF_OPEN":
                self._half_open_in_flight[key] = max(
                    0, self._half_open_in_flight.get(key, 0) - 1
                )

    def record_success(self, endpoint: str) -> None:
        key = self._key(endpoint)
        with self._lock:
            state = self._refresh_state_locked(key)
            if state == "HALF_OPEN":
                self._half_open_in_flight[key] = max(0, self._half_open_in_flight.get(key, 0) - 1)
                self._half_open_successes[key] = self._half_open_successes.get(key, 0) + 1
                if self._half_open_successes[key] >= self.success_threshold:
                    self._states[key] = "CLOSED"
                    self.open_state[key] = False
                    self.failures[key] = 0
                    self._opened_at[key] = None
                    self._half_open_in_flight[key] = 0
                    self._half_open_successes[key] = 0
            elif state == "CLOSED":
                self.failures[key] = 0

    def get_status(self, endpoint: str) -> Dict[str, object]:
        key = self._key(endpoint)
        with self._lock:
            state = self._refresh_state_locked(key)
            remaining = None
            if state == "OPEN" and self.recovery_timeout is not None:
                opened_at = self._opened_at.get(key)
                elapsed = (
                    time.monotonic() - opened_at if opened_at is not None else 0.0
                )
                remaining = max(0.0, self.recovery_timeout - elapsed)
            return {
                "state": state,
                "failure_count": self.failures.get(key, 0),
                "failure_threshold": self.failure_threshold,
                "recovery_timeout_seconds": self.recovery_timeout,
                "remaining_recovery_seconds": round(remaining, 6) if remaining is not None else None,
                "half_open_max_calls": self.half_open_max_calls,
                "half_open_calls_in_flight": self._half_open_in_flight.get(key, 0),
                "half_open_success_threshold": self.success_threshold,
            }

    def reset(self, endpoint: str) -> None:
        key = self._key(endpoint)
        with self._lock:
            self.failures[key] = 0
            self.open_state[key] = False
            self._states[key] = "CLOSED"
            self._opened_at[key] = None
            self._half_open_in_flight[key] = 0
            self._half_open_successes[key] = 0

    def audit(self) -> Dict[str, List[str]]:
        results: Dict[str, List[str]] = {}
        for endpoint in self.api_endpoints:
            key = self._key(endpoint)
            try:
                if not self.check_circuit_breaker(key):
                    results[key] = ["Circuit breaker is open"]
                    continue
                self.security_layer.check_endpoint(endpoint)
                self.record_success(key)
                results[key] = ["No circuit breaker issues"]
            except SecurityViolationError as exc:
                self.cancel_half_open_probe(key)
                results[key] = [f"Security violation: {str(exc)}"]
            except RequestException as exc:
                self.record_failure(key)
                results[key] = [str(exc)]
            except (ValueError, TypeError) as exc:
                self.cancel_half_open_probe(key)
                results[key] = [f"Validation error: {str(exc)}"]
            except Exception as exc:
                self.record_failure(key)
                results[key] = [f"Unexpected error: {str(exc)}"]
        return results
