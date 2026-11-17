from unittest.mock import patch, MagicMock
import pytest
from requests import RequestException, Timeout, ConnectionError as ReqConnectionError, TooManyRedirects
from core.rate_limit_engine import RateLimitEngine
from core.circuit_breaker import CircuitBreaker
from core.security_layer import SecurityLayer, SecurityViolationError
from cli.api_rate_limit_cli import APIRateLimitCLI
from cli.api_rate_limit_api import APIRateLimitAPI


# 1. 15 SECURITY & INPUT VALIDATION TESTS
@pytest.mark.parametrize(
    "malicious_url",
    [
        "http://example.com/api?id=1' OR '1'='1",
        "http://example.com/api?q=1; DROP TABLE users--",
        "http://example.com/api?q=UNION SELECT username,password",
        "http://example.com/api?search=<script>alert(1)</script>",
        "http://example.com/api?redirect=javascript:alert(1)",
        "http://example.com/api/../../etc/passwd",
        "http://example.com/api/%2e%2e%2f%2e%2e%2fetc/passwd",
        "http://example.com/api?file=c:\\windows\\system32",
        "http://example.com/api?cmd=; cat /etc/passwd",
        "http://example.com/api?cmd=| whoami",
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data/",
        "ftp://example.com/resource",
        "http://example.com/api?file=report.pdf%00.txt",
        "http://example.com/api?header=%0d%0aSet-Cookie:admin=1",
    ],
)
def test_15_security_attack_vectors_blocked(malicious_url):
    layer = SecurityLayer()
    with pytest.raises(SecurityViolationError):
        layer.check_endpoint(malicious_url)


# 2. 10 FAILURE & RESILIENCE TESTS
@pytest.mark.parametrize(
    "side_effect,expected_substring",
    [
        (Timeout("Connection timed out"), "Connection timed out"),
        (ReqConnectionError("DNS lookup failed"), "DNS lookup failed"),
        (TooManyRedirects("Exceeded 30 redirects"), "Exceeded 30 redirects"),
        (RequestException("SSL certificate verify failed"), "SSL certificate"),
        (RuntimeError("Disk I/O buffer fault"), "Unexpected error: Disk I/O"),
        (MemoryError("Out of memory"), "Unexpected error: Out of memory"),
        (MagicMock(status_code=404), "Endpoint not found"),
        (MagicMock(status_code=500), "Server error: HTTP 500"),
        (MagicMock(status_code=503), "Server error: HTTP 503"),
        (MagicMock(status_code="corrupted"), "Malformed HTTP"),
    ],
)
@patch("requests.get")
def test_10_failure_and_resilience_modes(mock_get, side_effect, expected_substring):
    mock_get.side_effect = [side_effect]
    cb = CircuitBreaker(["https://api.example.com/v1/health"], SecurityLayer())
    results = cb.audit()
    assert expected_substring in results["https://api.example.com/v1/health"][0]
    assert cb.check_circuit_breaker("https://api.example.com/v1/health") is False


# 3. 15 BUG & EDGE-CASE TESTS (6 PARAMETRIZED + 9 STANDALONE = 15)
@pytest.mark.parametrize(
    "bad_input",
    [
        "",
        "    ",
        "http://",
        "https://example.com:99999",
        None,
        12345,
    ],
)
def test_edge_case_invalid_inputs_handled_gracefully(bad_input):
    engine = RateLimitEngine([bad_input], SecurityLayer())
    results = engine.audit()
    key = str(bad_input).strip() if isinstance(bad_input, str) else str(bad_input)
    assert "Validation error" in results[key][0] or "Security violation" in results[key][0]


@patch("requests.get")
def test_32_rate_limit_check_and_exhaustion(mock_get):
    mock_get.return_value.status_code = 200
    rate_limit_engine = RateLimitEngine(["http://example.com/api1"], SecurityLayer(), max_requests=1)
    assert rate_limit_engine.check_rate_limit("http://example.com/api1") is True
    assert rate_limit_engine.check_rate_limit("http://example.com/api1") is False
    rate_limit_engine.reset_rate_limit("http://example.com/api1")
    assert rate_limit_engine.check_rate_limit("http://example.com/api1") is True


@patch("requests.get")
def test_33_circuit_breaker_trips_and_blocks_when_open(mock_get):
    mock_get.return_value.status_code = 500
    cb = CircuitBreaker(["http://example.com/api1"], SecurityLayer(), failure_threshold=1)
    first_audit = cb.audit()
    assert "Server error: HTTP 500" in first_audit["http://example.com/api1"][0]
    second_audit = cb.audit()
    assert second_audit["http://example.com/api1"] == ["Circuit breaker is open"]


def test_34_boundary_url_exceeding_max_length():
    long_url = "https://example.com/" + ("a" * 2100)
    with pytest.raises(SecurityViolationError):
        SecurityLayer(max_url_length=2048).check_endpoint(long_url)


def test_35_invalid_thresholds_and_timeouts_rejected():
    with pytest.raises(ValueError):
        SecurityLayer(timeout=0)
    with pytest.raises(ValueError):
        RateLimitEngine(["http://example.com"], max_requests=0)
    with pytest.raises(ValueError):
        CircuitBreaker(["http://example.com"], failure_threshold=0)


def test_36_empty_and_non_list_endpoints_handled():
    assert RateLimitEngine([]).audit() == {}
    with pytest.raises(TypeError):
        RateLimitEngine(None)


@patch("requests.get")
def test_37_unicode_and_whitespace_trimmed_url_succeeds(mock_get):
    mock_get.return_value = MagicMock(status_code=200)
    engine = RateLimitEngine(["  https://example.com/api/v1/ümlaut  "])
    results = engine.audit()
    assert results["https://example.com/api/v1/ümlaut"] == ["No rate limit issues"]


@patch("requests.get")
def test_38_upstream_http_429_depletes_rate_limit(mock_get):
    mock_get.return_value = MagicMock(status_code=429)
    engine = RateLimitEngine(["https://example.com/rate"], max_requests=5)
    results = engine.audit()
    assert results["https://example.com/rate"] == ["Upstream rate limit triggered (HTTP 429)"]
    assert engine.check_rate_limit("https://example.com/rate") is False


@patch("requests.get")
def test_39_rate_limit_and_circuit_breaker_healthy_audits(mock_get):
    mock_get.return_value = MagicMock(status_code=200)
    rl = RateLimitEngine(["http://example.com/api1"], SecurityLayer())
    cb = CircuitBreaker(["http://example.com/api1"], SecurityLayer())
    assert rl.audit()["http://example.com/api1"] == ["No rate limit issues"]
    assert cb.audit()["http://example.com/api1"] == ["No circuit breaker issues"]


@patch("requests.get")
def test_40_cli_and_api_wrappers_merge_both_engines(mock_get, capsys):
    mock_get.return_value = MagicMock(status_code=200)
    endpoints = ["https://example.com/api1"]
    cli_res = APIRateLimitCLI(endpoints).run()
    api_res = APIRateLimitAPI(endpoints).audit()
    captured = capsys.readouterr().out
    expected = {
        "https://example.com/api1": ["No rate limit issues", "No circuit breaker issues"]
    }
    assert cli_res == api_res == expected
    assert "Endpoint: https://example.com/api1" in captured
