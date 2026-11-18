from dataclasses import dataclass

from fastapi import Request

from core.circuit_breaker import CircuitBreaker
from core.circuit_breaker import CircuitBreaker
from core.rate_limit_engine import RateLimitEngine


DEMO_RATE_ENDPOINT = "demo://rate-limiter"
DEMO_CIRCUIT_ENDPOINT = "demo://downstream-service"


@dataclass(frozen=True)
class DemoConfig:
    rate_limit_capacity: int = 5
    rate_limit_refill_rate_per_second: float = 0.5
    circuit_failure_threshold: int = 2
    circuit_recovery_timeout_seconds: float = 5.0
    circuit_half_open_max_calls: int = 1


@dataclass
class DemoState:
    rate_limiter: RateLimitEngine
    circuit_breaker: CircuitBreaker
    config: DemoConfig


def build_demo_state(config: DemoConfig | None = None) -> DemoState:
    """Build independent in-memory state for the browser demonstration.

    The demo endpoint identifiers are local keys only. No audit method is
    called, and the simulated downstream service never performs HTTP requests.
    """
    selected = config or DemoConfig()
    rate_limiter = RateLimitEngine(
        [DEMO_RATE_ENDPOINT],
        max_requests=selected.rate_limit_capacity,
        refill_rate_per_second=selected.rate_limit_refill_rate_per_second,
    )
    circuit_breaker = CircuitBreaker(
        [DEMO_CIRCUIT_ENDPOINT],
        failure_threshold=selected.circuit_failure_threshold,
        recovery_timeout=selected.circuit_recovery_timeout_seconds,
        half_open_max_calls=selected.circuit_half_open_max_calls,
    )
    return DemoState(
        rate_limiter=rate_limiter,
        circuit_breaker=circuit_breaker,
        config=selected,
    )


def get_demo_state(request: Request) -> DemoState:
    return request.app.state.demo_state
