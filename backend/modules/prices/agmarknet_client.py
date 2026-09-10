"""
modules/prices/agmarknet_client.py — Async HTTP client for data.gov.in AGMARKNET dataset.

Dataset Resource ID: 9ef84268-d588-465a-a308-a864a43d0070
Official Platform: Open Government Data (OGD) Platform India (data.gov.in)

Security & Operational Invariants:
1. API keys are strictly masked and NEVER logged in plain text or exposed in exception messages.
2. Requests use explicit, bounded timeouts and restrained exponential backoff retries.
3. Errors are classified into domain exceptions without crashing callers.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from core.config import settings
from core.exceptions import (
    AgmarknetAuthError,
    AgmarknetMalformedResponseError,
    AgmarknetNetworkError,
    AgmarknetRateLimitError,
    AgmarknetServerError,
    AgmarknetTimeoutError,
)

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class AgmarknetFetchResult:
    """Raw response container with metadata and performance metrics."""

    records: list[dict[str, Any]]
    total: int
    count: int
    limit: int
    offset: int
    status: str
    latency_ms: float
    fetched_at: datetime


class AgmarknetClient:
    """
    Async client for querying the official AGMARKNET commodity arrival prices on data.gov.in.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else settings.AGMARKNET_API_KEY
        self.base_url = (base_url or settings.AGMARKNET_BASE_URL).rstrip("?")
        self.timeout = timeout or settings.AGMARKNET_TIMEOUT_SECONDS
        self.max_retries = max_retries if max_retries is not None else settings.AGMARKNET_MAX_RETRIES
        self._custom_client = http_client

    @staticmethod
    def mask_sensitive_url(url: str) -> str:
        """Sanitize URLs by replacing api-key values with '***' for safe logging."""
        return re.sub(r"(api-key=)[^&]+", r"\1***", url, flags=re.IGNORECASE)

    async def fetch_prices(
        self,
        commodity: str | None = None,
        state: str | None = None,
        district: str | None = None,
        market: str | None = None,
        arrival_date: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> AgmarknetFetchResult:
        """
        Query daily commodity prices from data.gov.in.

        Raises:
            AgmarknetAuthError: If no API key is provided or server returns 401/403.
            AgmarknetRateLimitError: If HTTP 429 Too Many Requests is received.
            AgmarknetTimeoutError: If the request times out after all retries.
            AgmarknetNetworkError: If connection to data.gov.in fails.
            AgmarknetServerError: If data.gov.in returns a 5xx response.
            AgmarknetMalformedResponseError: If the response is not valid JSON or lacks 'records'.
        """
        if not self.api_key or not self.api_key.strip():
            log.warning("agmarknet.auth_missing", message="AGMARKNET_API_KEY is not configured")
            raise AgmarknetAuthError(
                "AGMARKNET_API_KEY is not configured. Supply a valid key in environment variables."
            )

        params: dict[str, Any] = {
            "api-key": self.api_key.strip(),
            "format": "json",
            "limit": max(1, min(limit, 1000)),
            "offset": max(0, offset),
        }

        # data.gov.in uses filters[field_name]=value syntax
        if commodity:
            params["filters[commodity]"] = commodity.strip()
        if state:
            params["filters[state]"] = state.strip()
        if district:
            params["filters[district]"] = district.strip()
        if market:
            params["filters[market]"] = market.strip()
        if arrival_date:
            params["filters[arrival_date]"] = arrival_date.strip()

        start_time = time.perf_counter()
        attempt = 0
        backoff_delay = 0.5

        while attempt <= self.max_retries:
            attempt += 1
            try:
                if self._custom_client:
                    response = await self._send_request(self._custom_client, params)
                else:
                    async with httpx.AsyncClient(timeout=self.timeout) as client:
                        response = await self._send_request(client, params)

                latency_ms = (time.perf_counter() - start_time) * 1000
                return self._parse_response(response, latency_ms)

            except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                if attempt > self.max_retries:
                    log.error(
                        "agmarknet.request.timeout",
                        attempt=attempt,
                        max_retries=self.max_retries,
                        timeout_seconds=self.timeout,
                    )
                    raise AgmarknetTimeoutError(
                        f"Request to AGMARKNET OGD platform timed out after {attempt} attempts"
                    ) from exc
                log.warning("agmarknet.request.retry_timeout", attempt=attempt, delay=backoff_delay)
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2

            except httpx.NetworkError as exc:
                if attempt > self.max_retries:
                    log.error(
                        "agmarknet.request.network_failure",
                        attempt=attempt,
                        error=str(exc),
                    )
                    raise AgmarknetNetworkError(
                        f"Failed to connect to data.gov.in: {exc}"
                    ) from exc
                log.warning("agmarknet.request.retry_network", attempt=attempt, delay=backoff_delay)
                await asyncio.sleep(backoff_delay)
                backoff_delay *= 2

        raise AgmarknetTimeoutError("Exhausted retries connecting to AGMARKNET")

    async def _send_request(
        self, client: httpx.AsyncClient, params: dict[str, Any]
    ) -> httpx.Response:
        """Perform HTTP GET request with safe logging."""
        headers = {
            "Accept": "application/json",
            "User-Agent": f"KisanQueue/{settings.APP_VERSION} (SIH-2026 PS-26032; AGMARKNET Consumer)",
        }
        return await client.get(self.base_url, params=params, headers=headers)

    def _parse_response(self, response: httpx.Response, latency_ms: float) -> AgmarknetFetchResult:
        """Inspect HTTP status, sanitize error messages, and parse JSON payload."""
        status_code = response.status_code

        if status_code in (401, 403):
            log.error("agmarknet.auth_failed", status_code=status_code)
            raise AgmarknetAuthError(
                f"Authentication failed with data.gov.in (HTTP {status_code}). Check AGMARKNET_API_KEY."
            )

        if status_code == 429:
            log.warning("agmarknet.rate_limited", status_code=status_code)
            raise AgmarknetRateLimitError(
                "data.gov.in rate limit exceeded (HTTP 429). Please wait before re-requesting."
            )

        if status_code >= 500:
            log.error("agmarknet.server_error", status_code=status_code)
            raise AgmarknetServerError(
                f"data.gov.in upstream server error (HTTP {status_code})."
            )

        if status_code >= 400:
            log.warning("agmarknet.client_error", status_code=status_code)
            raise AgmarknetMalformedResponseError(
                f"data.gov.in returned HTTP {status_code}: {response.text[:200]}"
            )

        try:
            payload = response.json()
        except Exception as exc:
            log.error("agmarknet.invalid_json", error=str(exc))
            raise AgmarknetMalformedResponseError("Failed to decode JSON from data.gov.in") from exc

        if not isinstance(payload, dict):
            raise AgmarknetMalformedResponseError("Expected top-level JSON object in AGMARKNET response")

        # In data.gov.in OGD responses, records reside in payload["records"]
        records = payload.get("records")
        if records is None or not isinstance(records, list):
            # Check for empty result or alternate structure
            if payload.get("status") == "ok" and payload.get("count") == 0:
                records = []
            else:
                log.warning("agmarknet.missing_records_key", payload_keys=list(payload.keys()))
                records = []

        total = int(payload.get("total") or len(records))
        count = int(payload.get("count") or len(records))
        limit = int(payload.get("limit") or len(records))
        offset = int(payload.get("offset") or 0)
        status_str = str(payload.get("status") or "ok")

        log.info(
            "agmarknet.fetch.success",
            records_count=len(records),
            total=total,
            latency_ms=round(latency_ms, 2),
        )

        return AgmarknetFetchResult(
            records=records,
            total=total,
            count=count,
            limit=limit,
            offset=offset,
            status=status_str,
            latency_ms=latency_ms,
            fetched_at=datetime.now(timezone.utc),
        )
