"""
modules/prices/router.py — Mandi Commodity Prices API endpoints.

Routes:
    GET /v1/prices              — Search and paginate daily mandi prices with freshness metadata
    GET /v1/prices/sync-status  — Observable telemetry of the latest synchronization job
"""
from __future__ import annotations

from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, Query

from core.config import settings
from core.dependencies import DbSession
from modules.prices.schemas import MandiPriceListResponse, PriceSyncSummary
from modules.prices.service import PriceService
from modules.prices.sync import get_latest_sync_summary

router = APIRouter()
log = structlog.get_logger(__name__)


@router.get("", response_model=MandiPriceListResponse)
async def get_prices(
    db: DbSession,
    commodity: str | None = Query(None, description="Commodity name (e.g. 'Wheat', 'Paddy', 'Mustard')"),
    variety: str | None = Query(None, description="Crop variety (e.g. 'Sharbati', 'Lokwan', 'Local')"),
    market: str | None = Query(None, description="Mandi/market name (e.g. 'Sehore Mandi')"),
    district: str | None = Query(None, description="District name"),
    state: str | None = Query(None, description="State name"),
    arrival_date: date | None = Query(None, alias="date", description="Arrival date (YYYY-MM-DD)"),
    limit: int = Query(20, ge=1, le=100, description="Page size (1 to 100)"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    force_live: bool = Query(False, description="Bypass cache to fetch live from upstream if provider is agmarknet"),
) -> MandiPriceListResponse:
    """
    Retrieve daily wholesale arrival prices for agricultural commodities.

    Returns prices alongside detailed freshness and delivery metadata:
    - `source`: Underlying provenance (AGMARKNET, DEMO_SEED, etc.)
    - `delivery_status`: How data was served (LIVE_API, CACHE_HIT, FALLBACK, DEMO)
    - `is_live`: True only if directly fetched from upstream in this request
    - `freshness`: Operational freshness classification (LIVE, RECENT_CACHE, STALE_CACHE, DEMO, NO_DATA)
    - `data_age_days`: Age of the market arrival date relative to today
    - `cache_age_seconds`: Age of the local cache entry relative to now
    """
    service = PriceService(db_session=db)
    return await service.get_prices(
        commodity=commodity,
        variety=variety,
        market=market,
        district=district,
        state=state,
        arrival_date=arrival_date,
        limit=limit,
        offset=offset,
        force_live=force_live,
    )


@router.get("/sync-status")
async def get_sync_status() -> dict[str, Any]:
    """
    Observability endpoint: returns telemetry for the most recent background sync run.
    """
    latest = get_latest_sync_summary()
    return {
        "configured_provider": settings.PRICE_PROVIDER,
        "is_api_key_configured": bool(settings.AGMARKNET_API_KEY and settings.AGMARKNET_API_KEY.strip()),
        "base_url": settings.AGMARKNET_BASE_URL,
        "cache_ttl_hours": settings.PRICE_CACHE_TTL_HOURS,
        "latest_sync": latest.model_dump() if latest else None,
    }
