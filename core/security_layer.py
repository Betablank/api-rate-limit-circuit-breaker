import re
from typing import List
from urllib.parse import urlparse, unquote
import requests
from requests import RequestException


class SecurityViolationError(Exception):
    """Raised when an endpoint violates pre-flight security rules."""


class SecurityLayer:
    MALICIOUS_PATTERNS = (
        r"(\bUNION\b.*\bSELECT\b|\bDROP\s+TABLE\b|--|;\s*--|\bOR\b\s+['\"]?1['\"]?\s*=\s*['\"]?1)",
        r"(<script\b[^>]*>|javascript:|onerror\s*=|onload\s*=)",
        r"(\.\./|\.\.\\|%2e%2e%2f|/etc/passwd|c:\\windows)",
        r"(;|\||&&|\$\(|\`)\s*(cat|ls|whoami|id|bash|sh|cmd|powershell)\b",
        r"(\x00|%00)",
        r"(<!ENTITY|SYSTEM\s+['\"]file:)",
        r"(\r\n|\n|\r|%0d%0a)(Set-Cookie:|Location:|HTTP/)",
    )

    PRIVATE_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254", "::1"}

    def __init__(self, timeout: float = 5.0, max_url_length: int = 2048):
        if timeout <= 0:
            raise ValueError("Timeout must be greater than 0")
        self.timeout = timeout
        self.max_url_length = max_url_length

    def validate_target(self, endpoint: str) -> str:
        if not isinstance(endpoint, str):
            raise TypeError("Endpoint must be a string")

        cleaned = endpoint.strip()
        if not cleaned:
            raise ValueError("Endpoint cannot be empty")

        if len(cleaned) > self.max_url_length:
            raise SecurityViolationError("Endpoint exceeds maximum safe URL length")

        decoded = unquote(cleaned)
        for pattern in self.MALICIOUS_PATTERNS:
            if re.search(pattern, decoded, re.IGNORECASE) or re.search(pattern, cleaned, re.IGNORECASE):
                raise SecurityViolationError(f"Malicious payload detected in endpoint: {cleaned}")

        parsed = urlparse(cleaned)
        if parsed.scheme.lower() not in ("http", "https"):
            raise SecurityViolationError(f"Unsupported or unsafe URL scheme: {parsed.scheme}")

        if not parsed.netloc or not parsed.hostname:
            raise ValueError(f"Invalid URL host: {cleaned}")

        try:
            port = parsed.port
            if port is not None and not (1 <= port <= 65535):
                raise ValueError("Port out of valid range")
        except ValueError as exc:
            raise ValueError(f"Invalid port in endpoint: {cleaned}") from exc

        hostname = parsed.hostname.lower()
        if hostname in self.PRIVATE_HOSTS or hostname.startswith(("10.", "192.168.", "172.16.")):
            raise SecurityViolationError(f"SSRF protection blocked internal host: {hostname}")

        return cleaned

    def check_endpoint(self, endpoint: str) -> int:
        target = self.validate_target(endpoint)
        response = requests.get(target, timeout=self.timeout)
        status = getattr(response, "status_code", None)
        if not isinstance(status, int):
            raise RequestException("Malformed HTTP response status code")
        if status == 404:
            raise RequestException("Endpoint not found")
        if status >= 500:
            raise RequestException(f"Server error: HTTP {status}")
        return status
