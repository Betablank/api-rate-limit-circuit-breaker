import math
import threading
import time
from typing import Dict, List, Optional

from requests import RequestException

from .security_layer import SecurityLayer, SecurityViolationError


class RateLimitEngine:
    """Per-endpoint request limiter with an optional token-refill mode.

    The default ``refill_rate_per_second=None`` preserves the original fixed
    request-counter behavior. Supplying a refill rate enables token-bucket
    behavior without changing the existing ``check_rate_limit`` interface.
    """

    def __init__(
        self,
        api_endpoints: List[str],
        security_layer: Optional[SecurityLayer] = None,
        max_requests: int = 1,
        refill_rate_per_second: Optional[float] = None,
    ):
        if api_endpoints is None or not isinstance(api_endpoints, list):
            raise TypeError("api_endpoints must be a list of URL strings")
        if max_requests <= 0:
            raise ValueError("max_requests must be greater than 0")
        if refill_rate_per_second is not None and refill_rate_per_second <= 0:
            raise ValueError("refill_rate_per_second must be greater than 0")

        self.api_endpoints = api_endpoints
        self.security_layer = security_layer or SecurityLayer()
        self.max_requests = max_requests
        self.refill_rate_per_second = refill_rate_per_second
        self._lock = threading.RLock()
        self.rate_limits: Dict[str, int] = {
            self._key(endpoint): max_requests for endpoint in api_endpoints
        }
        now = time.monotonic()
        self._token_buckets: Dict[str, Dict[str, float]] = {}
        if refill_rate_per_second is not None:
            self._token_buckets = {
                self._key(endpoint): {"tokens": float(max_requests), "updated_at": now}
                for endpoint in api_endpoints
            }

    @staticmethod
    def _key(endpoint: str) -> str:
        return str(endpoint).strip() if isinstance(endpoint, str) else str(endpoint)

    def _refill_bucket_locked(
        self, key: str, now: Optional[float] = None
    ) -> Optional[Dict[str, float]]:
        bucket = self._token_buckets.get(key)
        if bucket is None or self.refill_rate_per_second is None:
            return bucket
        current_time = time.monotonic() if now is None else now
        elapsed = max(0.0, current_time - bucket["updated_at"])
        bucket["tokens"] = min(
            float(self.max_requests),
            bucket["tokens"] + elapsed * self.refill_rate_per_second,
        )
        bucket["updated_at"] = current_time
        self.rate_limits[key] = int(math.floor(bucket["tokens"] + 1e-12))
        return bucket

    def check_rate_limit(self, endpoint: str) -> bool:
        key = self._key(endpoint)
        with self._lock:
            if self.refill_rate_per_second is None:
                if self.rate_limits.get(key, 0) > 0:
                    self.rate_limits[key] -= 1
                    return True
                return False

            bucket = self._refill_bucket_locked(key)
            if bucket is None:
                return False
            if bucket["tokens"] >= 1.0:
                bucket["tokens"] -= 1.0
                self.rate_limits[key] = int(math.floor(bucket["tokens"] + 1e-12))
                return True
            self.rate_limits[key] = 0
            return False

    def get_rate_limit_status(self, endpoint: str) -> Dict[str, object]:
        """Return an accurate snapshot without consuming a request token."""
        key = self._key(endpoint)
        with self._lock:
            if self.refill_rate_per_second is None:
                remaining = max(0, self.rate_limits.get(key, 0))
                return {
                    "limit": self.max_requests,
                    "remaining": remaining,
                    "available_tokens": float(remaining),
                    "refill_rate_per_second": None,
                    "retry_after_seconds": None,
                }

            bucket = self._refill_bucket_locked(key)
            tokens = bucket["tokens"] if bucket is not None else 0.0
            remaining = int(math.floor(tokens + 1e-12))
            retry_after = max(0.0, (1.0 - tokens) / self.refill_rate_per_second)
            return {
                "limit": self.max_requests,
                "remaining": remaining,
                "available_tokens": round(tokens, 6),
                "refill_rate_per_second": self.refill_rate_per_second,
                "retry_after_seconds": round(retry_after, 6),
            }

    def reset_rate_limit(self, endpoint: str) -> None:
        key = self._key(endpoint)
        with self._lock:
            self.rate_limits[key] = self.max_requests
            if self.refill_rate_per_second is not None:
                self._token_buckets[key] = {
                    "tokens": float(self.max_requests),
                    "updated_at": time.monotonic(),
                }

    def audit(self) -> Dict[str, List[str]]:
        results: Dict[str, List[str]] = {}
        for endpoint in self.api_endpoints:
            key = self._key(endpoint)
            try:
                if not self.check_rate_limit(key):
                    results[key] = ["Rate limit exceeded"]
                    continue
                status = self.security_layer.check_endpoint(endpoint)
                if status == 429:
                    with self._lock:
                        self.rate_limits[key] = 0
                        bucket = self._token_buckets.get(key)
                        if bucket is not None:
                            bucket["tokens"] = 0.0
                            bucket["updated_at"] = time.monotonic()
                    results[key] = ["Upstream rate limit triggered (HTTP 429)"]
                else:
                    results[key] = ["No rate limit issues"]
            except SecurityViolationError as exc:
                results[key] = [f"Security violation: {str(exc)}"]
            except RequestException as exc:
                results[key] = [str(exc)]
            except (ValueError, TypeError) as exc:
                results[key] = [f"Validation error: {str(exc)}"]
            except Exception as exc:
                results[key] = [f"Unexpected error: {str(exc)}"]
        return results
