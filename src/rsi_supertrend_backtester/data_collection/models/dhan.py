"""
Pydantic models for DhanHQ API request/response structures.
"""
from typing import Any
from pydantic import BaseModel, Field


class IntradayRequest(BaseModel):
    """Request body for POST /v2/charts/intraday"""

    securityId: str
    exchangeSegment: str
    instrument: str
    interval: str = "5"
    expiryCode: int = 0
    oi: bool = False
    fromDate: str  # YYYY-MM-DD
    toDate: str  # YYYY-MM-DD


class HistoricalRequest(BaseModel):
    """Request body for POST /v2/charts/historical (Day/Week candles)"""

    securityId: str
    exchangeSegment: str
    instrument: str
    expiryCode: int = 0
    fromDate: str  # YYYY-MM-DD
    toDate: str  # YYYY-MM-DD


class IntradayResponse(BaseModel):
    """
    Response from POST /v2/charts/intraday.

    The API returns parallel arrays. All arrays must have equal length.
    On error, the API may return {"status": "failure", "errorCode": "...", "errorMessage": "..."}
    """

    open: list[float] = Field(default_factory=list)
    high: list[float] = Field(default_factory=list)
    low: list[float] = Field(default_factory=list)
    close: list[float] = Field(default_factory=list)
    volume: list[int] = Field(default_factory=list)
    timestamp: list[int] = Field(default_factory=list)  # UNIX epoch seconds

    # Error fields (present on failure)
    status: str | None = None
    errorCode: str | None = None
    errorMessage: str | None = None
    errorType: str | None = None

    def is_error(self) -> bool:
        return self.status == "failure" or self.errorCode is not None

    def get_row_count(self) -> int:
        return len(self.timestamp)

    def validate_array_lengths(self) -> bool:
        """All non-empty arrays must have the same length."""
        lengths = {
            len(self.open),
            len(self.high),
            len(self.low),
            len(self.close),
            len(self.volume),
            len(self.timestamp),
        }
        return len(lengths) <= 1


class DhanErrorCodes:
    """Known DhanHQ error codes for classification."""

    RATE_LIMITED = {"805", "DH-904", "429"}
    AUTH_FAILED = {"DH-901", "INVALID_TOKEN", "INVALID_CLIENT_ID", "DH-908"}
    NOT_SUBSCRIBED = {"DH-902", "SUBSCRIPTION_ERROR"}
    INVALID_REQUEST = {"DH-903", "INVALID_SECURITY_ID", "DH-905"}
    NO_DATA = {"DH-906", "NO_DATA"}


class DhanApiError(Exception):
    """Structured error from DhanHQ API."""

    def __init__(
        self,
        error_code: str,
        message: str,
        error_type: str = "UNKNOWN",
        retryable: bool = False,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.error_type = error_type
        self.retryable = retryable
        self.message = message

    def __repr__(self) -> str:
        return f"DhanApiError(code={self.error_code}, type={self.error_type}, retryable={self.retryable})"


class AuthenticationError(DhanApiError):
    """Non-retryable authentication failure."""

    def __init__(self, message: str, error_code: str = "AUTH_FAILED"):
        super().__init__(error_code, message, "AUTH_ERROR", retryable=False)


class RateLimitError(DhanApiError):
    """Retryable rate limit error."""

    def __init__(self, message: str, error_code: str = "RATE_LIMIT"):
        super().__init__(error_code, message, "RATE_LIMIT", retryable=True)


class SubscriptionError(DhanApiError):
    """Non-retryable subscription/access error."""

    def __init__(self, message: str):
        super().__init__("SUBSCRIPTION_ERROR", message, "SUBSCRIPTION", retryable=False)


class TransientError(DhanApiError):
    """Retryable transient server error."""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(
            f"HTTP_{status_code}", message, "TRANSIENT_ERROR", retryable=True
        )
