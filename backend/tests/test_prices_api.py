"""
tests/test_prices_api.py — API integration tests for /v1/prices endpoints.

Tests HTTP status, query filters, pagination boundaries, and sync status telemetry.
"""
from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.db]


@pytest.mark.asyncio
async def test_get_prices_endpoint_success(async_client: AsyncClient):
    """GET /v1/prices returns 200 with standard response envelope."""
    resp = await async_client.get("/v1/prices?limit=5")
    assert resp.status_code == 200

    data = resp.json()
    assert "prices" in data
    assert "total" in data
    assert "limit" in data
    assert "offset" in data
    assert "source" in data
    assert "delivery_status" in data
    assert "is_live" in data
    assert "freshness" in data
    assert data["limit"] == 5

    # If seeded rows exist, verify item schema
    if data["prices"]:
        first = data["prices"][0]
        assert "commodity" in first
        assert "variety" in first
        assert "market" in first
        assert "modal_price" in first
        assert "unit" in first
        assert "data_age_days" in first
        assert first["unit"] == "₹/quintal"


@pytest.mark.asyncio
async def test_get_prices_filter_by_commodity(async_client: AsyncClient):
    """GET /v1/prices?commodity=Wheat filters records to Wheat only."""
    resp = await async_client.get("/v1/prices?commodity=Wheat")
    assert resp.status_code == 200

    data = resp.json()
    for item in data["prices"]:
        assert item["commodity"].lower() == "wheat"


@pytest.mark.asyncio
async def test_get_prices_pagination_validation(async_client: AsyncClient):
    """Verify bounds enforcement on pagination parameters."""
    # limit > 100 should be rejected by Pydantic validation (422)
    resp_over = await async_client.get("/v1/prices?limit=101")
    assert resp_over.status_code == 422

    # limit < 1 should be rejected
    resp_under = await async_client.get("/v1/prices?limit=0")
    assert resp_under.status_code == 422

    # negative offset should be rejected
    resp_neg_offset = await async_client.get("/v1/prices?offset=-5")
    assert resp_neg_offset.status_code == 422


@pytest.mark.asyncio
async def test_get_sync_status_endpoint(async_client: AsyncClient):
    """GET /v1/prices/sync-status returns observability metadata."""
    resp = await async_client.get("/v1/prices/sync-status")
    assert resp.status_code == 200

    data = resp.json()
    assert "configured_provider" in data
    assert "is_api_key_configured" in data
    assert "base_url" in data
    assert "cache_ttl_hours" in data
    assert "latest_sync" in data
