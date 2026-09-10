"""
tests/test_prices_service.py — Unit and integration tests for PriceService.

Tests PostgreSQL upsert deduplication, provider behaviors, fallback mechanics,
data age vs cache age separation, and freshness classification.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.mandi_price import MandiPrice
from modules.prices.agmarknet_client import AgmarknetClient
from modules.prices.normalizer import NormalizedMandiPrice
from modules.prices.service import PriceService


@pytest.mark.asyncio
async def test_upsert_deduplication_updates_existing_row(db_session: AsyncSession):
    """
    Verify the composite natural key (commodity, variety, market, arrival_date, source)
    guarantees deduplication: re-syncing the same market date updates prices instead of duplicating rows.
    """
    service = PriceService(db_session=db_session)
    arr_date = date(2026, 9, 10)
    now = datetime.now(timezone.utc)

    # Initial record
    record1 = NormalizedMandiPrice(
        commodity="Wheat",
        variety="Sharbati",
        market="Test Mandi A",
        district="Test District",
        state="Test State",
        arrival_date=arr_date,
        min_price=Decimal("2200.00"),
        max_price=Decimal("2400.00"),
        modal_price=Decimal("2300.00"),
        unit="₹/quintal",
        source="AGMARKNET",
        source_record_id="rec-1",
        fetched_at=now,
    )

    upserted_count = await service.upsert_prices([record1])
    assert upserted_count == 1

    # Check that 1 row exists
    res1 = await db_session.execute(
        select(MandiPrice).where(
            MandiPrice.commodity == "Wheat",
            MandiPrice.market == "Test Mandi A",
            MandiPrice.arrival_date == arr_date,
        )
    )
    rows1 = res1.scalars().all()
    assert len(rows1) == 1
    assert rows1[0].modal_price == Decimal("2300.00")

    # Updated record for the exact same market day (new modal price 2350)
    record2 = NormalizedMandiPrice(
        commodity="Wheat",
        variety="Sharbati",
        market="Test Mandi A",
        district="Test District",
        state="Test State",
        arrival_date=arr_date,
        min_price=Decimal("2250.00"),
        max_price=Decimal("2450.00"),
        modal_price=Decimal("2350.00"),
        unit="₹/quintal",
        source="AGMARKNET",
        source_record_id="rec-1-v2",
        fetched_at=now + timedelta(hours=2),
    )

    upserted_count_2 = await service.upsert_prices([record2])
    assert upserted_count_2 == 1

    # Expire cached session objects so fresh state is fetched from DB
    db_session.expire_all()

    # Verify still exactly 1 row, but with updated modal price
    res2 = await db_session.execute(
        select(MandiPrice).where(
            MandiPrice.commodity == "Wheat",
            MandiPrice.market == "Test Mandi A",
            MandiPrice.arrival_date == arr_date,
        )
    )
    rows2 = res2.scalars().all()
    assert len(rows2) == 1
    assert rows2[0].modal_price == Decimal("2350.00")
    assert rows2[0].source_record_id == "rec-1-v2"

    # Cleanup
    await db_session.execute(delete(MandiPrice).where(MandiPrice.market == "Test Mandi A"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_provider_seed_returns_demo_delivery(db_session: AsyncSession):
    """When PRICE_PROVIDER=seed, results return delivery_status=DEMO and is_live=False."""
    service = PriceService(db_session=db_session, provider_override="seed")
    response = await service.get_prices(limit=10)

    assert response.delivery_status == "DEMO"
    assert response.is_live is False
    assert response.limit == 10
    if response.total > 0:
        assert response.prices[0].unit == "₹/quintal"
        assert response.prices[0].data_age_days >= 0


@pytest.mark.asyncio
async def test_agmarknet_provider_live_success_and_caching(db_session: AsyncSession):
    """When AGMARKNET succeeds, delivery_status is LIVE_API and is_live is True."""
    mock_payload = {
        "status": "ok",
        "total": 1,
        "count": 1,
        "records": [
            {
                "state": "Madhya Pradesh",
                "district": "Sehore",
                "market": "Live Mandi Test",
                "commodity": "Soyabean",
                "variety": "Yellow",
                "arrival_date": "10/09/2026",
                "min_price": "4500",
                "max_price": "4800",
                "modal_price": "4700",
            }
        ],
    }

    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=mock_payload))
    async with httpx.AsyncClient(transport=transport) as mock_http:
        client = AgmarknetClient(api_key="valid-key", http_client=mock_http)
        service = PriceService(
            db_session=db_session,
            agmarknet_client=client,
            provider_override="agmarknet",
        )

        response = await service.get_prices(commodity="Soyabean", market="Live Mandi Test", force_live=True)

        assert response.delivery_status == "LIVE_API"
        assert response.is_live is True
        assert response.freshness == "LIVE"
        assert len(response.prices) == 1
        assert response.prices[0].modal_price == Decimal("4700.00")

        # Second call with force_live=False should hit cache
        cache_response = await service.get_prices(commodity="Soyabean", market="Live Mandi Test", force_live=False)
        assert cache_response.delivery_status == "CACHE_HIT"
        assert cache_response.is_live is False
        assert cache_response.freshness == "RECENT_CACHE"

    # Cleanup
    await db_session.execute(delete(MandiPrice).where(MandiPrice.market == "Live Mandi Test"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_agmarknet_fallback_on_upstream_failure(db_session: AsyncSession):
    """When AGMARKNET raises an error, service falls back to PostgreSQL cache gracefully."""
    # Seed a cached record
    arr_date = date(2026, 9, 9)
    await db_session.execute(
        MandiPrice.__table__.insert().values(
            id="fallback-test-1",
            commodity="Mustard",
            variety="Black",
            market="Fallback Mandi",
            district="Raisen",
            state="Madhya Pradesh",
            arrival_date=arr_date,
            min_price=Decimal("5000.00"),
            max_price=Decimal("5400.00"),
            modal_price=Decimal("5200.00"),
            unit="₹/quintal",
            source="AGMARKNET",
            fetched_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
    )
    await db_session.commit()

    # Mock server error from upstream
    transport = httpx.MockTransport(lambda req: httpx.Response(500, text="Server Error"))
    async with httpx.AsyncClient(transport=transport) as mock_http:
        client = AgmarknetClient(api_key="valid-key", http_client=mock_http, max_retries=0)
        service = PriceService(
            db_session=db_session,
            agmarknet_client=client,
            provider_override="agmarknet",
        )

        # Request force_live=True to trigger upstream call that will fail
        response = await service.get_prices(commodity="Mustard", market="Fallback Mandi", force_live=True)

        assert response.delivery_status == "FALLBACK"
        assert response.is_live is False
        assert response.source == "AGMARKNET"
        assert len(response.prices) == 1
        assert response.prices[0].modal_price == Decimal("5200.00")

    # Cleanup
    await db_session.execute(delete(MandiPrice).where(MandiPrice.market == "Fallback Mandi"))
    await db_session.commit()


@pytest.mark.asyncio
async def test_freshness_stale_cache_and_no_data(db_session: AsyncSession):
    """Verify STALE_CACHE when data is > 24h old and NO_DATA when no records match."""
    # Stale record (fetched 3 days ago)
    import uuid
    uid_str = uuid.uuid4().hex[:8]
    test_id = f"stale-{uid_str}"
    test_market = f"Stale Mandi {uid_str}"
    try:
        await db_session.execute(
            MandiPrice.__table__.insert().values(
                id=test_id,
                commodity="Cotton",
                variety="Medium",
                market=test_market,
                district="Khandwa",
                state="Madhya Pradesh",
                arrival_date=date(2026, 9, 5),
                min_price=Decimal("6500.00"),
                max_price=Decimal("7000.00"),
                modal_price=Decimal("6800.00"),
                unit="₹/quintal",
                source="AGMARKNET",
                fetched_at=datetime.now(timezone.utc) - timedelta(days=3),
            )
        )
        await db_session.commit()

        service = PriceService(db_session=db_session, provider_override="agmarknet")
        # Query stale mandi with force_live=False. Because cache is stale, service attempts
        # an upstream refresh. Since no API key is set in test environment, it falls back to cache.
        stale_resp = await service.get_prices(market=test_market, force_live=False)
        assert stale_resp.delivery_status == "FALLBACK"
        assert stale_resp.freshness == "STALE_CACHE"
        assert stale_resp.cache_age_seconds is not None
        assert stale_resp.cache_age_seconds > 86400  # More than 24 hours

        # Query completely nonexistent commodity
        empty_resp = await service.get_prices(commodity="NonExistentDragonFruit", force_live=False)
        assert empty_resp.total == 0
        assert empty_resp.freshness == "NO_DATA"
    finally:
        await db_session.rollback()
        await db_session.execute(delete(MandiPrice).where(MandiPrice.id == test_id))
        await db_session.commit()


