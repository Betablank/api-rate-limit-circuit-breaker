# API Rate-Limit & Circuit-Breaker Resilience Engine

Production-grade Python resilience engine that enforces token-bucket API rate limits, automatic circuit-breaker state transitions, and pre-flight security validation.

## Architecture

    +----------------------+     +------------------------+     +--------------------+
    | CLI / API Interface  | --> | RateLimitEngine &      | --> | SecurityLayer      |
    | (main.py / cli/)     |     | CircuitBreaker (core/) |     | SSRF, SQLi, XSS &  |
    | Merges audit reports |     | Quota & failure states |     | HTTP status checks |
    +----------------------+     +------------------------+     +--------------------+

## Setup & Usage

    pip install -r requirements.txt
    python main.py --api-endpoints https://httpbin.org/get

## Running the 40-Test Verification Suite

    pytest -v
