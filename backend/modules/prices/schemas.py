"""
modules/prices/schemas.py — Pydantic schemas for Mandi Price Subsystem.

Cleanly separates:
- Source (provenance: AGMARKNET, DEMO_SEED, etc.)
- Delivery Status (delivery mechanism: LIVE_API, CACHE_HIT, FALLBACK, DEMO)
- Data Age (arrival_date vs current date)
- Fetch/Cache Age (fetched_at vs current timestamp)
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


FreshnessLevel = Literal["LIVE", "RECENT_CACHE", "STALE_CACHE", "DEMO", "NO_DATA"]
DeliveryStatus = Literal["LIVE_API", "CACHE_HIT", "FALLBACK", "DEMO"]
DataSource = Literal["AGMARKNET", "DEMO_SEED", "MANUAL_INPUT"]


class MandiPriceItem(BaseModel):
    """Single normalized mandi commodity price record."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    commodity: str
    variety: str
    market: str
    district: str
    state: str
    arrival_date: date
    min_price: Decimal = Field(..., description="Minimum wholesale price in ₹ per unit")
    max_price: Decimal = Field(..., description="Maximum wholesale price in ₹ per unit")
    modal_price: Decimal = Field(..., description="Most frequent (modal) price in ₹ per unit")
    unit: str = Field(default="₹/quintal")
    source: str = Field(default="AGMARKNET")
    source_record_id: str | None = None
    fetched_at: datetime
    data_age_days: int = Field(
        ...,
        description="Calendar days elapsed since commodity arrived at the mandi (market date age)",
    )


class MandiPriceListResponse(BaseModel):
    """Envelope for mandi price query results with comprehensive freshness metadata."""

    prices: list[MandiPriceItem]
    total: int = Field(ge=0)
    limit: int = Field(ge=1, le=100)
    offset: int = Field(ge=0)

    # Provenance and delivery separation
    source: str = Field(..., description="Underlying data provenance, e.g. AGMARKNET, DEMO_SEED")
    delivery_status: DeliveryStatus = Field(
        ...,
        description="How data was delivered: LIVE_API, CACHE_HIT, FALLBACK, or DEMO",
    )
    is_live: bool = Field(
        ...,
        description="True ONLY if data was fetched directly from upstream API in this request",
    )

    # Freshness and cache age metadata
    freshness: FreshnessLevel = Field(
        ...,
        description="Operational freshness classification: LIVE, RECENT_CACHE, STALE_CACHE, DEMO, or NO_DATA",
    )
    cache_age_seconds: float | None = Field(
        None,
        description="Seconds elapsed since the latest record in this result was fetched/cached",
    )
    last_updated: datetime | None = Field(
        None,
        description="Timestamp of the most recent fetch/write among returned records",
    )


class PriceSyncSummary(BaseModel):
    """Execution telemetry for price synchronization jobs (observability)."""

    provider: str
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
    total_fetched: int = 0
    total_normalized: int = 0
    total_upserted: int = 0
    total_skipped: int = 0
    success: bool = True
    error_message: str | None = None
