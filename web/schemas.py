from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplicationInfoResponse(BaseModel):
    name: str
    description: str
    version: str
    docs: str
    redoc: str
    features: List[str]


class HealthResponse(BaseModel):
    status: str
    service: str
    demo_mode: bool


class RateLimitRequest(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"label": "browser-demo"}]},
    )
    label: Optional[str] = Field(default=None, max_length=120, description="Optional label shown in the response")


class RateLimitDemoResponse(BaseModel):
    accepted: bool
    timestamp: str
    label: Optional[str] = None
    limit: int
    remaining: int
    available_tokens: float
    refill_rate_per_second: float


class RateLimitStatusResponse(BaseModel):
    limit: int
    remaining: int
    available_tokens: float
    refill_rate_per_second: float
    retry_after_seconds: float


class ResetResponse(BaseModel):
    reset: bool
    message: str
    status: Optional[str] = None


class CircuitBreakerRequest(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={"examples": [{"simulate_failure": False}, {"simulate_failure": True}]},
    )
    simulate_failure: bool = Field(default=False, description="Return a controlled downstream failure when true")


class CircuitBreakerResponse(BaseModel):
    success: bool
    state: str
    message: str
    timestamp: str


class CircuitBreakerStatusResponse(BaseModel):
    state: str
    failure_count: int
    failure_threshold: int
    recovery_timeout_seconds: Optional[float] = None
    remaining_recovery_seconds: Optional[float] = None
    half_open_max_calls: int
    half_open_calls_in_flight: int
    half_open_success_threshold: int
