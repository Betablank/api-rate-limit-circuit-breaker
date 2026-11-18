from datetime import datetime, timezone
from math import ceil

from fastapi import APIRouter, Depends, HTTPException, Response, status

from core.circuit_breaker import CircuitBreaker
from .dependencies import (
    DEMO_CIRCUIT_ENDPOINT,
    DEMO_RATE_ENDPOINT,
    DemoState,
    get_demo_state,
)
from .schemas import (
    ApplicationInfoResponse,
    CircuitBreakerRequest,
    CircuitBreakerResponse,
    CircuitBreakerStatusResponse,
    HealthResponse,
    RateLimitDemoResponse,
    RateLimitRequest,
    RateLimitStatusResponse,
    ResetResponse,
)


router = APIRouter()
APP_NAME = "API Rate-Limit & Circuit-Breaker Resilience Engine"
APP_DESCRIPTION = (
    "Interactive demonstration of API resilience patterns, token-bucket "
    "rate limiting, and circuit-breaker state transitions."
)
APP_VERSION = "1.0.0"


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rate_headers(snapshot: dict) -> dict[str, str]:
    return {
        "X-RateLimit-Limit": str(snapshot["limit"]),
        "X-RateLimit-Remaining": str(snapshot["remaining"]),
    }


def _circuit_status(breaker: CircuitBreaker) -> dict:
    return breaker.get_status(DEMO_CIRCUIT_ENDPOINT)


def _run_simulated_downstream(state: DemoState, simulate_failure: bool) -> CircuitBreakerResponse:
    breaker = state.circuit_breaker
    allowed = breaker.check_circuit_breaker(DEMO_CIRCUIT_ENDPOINT)
    current = _circuit_status(breaker)

    if not allowed:
        retry_seconds = current.get("remaining_recovery_seconds")
        headers = {"X-Circuit-Breaker-State": current["state"]}
        if retry_seconds is not None:
            headers["Retry-After"] = str(max(1, ceil(retry_seconds)))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Circuit breaker rejected the request; simulated downstream was not called.",
                "state": current["state"],
                "failure_count": current["failure_count"],
            },
            headers=headers,
        )

    if simulate_failure:
        breaker.record_failure(DEMO_CIRCUIT_ENDPOINT)
        current = _circuit_status(breaker)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "message": "Controlled simulated downstream failure.",
                "state": current["state"],
                "failure_count": current["failure_count"],
            },
            headers={"X-Circuit-Breaker-State": current["state"]},
        )

    breaker.record_success(DEMO_CIRCUIT_ENDPOINT)
    current = _circuit_status(breaker)
    return CircuitBreakerResponse(
        success=True,
        state=current["state"],
        message="Simulated downstream request succeeded.",
        timestamp=_timestamp(),
    )


@router.get("/", response_model=ApplicationInfoResponse, tags=["system"])
def application_info() -> ApplicationInfoResponse:
    return ApplicationInfoResponse(
        name=APP_NAME,
        description=APP_DESCRIPTION,
        version=APP_VERSION,
        docs="/docs",
        redoc="/redoc",
        features=[
            "Token-bucket rate-limit demonstration",
            "HTTP 429 responses and rate-limit headers",
            "Circuit-breaker CLOSED, OPEN, and HALF_OPEN transitions",
            "Controlled local downstream failures and recovery",
        ],
    )


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    return HealthResponse(status="ok", service=APP_NAME, demo_mode=True)


