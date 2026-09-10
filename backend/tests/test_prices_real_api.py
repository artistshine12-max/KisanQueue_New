"""
tests/test_prices_real_api.py — Optional live integration test against official data.gov.in.

This test ONLY runs when a legitimate AGMARKNET_API_KEY environment variable is present.
If no key is configured, pytest automatically skips this test without failing the build.

SECURITY:
- Never prints, asserts against, or logs the plain API key.
- Never commits or persists any credentials.
"""
from __future__ import annotations

import os
import time
import pytest

from modules.prices.agmarknet_client import AgmarknetClient

API_KEY = os.environ.get("AGMARKNET_API_KEY", "").strip()


@pytest.mark.skipif(
    not API_KEY,
    reason="LIVE API NOT VERIFIED — no legitimate AGMARKNET_API_KEY configured in environment",
)
@pytest.mark.asyncio
async def test_live_data_gov_in_agmarknet_api():
    """
    Direct live integration verification against official data.gov.in AGMARKNET dataset:
    Resource ID: 9ef84268-d588-465a-a308-a864a43d0070
    """
    client = AgmarknetClient(api_key=API_KEY)

    start = time.perf_counter()
    result = await client.fetch_prices(commodity="Wheat", limit=5)
    latency_ms = (time.perf_counter() - start) * 1000

    assert result.status == "ok"
    assert isinstance(result.records, list)
    assert result.limit == 5

    # Print telemetry for test runner visibility without printing credentials
    print(f"\n[LIVE API TELEMETRY] Status: {result.status}")
    print(f"[LIVE API TELEMETRY] Records count: {len(result.records)}")
    print(f"[LIVE API TELEMETRY] Total reported: {result.total}")
    print(f"[LIVE API TELEMETRY] Latency: {latency_ms:.2f}ms")

    if result.records:
        first = result.records[0]
        print(f"[LIVE API TELEMETRY] Sample commodity: {first.get('commodity')}")
        print(f"[LIVE API TELEMETRY] Sample market: {first.get('market')}")
        print(f"[LIVE API TELEMETRY] Sample modal price: {first.get('modal_price')}")
        assert "commodity" in first
        assert "modal_price" in first
