from typing import Dict, List
from requests import RequestException
from .security_layer import SecurityLayer, SecurityViolationError


class RateLimitEngine:
    def __init__(
        self,
        api_endpoints: List[str],
        security_layer: SecurityLayer | None = None,
        max_requests: int = 1,
    ):
        if api_endpoints is None or not isinstance(api_endpoints, list):
            raise TypeError("api_endpoints must be a list of URL strings")
        if max_requests <= 0:
            raise ValueError("max_requests must be greater than 0")
        self.api_endpoints = api_endpoints
        self.security_layer = security_layer or SecurityLayer()
        self.max_requests = max_requests
        self.rate_limits: Dict[str, int] = {
            str(ep).strip() if isinstance(ep, str) else str(ep): max_requests
            for ep in api_endpoints
        }

    def check_rate_limit(self, endpoint: str) -> bool:
        key = str(endpoint).strip() if isinstance(endpoint, str) else str(endpoint)
        if self.rate_limits.get(key, 0) > 0:
            self.rate_limits[key] -= 1
            return True
        return False

    def reset_rate_limit(self, endpoint: str) -> None:
        key = str(endpoint).strip() if isinstance(endpoint, str) else str(endpoint)
        self.rate_limits[key] = self.max_requests

    def audit(self) -> Dict[str, List[str]]:
        results: Dict[str, List[str]] = {}
        for endpoint in self.api_endpoints:
            key = str(endpoint).strip() if isinstance(endpoint, str) else str(endpoint)
            try:
                if not self.check_rate_limit(key):
                    results[key] = ["Rate limit exceeded"]
                    continue
                status = self.security_layer.check_endpoint(endpoint)
                if status == 429:
                    self.rate_limits[key] = 0
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
