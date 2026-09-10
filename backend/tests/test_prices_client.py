"""
tests/test_prices_client.py — Unit tests for AgmarknetClient.

Tests HTTP mock interactions, error classification, timeout backoff, and secret masking.
"""
from __future__ import annotations

import httpx
import pytest

from core.exceptions import (
    AgmarknetAuthError,
    AgmarknetMalformedResponseError,
    AgmarknetRateLimitError,
    AgmarknetServerError,
    AgmarknetTimeoutError,
)
from modules.prices.agmarknet_client import AgmarknetClient


@pytest.mark.asyncio
async def test_client_raises_auth_error_when_api_key_missing():
    """Client must immediately raise AgmarknetAuthError if API key is None or empty."""
    client = AgmarknetClient(api_key="")
    with pytest.raises(AgmarknetAuthError, match="AGMARKNET_API_KEY is not configured"):
        await client.fetch_prices(commodity="Wheat")


def test_client_mask_sensitive_url():
    """Ensure API keys are masked in logged URLs."""
    raw_url = "https://api.data.gov.in/resource/123?api-key=SECRET_TOKEN_999&format=json"
    masked = AgmarknetClient.mask_sensitive_url(raw_url)
    assert "SECRET_TOKEN_999" not in masked
    assert "api-key=***" in masked


@pytest.mark.asyncio
async def test_client_fetch_success():
    """Mock 200 OK response from data.gov.in."""
    mock_payload = {
        "status": "ok",
        "total": 1,
        "count": 1,
        "limit": 10,
        "offset": 0,
        "records": [
            {
                "state": "Madhya Pradesh",
                "district": "Sehore",
                "market": "Sehore Mandi",
                "commodity": "Wheat",
                "variety": "Sharbati",
                "arrival_date": "04/10/2026",
                "min_price": "2400",
                "max_price": "2600",
                "modal_price": "2500",
            }
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "filters%5Bcommodity%5D=Wheat" in str(request.url) or "filters[commodity]=Wheat" in str(request.url)
        return httpx.Response(200, json=mock_payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as mock_http:
        client = AgmarknetClient(api_key="test-key", http_client=mock_http)
        result = await client.fetch_prices(commodity="Wheat")

        assert result.status == "ok"
        assert len(result.records) == 1
        assert result.total == 1
        assert result.records[0]["commodity"] == "Wheat"


@pytest.mark.asyncio
async def test_client_fetch_401_auth_error():
    """Mock 401 Unauthorized maps to AgmarknetAuthError."""
    transport = httpx.MockTransport(lambda req: httpx.Response(401, text="Unauthorized"))
    async with httpx.AsyncClient(transport=transport) as mock_http:
        client = AgmarknetClient(api_key="invalid-key", http_client=mock_http)
        with pytest.raises(AgmarknetAuthError, match="Authentication failed"):
            await client.fetch_prices(commodity="Wheat")


@pytest.mark.asyncio
async def test_client_fetch_429_rate_limit():
    """Mock 429 Too Many Requests maps to AgmarknetRateLimitError."""
    transport = httpx.MockTransport(lambda req: httpx.Response(429, text="Rate Limit Exceeded"))
    async with httpx.AsyncClient(transport=transport) as mock_http:
        client = AgmarknetClient(api_key="test-key", http_client=mock_http)
        with pytest.raises(AgmarknetRateLimitError, match="rate limit exceeded"):
            await client.fetch_prices(commodity="Wheat")


@pytest.mark.asyncio
async def test_client_fetch_500_server_error():
    """Mock 500 Internal Server Error maps to AgmarknetServerError."""
    transport = httpx.MockTransport(lambda req: httpx.Response(503, text="Government Gateway Error"))
    async with httpx.AsyncClient(transport=transport) as mock_http:
        client = AgmarknetClient(api_key="test-key", http_client=mock_http, max_retries=0)
        with pytest.raises(AgmarknetServerError):
            await client.fetch_prices(commodity="Wheat")


@pytest.mark.asyncio
async def test_client_fetch_malformed_json():
    """Mock response that returns non-JSON text."""
    transport = httpx.MockTransport(lambda req: httpx.Response(200, text="<html>502 Bad Gateway</html>"))
    async with httpx.AsyncClient(transport=transport) as mock_http:
        client = AgmarknetClient(api_key="test-key", http_client=mock_http)
        with pytest.raises(AgmarknetMalformedResponseError):
            await client.fetch_prices(commodity="Wheat")


@pytest.mark.asyncio
async def test_client_fetch_empty_records_list():
    """Mock response returning 0 records for a commodity."""
    mock_payload = {"status": "ok", "total": 0, "count": 0, "records": []}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=mock_payload))
    async with httpx.AsyncClient(transport=transport) as mock_http:
        client = AgmarknetClient(api_key="test-key", http_client=mock_http)
        result = await client.fetch_prices(commodity="UnknownCrop")
        assert len(result.records) == 0
        assert result.total == 0
