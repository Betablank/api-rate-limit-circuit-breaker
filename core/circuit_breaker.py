from typing import Dict, List
from requests import RequestException
from .security_layer import SecurityLayer, SecurityViolationError


class CircuitBreaker:
    def __init__(
        self,
        api_endpoints: List[str],
        security_layer: SecurityLayer | None = None,
        failure_threshold: int = 1,
    ):
        if api_endpoints is None or not isinstance(api_endpoints, list):
            raise TypeError("api_endpoints must be a list of URL strings")
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be greater than 0")
        self.api_endpoints = api_endpoints
        self.security_layer = security_layer or SecurityLayer()
        self.failure_threshold = failure_threshold
        self.failures: Dict[str, int] = {
            str(ep).strip() if isinstance(ep, str) else str(ep): 0 for ep in api_endpoints
        }
        self.open_state: Dict[str, bool] = {
            str(ep).strip() if isinstance(ep, str) else str(ep): False for ep in api_endpoints
        }

    def check_circuit_breaker(self, endpoint: str) -> bool:
        key = str(endpoint).strip() if isinstance(endpoint, str) else str(endpoint)
        return not self.open_state.get(key, False)

    def record_failure(self, endpoint: str) -> None:
        key = str(endpoint).strip() if isinstance(endpoint, str) else str(endpoint)
        self.failures[key] = self.failures.get(key, 0) + 1
        if self.failures[key] >= self.failure_threshold:
            self.open_state[key] = True

    def reset(self, endpoint: str) -> None:
        key = str(endpoint).strip() if isinstance(endpoint, str) else str(endpoint)
        self.failures[key] = 0
        self.open_state[key] = False

    def audit(self) -> Dict[str, List[str]]:
        results: Dict[str, List[str]] = {}
        for endpoint in self.api_endpoints:
            key = str(endpoint).strip() if isinstance(endpoint, str) else str(endpoint)
            try:
                if not self.check_circuit_breaker(key):
                    results[key] = ["Circuit breaker is open"]
                    continue
                self.security_layer.check_endpoint(endpoint)
                self.reset(key)
                results[key] = ["No circuit breaker issues"]
            except SecurityViolationError as exc:
                results[key] = [f"Security violation: {str(exc)}"]
            except RequestException as exc:
                self.record_failure(key)
                results[key] = [str(exc)]
            except (ValueError, TypeError) as exc:
                results[key] = [f"Validation error: {str(exc)}"]
            except Exception as exc:
                self.record_failure(key)
                results[key] = [f"Unexpected error: {str(exc)}"]
        return results
