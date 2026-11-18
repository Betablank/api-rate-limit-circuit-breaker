from concurrent.futures import ThreadPoolExecutor
import time

import pytest
from fastapi.testclient import TestClient

from core.circuit_breaker import CircuitBreaker
from core.rate_limit_engine import RateLimitEngine
from web.app import create_app
from web.dependencies import DemoConfig


@pytest.fixture
def client():
    app = create_app(
        DemoConfig(
            rate_limit_capacity=2,
            rate_limit_refill_rate_per_second=0.01,
            circuit_failure_threshold=2,
            circuit_recovery_timeout_seconds=0.05,
            circuit_half_open_max_calls=1,
        )
    )
    with TestClient(app) as test_client:
        yield test_client


def test_root_health_and_documentation(client):
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["docs"] == "/docs"
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "API Rate-Limit & Circuit-Breaker Resilience Engine"
    assert schema["paths"]["/demo/rate-limit/request"]["post"]["responses"]["429"]["content"]["application/json"]["example"]
    request_schema = schema["components"]["schemas"]["RateLimitRequest"]
    assert request_schema["examples"][0]["label"] == "browser-demo"


def test_rate_limit_accepts_then_returns_429_with_headers_and_reset(client):
    first = client.post("/demo/rate-limit/request", json={"label": "first"})
    second = client.post("/demo/rate-limit/request", json={})
    blocked = client.post("/demo/rate-limit/request", json={})

    assert first.status_code == 200
    assert first.json()["remaining"] == 1
    assert second.status_code == 200
    assert second.json()["remaining"] == 0
    assert blocked.status_code == 429
    assert blocked.headers["X-RateLimit-Limit"] == "2"
    assert blocked.headers["X-RateLimit-Remaining"] == "0"
    assert int(blocked.headers["Retry-After"]) >= 1

    reset = client.post("/demo/rate-limit/reset")
    assert reset.status_code == 200
    assert client.get("/demo/rate-limit/status").json()["remaining"] == 2
    assert client.post("/demo/rate-limit/request", json={}).status_code == 200


def test_rate_limit_refills_tokens(client):
    client.post("/demo/rate-limit/request", json={})
    client.post("/demo/rate-limit/request", json={})
    time.sleep(0.12)
    response = client.get("/demo/rate-limit/status")
    assert response.status_code == 200
    assert response.json()["available_tokens"] > 0


def test_circuit_breaker_opens_rejects_and_recovers_to_closed(client):
    assert client.get("/demo/circuit-breaker/status").json()["state"] == "CLOSED"
    assert client.post("/demo/circuit-breaker/request", json={}).status_code == 200

    assert client.post("/demo/circuit-breaker/simulate-failure").status_code == 503
    opened = client.post("/demo/circuit-breaker/simulate-failure")
    assert opened.status_code == 503
    assert client.get("/demo/circuit-breaker/status").json()["state"] == "OPEN"

    rejected = client.post("/demo/circuit-breaker/request", json={})
    assert rejected.status_code == 503
    assert "not called" in rejected.json()["detail"]["message"]

    time.sleep(0.07)
    assert client.get("/demo/circuit-breaker/status").json()["state"] == "HALF_OPEN"
    recovered = client.post("/demo/circuit-breaker/request", json={})
    assert recovered.status_code == 200
    assert recovered.json()["state"] == "CLOSED"


def test_circuit_breaker_failure_during_half_open_reopens(client):
    client.post("/demo/circuit-breaker/simulate-failure")
    client.post("/demo/circuit-breaker/simulate-failure")
    time.sleep(0.07)
    assert client.get("/demo/circuit-breaker/status").json()["state"] == "HALF_OPEN"
    assert client.post("/demo/circuit-breaker/simulate-failure").status_code == 503
    assert client.get("/demo/circuit-breaker/status").json()["state"] == "OPEN"


def test_circuit_breaker_reset_and_invalid_payload(client):
    client.post("/demo/circuit-breaker/simulate-failure")
    client.post("/demo/circuit-breaker/simulate-failure")
    reset = client.post("/demo/circuit-breaker/reset")
    assert reset.status_code == 200
    assert reset.json()["status"] == "CLOSED"
    assert client.get("/demo/circuit-breaker/status").json()["state"] == "CLOSED"

    invalid = client.post("/demo/rate-limit/request", json={"unexpected": True})
    assert invalid.status_code == 422


def test_legacy_engine_defaults_remain_compatible():
    limiter = RateLimitEngine(["https://example.com"], max_requests=1)
    assert limiter.check_rate_limit("https://example.com") is True
    assert limiter.check_rate_limit("https://example.com") is False
    limiter.reset_rate_limit("https://example.com")
    assert limiter.check_rate_limit("https://example.com") is True

    breaker = CircuitBreaker(["https://example.com"], failure_threshold=1)
    breaker.record_failure("https://example.com")
    assert breaker.check_circuit_breaker("https://example.com") is False
    time.sleep(0.02)
    assert breaker.check_circuit_breaker("https://example.com") is False
    breaker.reset("https://example.com")
    assert breaker.check_circuit_breaker("https://example.com") is True


def test_half_open_allows_only_configured_probe_count():
    breaker = CircuitBreaker(
        ["demo://probe"],
        failure_threshold=1,
        recovery_timeout=0.02,
        half_open_max_calls=1,
    )
    breaker.record_failure("demo://probe")
    time.sleep(0.03)
    assert breaker.check_circuit_breaker("demo://probe") is True
    assert breaker.check_circuit_breaker("demo://probe") is False
    breaker.record_success("demo://probe")
    assert breaker.get_status("demo://probe")["state"] == "CLOSED"


def test_rate_limiter_is_atomic_under_concurrent_calls():
    limiter = RateLimitEngine(
        ["demo://concurrency"],
        max_requests=4,
        refill_rate_per_second=0.001,
    )
    with ThreadPoolExecutor(max_workers=20) as pool:
        outcomes = list(pool.map(lambda _: limiter.check_rate_limit("demo://concurrency"), range(20)))
    assert sum(outcomes) == 4
