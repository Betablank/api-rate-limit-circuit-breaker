from typing import Dict, List
from core.rate_limit_engine import RateLimitEngine
from core.circuit_breaker import CircuitBreaker
from core.security_layer import SecurityLayer


class APIRateLimitAPI:
    def __init__(self, api_endpoints: List[str]):
        layer = SecurityLayer()
        self.rate_limit_engine = RateLimitEngine(api_endpoints, layer)
        self.circuit_breaker = CircuitBreaker(api_endpoints, layer)

    def audit(self) -> Dict[str, List[str]]:
        rate_limit_results = self.rate_limit_engine.audit()
        circuit_breaker_results = self.circuit_breaker.audit()
        combined: Dict[str, List[str]] = {}
        for endpoint, issues in rate_limit_results.items():
            combined.setdefault(endpoint, []).extend(issues)
        for endpoint, issues in circuit_breaker_results.items():
            combined.setdefault(endpoint, []).extend(issues)
        return combined
