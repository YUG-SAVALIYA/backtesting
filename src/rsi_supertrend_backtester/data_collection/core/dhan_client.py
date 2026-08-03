"""
DhanHQ HTTP client with retry and rate limiting.

Handles:
- Authentication via access-token header
- Rate limiting via global token bucket
- Retry via tenacity with exponential backoff + jitter
- Error classification into actionable exception types
- Response validation (array length parity, empty data)
"""
import asyncio
import random
from datetime import date

import httpx
import pandas as pd
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from rsi_supertrend_backtester.data_collection.config import settings
from rsi_supertrend_backtester.data_collection.core.rate_limiter import get_rate_limiter
from rsi_supertrend_backtester.data_collection.models.dhan import (
    AuthenticationError,
    DhanApiError,
    DhanErrorCodes,
    HistoricalRequest,
    IntradayRequest,
    IntradayResponse,
    RateLimitError,
    SubscriptionError,
    TransientError,
)
from rsi_supertrend_backtester.data_collection.utils.logger import get_logger

logger = get_logger(__name__)

IST_TZ = "Asia/Kolkata"


def _classify_error(response_data: dict) -> DhanApiError | None:
    """
    Classify a DhanHQ error response into the appropriate exception type.

    Returns None if the response is not an error.
    """
    status = response_data.get("status", "")
    error_code = str(response_data.get("errorCode", ""))
    error_type = str(response_data.get("errorType", ""))
    error_msg = response_data.get("errorMessage", "Unknown DhanHQ error")

    # Successful case
    if status == "success" or (not error_code and not error_type):
        return None

    # Check for authentication errors
    if (
        error_code in DhanErrorCodes.AUTH_FAILED
        or error_type in DhanErrorCodes.AUTH_FAILED
        or "token" in error_msg.lower()
        or "authentication" in error_msg.lower()
    ):
        return AuthenticationError(f"Auth failed [{error_code}]: {error_msg}", error_code)

    # Check for subscription errors
    if (
        error_code in DhanErrorCodes.NOT_SUBSCRIBED
        or error_type in DhanErrorCodes.NOT_SUBSCRIBED
        or "subscription" in error_msg.lower()
    ):
        return SubscriptionError(f"API not subscribed [{error_code}]: {error_msg}")

    # Check for rate limit errors
    if (
        error_code in DhanErrorCodes.RATE_LIMITED
        or error_type in ("RATE_LIMIT", "TOO_MANY_REQUESTS")
        or "rate" in error_msg.lower()
        or "too many" in error_msg.lower()
        or "blocked" in error_msg.lower()
    ):
        return RateLimitError(f"Rate limited [{error_code}]: {error_msg}", error_code)

    # Check for no-data
    if (
        error_code in DhanErrorCodes.NO_DATA
        or error_type in DhanErrorCodes.NO_DATA
        or "no data" in error_msg.lower()
    ):
        return None  # Handled as empty response

    # Generic Dhan error (fail-fast for invalid requests)
    return DhanApiError(error_code, f"[{error_code}]: {error_msg}", error_type, retryable=False)