@router.post(
    "/demo/rate-limit/request",
    response_model=RateLimitDemoResponse,
    tags=["rate limiter"],
    summary="Consume one token from the demonstration bucket",
    responses={429: {
        "description": "The token bucket is empty; retry after the indicated delay.",
        "content": {"application/json": {"example": {"detail": {
            "message": "Rate limit exceeded. Wait for a token to refill or reset the demo.",
            "retry_after_seconds": 2.0, "limit": 5, "remaining": 0
        }}}},
    }},
)
def rate_limit_request(
    payload: RateLimitRequest,
    response: Response,
    state: DemoState = Depends(get_demo_state),
) -> RateLimitDemoResponse:
    accepted = state.rate_limiter.check_rate_limit(DEMO_RATE_ENDPOINT)
    snapshot = state.rate_limiter.get_rate_limit_status(DEMO_RATE_ENDPOINT)
    headers = _rate_headers(snapshot)
    response.headers.update(headers)

    if not accepted:
        retry_seconds = snapshot.get("retry_after_seconds") or 1.0
        retry_after = max(1, ceil(retry_seconds))
        headers["Retry-After"] = str(retry_after)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "message": "Rate limit exceeded. Wait for a token to refill or reset the demo.",
                "retry_after_seconds": retry_seconds,
                "limit": snapshot["limit"],
                "remaining": snapshot["remaining"],
            },
            headers=headers,
        )

    return RateLimitDemoResponse(
        accepted=True,
        timestamp=_timestamp(),
        label=payload.label,
        limit=snapshot["limit"],
        remaining=snapshot["remaining"],
        available_tokens=snapshot["available_tokens"],
        refill_rate_per_second=snapshot["refill_rate_per_second"],
    )


@router.get(
    "/demo/rate-limit/status",
    response_model=RateLimitStatusResponse,
    tags=["rate limiter"],
    summary="Inspect the current demonstration token bucket",
)
def rate_limit_status(state: DemoState = Depends(get_demo_state)) -> RateLimitStatusResponse:
    snapshot = state.rate_limiter.get_rate_limit_status(DEMO_RATE_ENDPOINT)
    return RateLimitStatusResponse(**snapshot)


@router.post("/demo/rate-limit/reset", response_model=ResetResponse, tags=["rate limiter"])
def reset_rate_limit(state: DemoState = Depends(get_demo_state)) -> ResetResponse:
    state.rate_limiter.reset_rate_limit(DEMO_RATE_ENDPOINT)
    return ResetResponse(reset=True, message="Demonstration token bucket refilled to capacity.")


@router.post(
    "/demo/circuit-breaker/request",
    response_model=CircuitBreakerResponse,
    tags=["circuit breaker"],
    summary="Send a request through the demonstration circuit breaker",
    responses={503: {
        "description": "The simulated downstream failed or the circuit is open.",
        "content": {"application/json": {"example": {"detail": {
            "message": "Circuit breaker rejected the request; simulated downstream was not called.",
            "state": "OPEN", "failure_count": 2
        }}}},
    }},
)
def circuit_breaker_request(
    payload: CircuitBreakerRequest,
    state: DemoState = Depends(get_demo_state),
) -> CircuitBreakerResponse:
    return _run_simulated_downstream(state, payload.simulate_failure)


@router.get(
    "/demo/circuit-breaker/status",
    response_model=CircuitBreakerStatusResponse,
    tags=["circuit breaker"],
    summary="Inspect the circuit-breaker state and configuration",
)
def circuit_breaker_status(state: DemoState = Depends(get_demo_state)) -> CircuitBreakerStatusResponse:
    return CircuitBreakerStatusResponse(**_circuit_status(state.circuit_breaker))


@router.post(
    "/demo/circuit-breaker/simulate-failure",
    response_model=CircuitBreakerResponse,
    tags=["circuit breaker"],
    summary="Record one controlled simulated downstream failure",
    responses={503: {
        "description": "Expected response for the simulated failure.",
        "content": {"application/json": {"example": {"detail": {
            "message": "Controlled simulated downstream failure.",
            "state": "OPEN", "failure_count": 2
        }}}},
    }},
)
def simulate_circuit_breaker_failure(
    state: DemoState = Depends(get_demo_state),
) -> CircuitBreakerResponse:
    return _run_simulated_downstream(state, simulate_failure=True)


@router.post("/demo/circuit-breaker/reset", response_model=ResetResponse, tags=["circuit breaker"])
def reset_circuit_breaker(state: DemoState = Depends(get_demo_state)) -> ResetResponse:
    state.circuit_breaker.reset(DEMO_CIRCUIT_ENDPOINT)
    return ResetResponse(reset=True, message="Circuit breaker reset to CLOSED.", status="CLOSED")