class DhanClient:
    """
    Async HTTP client for the DhanHQ API.
    
    Singleton-style: call `DhanClient()` to get an instance, then use
    as async context manager or call `close()` explicitly.
    """

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=settings.dhan_base_url,
            headers={
                "access-token": settings.dhan_access_token,
                "client-id": settings.dhan_client_id,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(60.0, connect=10.0),
        )
        self._rate_limiter = get_rate_limiter()

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    async def fetch_intraday_chunk(
        self,
        security_id: str,
        exchange_segment: str,
        instrument: str,
        from_date: date,
        to_date: date,
        request_counter_callback=None,
    ) -> pd.DataFrame:
        """
        Fetch a single chunk of 5-minute intraday candle data.

        Args:
            security_id: DhanHQ security ID
            exchange_segment: e.g., "NSE_EQ"
            instrument: e.g., "EQUITY"
            from_date: Chunk start date
            to_date: Chunk end date (max 85 days from from_date)
            request_counter_callback: Optional callable to track total requests

        Returns:
            DataFrame with columns [datetime, open, high, low, close, volume]
            Empty DataFrame if no data available for the range.

        Raises:
            AuthenticationError: On invalid/expired token (not retried)
            SubscriptionError: On API not subscribed (not retried)
            DhanApiError: On unrecoverable API errors
        """
        request_body = IntradayRequest(
            securityId=security_id,
            exchangeSegment=exchange_segment,
            instrument=instrument,
            interval=settings.dhan_intraday_interval,
            fromDate=from_date.strftime("%Y-%m-%d"),
            toDate=to_date.strftime("%Y-%m-%d"),
        )

        # Retry with tenacity
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(settings.max_retries),
                wait=wait_exponential(
                    multiplier=1,
                    min=settings.retry_min_wait,
                    max=settings.retry_max_wait,
                ),
                retry=retry_if_exception_type((RateLimitError, TransientError, httpx.TransportError)),
                reraise=True,
            ):
                with attempt:
                    attempt_num = attempt.retry_state.attempt_number
                    if attempt_num > 1:
                        jitter = random.uniform(0.8, 1.2)
                        logger.warning(
                            f"Retry attempt {attempt_num}/{settings.max_retries} "
                            f"for {security_id} chunk {from_date}→{to_date}"
                        )
                        await asyncio.sleep(jitter)

                    # Acquire rate limit token
                    await self._rate_limiter.acquire()

                    if request_counter_callback:
                        request_counter_callback()

                    response = await self._client.post(
                        "/charts/intraday",
                        json=request_body.model_dump(),
                    )

                    df = await self._process_response(
                        response, security_id, from_date, to_date
                    )
                    return df

        except RetryError as e:
            logger.error(f"All retries exhausted for {security_id} {from_date}→{to_date}: {e}")
            raise

    async def _process_response(
        self,
        response: httpx.Response,
        security_id: str,
        from_date: date,
        to_date: date,
    ) -> pd.DataFrame:
        """Parse and validate the DhanHQ API response."""
        # Handle HTTP errors
        if response.status_code == 401:
            raise AuthenticationError(
                "Invalid or expired access token. Update DHAN_ACCESS_TOKEN in .env.",
                "HTTP_401",
            )
        if response.status_code == 403:
            raise AuthenticationError(
                "Access forbidden. Check your client ID and token.",
                "HTTP_403",
            )
        if response.status_code == 429:
            raise RateLimitError(
                f"HTTP 429 rate limit. Retry after backoff.",
                "HTTP_429",
            )
        if response.status_code >= 500:
            raise TransientError(
                f"Server error {response.status_code}",
                response.status_code,
            )

        try:
            data = response.json()
        except Exception as e:
            raise TransientError(f"Invalid JSON response: {e}")

        # Check for DhanHQ application-level errors
        if isinstance(data, dict):
            err = _classify_error(data)
            if err is not None:
                if isinstance(err, (AuthenticationError, SubscriptionError)):
                    raise err  # Non-retryable
                if isinstance(err, RateLimitError):
                    raise err  # Retryable via tenacity
                raise err

        # Parse intraday response
        intraday = IntradayResponse.model_validate(data)

        # Empty data is valid (no trades in range)
        if not intraday.timestamp:
            logger.debug(f"Empty data for securityId={security_id} {from_date}→{to_date}")
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])

        # Validate array lengths
        if not intraday.validate_array_lengths():
            logger.error(
                f"Array length mismatch for {security_id}: "
                f"open={len(intraday.open)}, high={len(intraday.high)}, "
                f"low={len(intraday.low)}, close={len(intraday.close)}, "
                f"vol={len(intraday.volume)}, time={len(intraday.timestamp)}"
            )
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume"])

        # Convert to DataFrame
        df = _arrays_to_dataframe(intraday)

        logger.info(
            f"  securityId={security_id} {from_date}→{to_date}: {len(df)} candles"
        )
        return df

    async def fetch_historical_data(
        self,
        security_id: str,
        exchange_segment: str,
        instrument: str,
        from_date: date,
        to_date: date,
        request_counter_callback=None,
    ) -> pd.DataFrame:
        """
        Fetch Day/Week candles from /v2/charts/historical.

        This endpoint supports long date ranges (years of daily data).
        Returns DataFrame with columns [datetime, open, high, low, close, volume].
        """
        request_body = HistoricalRequest(
            securityId=security_id,
            exchangeSegment=exchange_segment,
            instrument=instrument,
            fromDate=from_date.strftime("%Y-%m-%d"),
            toDate=to_date.strftime("%Y-%m-%d"),
        )

        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(settings.max_retries),
                wait=wait_exponential(
                    multiplier=1,
                    min=settings.retry_min_wait,
                    max=settings.retry_max_wait,
                ),
                retry=retry_if_exception_type((RateLimitError, TransientError, httpx.TransportError)),
                reraise=True,
            ):
                with attempt:
                    attempt_num = attempt.retry_state.attempt_number
                    if attempt_num > 1:
                        jitter = random.uniform(0.8, 1.2)
                        logger.warning(
                            f"Retry attempt {attempt_num}/{settings.max_retries} "
                            f"for historical {security_id} {from_date}→{to_date}"
                        )
                        await asyncio.sleep(jitter)

                    await self._rate_limiter.acquire()

                    if request_counter_callback:
                        request_counter_callback()

                    response = await self._client.post(
                        "/charts/historical",
                        json=request_body.model_dump(),
                    )

                    df = await self._process_response(
                        response, security_id, from_date, to_date
                    )
                    return df

        except RetryError as e:
            logger.error(f"All retries exhausted for historical {security_id} {from_date}→{to_date}: {e}")
            raise


def _arrays_to_dataframe(response: IntradayResponse) -> pd.DataFrame:
    """
    Convert parallel API response arrays into a row-based DataFrame.

    DhanHQ returns UNIX epoch timestamps (seconds). We convert to
    timezone-aware pandas datetimes in Asia/Kolkata (IST).
    """
    df = pd.DataFrame(
        {
            "datetime": pd.to_datetime(response.timestamp, unit="s", utc=True).tz_convert(IST_TZ),
            "open": response.open,
            "high": response.high,
            "low": response.low,
            "close": response.close,
            "volume": response.volume,
        }
    )
    return df[["datetime", "open", "high", "low", "close", "volume"]]


# Module level singleton
_client_instance: DhanClient | None = None


def get_dhan_client() -> DhanClient:
    """Get or create the global DhanHQ client instance."""
    global _client_instance
    if _client_instance is None:
        _client_instance = DhanClient()
    return _client_instance

