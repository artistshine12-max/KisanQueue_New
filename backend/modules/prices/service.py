"""
modules/prices/service.py — Core price service and caching/fallback orchestrator.

Implements the verified architecture:
- Explicit PRICE_PROVIDER ("agmarknet", "seed", "mock") — never auto-mutated.
- PostgreSQL atomic upsert with composite natural unique constraint.
- Separation of Data Age (arrival_date) from Fetch/Cache Age (fetched_at).
- Separation of Data Source (AGMARKNET / DEMO_SEED) from Delivery Status (LIVE_API / CACHE_HIT / FALLBACK / DEMO).
- Explicit freshness policy (LIVE, RECENT_CACHE, STALE_CACHE, DEMO, NO_DATA).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Sequence

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.exceptions import AgmarknetClientError, AgmarknetError, KisanQueueError
from models.mandi_price import MandiPrice
from modules.prices.agmarknet_client import AgmarknetClient, AgmarknetFetchResult
from modules.prices.normalizer import NormalizedMandiPrice, normalize_agmarknet_record
from modules.prices.schemas import (
    DeliveryStatus,
    FreshnessLevel,
    MandiPriceItem,
    MandiPriceListResponse,
)

log = structlog.get_logger(__name__)


class PriceService:
    """
    Coordinates market price queries between AGMARKNET upstream, PostgreSQL cache, and fallbacks.
    """

    def __init__(
        self,
        db_session: AsyncSession,
        agmarknet_client: AgmarknetClient | None = None,
        provider_override: str | None = None,
    ) -> None:
        self.db = db_session
        self.provider = provider_override or settings.PRICE_PROVIDER
        self.client = agmarknet_client or AgmarknetClient()

    async def get_prices(
        self,
        commodity: str | None = None,
        variety: str | None = None,
        market: str | None = None,
        district: str | None = None,
        state: str | None = None,
        arrival_date: date | None = None,
        limit: int = 20,
        offset: int = 0,
        force_live: bool = False,
    ) -> MandiPriceListResponse:
        """
        Retrieve commodity prices adhering to the configured PRICE_PROVIDER and fallback policy.
        """
        clamped_limit = max(1, min(limit, 100))
        clamped_offset = max(0, offset)

        # ── Case 1: DEMO / SEED Provider ──────────────────────────────────────
        if self.provider == "seed":
            return await self._query_database_cache(
                commodity=commodity,
                variety=variety,
                market=market,
                district=district,
                state=state,
                arrival_date=arrival_date,
                limit=clamped_limit,
                offset=clamped_offset,
                delivery_status="DEMO",
                default_source="DEMO_SEED",
            )

        # ── Case 2: MOCK Provider ─────────────────────────────────────────────
        if self.provider == "mock":
            return self._generate_mock_response(
                commodity=commodity,
                market=market,
                limit=clamped_limit,
                offset=clamped_offset,
            )

        # ── Case 3: AGMARKNET Provider ────────────────────────────────────────
        # If not forcing live and recent data exists in PostgreSQL, serve as CACHE_HIT
        if not force_live:
            cached_response = await self._query_database_cache(
                commodity=commodity,
                variety=variety,
                market=market,
                district=district,
                state=state,
                arrival_date=arrival_date,
                limit=clamped_limit,
                offset=clamped_offset,
                delivery_status="CACHE_HIT",
                default_source="AGMARKNET",
            )
            # If we have recent data in DB within cache TTL, serve cache hit
            if cached_response.total > 0 and cached_response.freshness == "RECENT_CACHE":
                log.info(
                    "price_service.cache_hit",
                    count=len(cached_response.prices),
                    total=cached_response.total,
                )
                return cached_response

        # Attempt Live Upstream Fetch from AGMARKNET
        try:
            fetch_result = await self.client.fetch_prices(
                commodity=commodity,
                state=state,
                district=district,
                market=market,
                arrival_date=arrival_date.isoformat() if arrival_date else None,
                limit=clamped_limit,
                offset=clamped_offset,
            )

            # Ingest & Normalize
            normalized_items = [
                n
                for raw in fetch_result.records
                if (n := normalize_agmarknet_record(raw, fetch_result.fetched_at)) is not None
            ]

            if normalized_items:
                await self.upsert_prices(normalized_items)

            # Return newly refreshed records
            live_response = await self._query_database_cache(
                commodity=commodity,
                variety=variety,
                market=market,
                district=district,
                state=state,
                arrival_date=arrival_date,
                limit=clamped_limit,
                offset=clamped_offset,
                delivery_status="LIVE_API",
                default_source="AGMARKNET",
            )
            log.info(
                "price_service.live_delivery",
                fetched=len(normalized_items),
                returned=len(live_response.prices),
            )
            return live_response

        except Exception as exc:
            # Mask and classify failure, then fallback to recent DB data without mutating provider
            log.warning(
                "price_service.upstream_fallback",
                error_type=exc.__class__.__name__,
                provider=self.provider,
                message="AGMARKNET fetch failed; falling back to PostgreSQL cache",
            )
            return await self._query_database_cache(
                commodity=commodity,
                variety=variety,
                market=market,
                district=district,
                state=state,
                arrival_date=arrival_date,
                limit=clamped_limit,
                offset=clamped_offset,
                delivery_status="FALLBACK",
                default_source="AGMARKNET",
            )

    async def upsert_prices(self, records: Sequence[NormalizedMandiPrice]) -> int:
        """
        Atomically upsert normalized price records using the natural key constraint.

        Returns:
            Number of records upserted.
        """
        if not records:
            return 0

        values = [
            {
                "commodity": r.commodity,
                "variety": r.variety,
                "market": r.market,
                "district": r.district,
                "state": r.state,
                "arrival_date": r.arrival_date,
                "min_price": r.min_price,
                "max_price": r.max_price,
                "modal_price": r.modal_price,
                "unit": r.unit,
                "source": r.source,
                "source_record_id": r.source_record_id,
                "fetched_at": r.fetched_at,
            }
            for r in records
        ]

        stmt = pg_insert(MandiPrice).values(values)
        upsert_stmt = stmt.on_conflict_do_update(
            constraint="uq_mandi_prices_natural_key",
            set_={
                "min_price": stmt.excluded.min_price,
                "max_price": stmt.excluded.max_price,
                "modal_price": stmt.excluded.modal_price,
                "unit": stmt.excluded.unit,
                "source_record_id": stmt.excluded.source_record_id,
                "fetched_at": stmt.excluded.fetched_at,
                "updated_at": func.now(),
            },
        )

        await self.db.execute(upsert_stmt)
        await self.db.commit()
        return len(records)

    async def _query_database_cache(
        self,
        commodity: str | None,
        variety: str | None,
        market: str | None,
        district: str | None,
        state: str | None,
        arrival_date: date | None,
        limit: int,
        offset: int,
        delivery_status: DeliveryStatus,
        default_source: str,
    ) -> MandiPriceListResponse:
        """Query PostgreSQL mandi_prices table and construct response with freshness metrics."""
        query = select(MandiPrice)
        count_query = select(func.count(MandiPrice.id))

        if commodity:
            query = query.where(func.lower(MandiPrice.commodity) == commodity.strip().lower())
            count_query = count_query.where(
                func.lower(MandiPrice.commodity) == commodity.strip().lower()
            )
        if variety:
            query = query.where(func.lower(MandiPrice.variety) == variety.strip().lower())
            count_query = count_query.where(
                func.lower(MandiPrice.variety) == variety.strip().lower()
            )
        if market:
            query = query.where(func.lower(MandiPrice.market) == market.strip().lower())
            count_query = count_query.where(
                func.lower(MandiPrice.market) == market.strip().lower()
            )
        if district:
            query = query.where(func.lower(MandiPrice.district) == district.strip().lower())
            count_query = count_query.where(
                func.lower(MandiPrice.district) == district.strip().lower()
            )
        if state:
            query = query.where(func.lower(MandiPrice.state) == state.strip().lower())
            count_query = count_query.where(
                func.lower(MandiPrice.state) == state.strip().lower()
            )
        if arrival_date:
            query = query.where(MandiPrice.arrival_date == arrival_date)
            count_query = count_query.where(MandiPrice.arrival_date == arrival_date)

        # Count total matches
        total_count = (await self.db.execute(count_query)).scalar() or 0

        # Pagination & Sorting
        query = query.order_by(MandiPrice.arrival_date.desc(), MandiPrice.modal_price.desc())
        query = query.limit(limit).offset(offset)

        result = await self.db.execute(query)
        db_rows = result.scalars().all()

        today = date.today()
        now_utc = datetime.now(timezone.utc)
        items: list[MandiPriceItem] = []
        most_recent_fetch: datetime | None = None
        inferred_source = default_source

        for row in db_rows:
            inferred_source = row.source
            if most_recent_fetch is None or row.fetched_at > most_recent_fetch:
                most_recent_fetch = row.fetched_at

            data_age = max(0, (today - row.arrival_date).days)
            items.append(
                MandiPriceItem(
                    id=row.id,
                    commodity=row.commodity,
                    variety=row.variety,
                    market=row.market,
                    district=row.district,
                    state=row.state,
                    arrival_date=row.arrival_date,
                    min_price=row.min_price,
                    max_price=row.max_price,
                    modal_price=row.modal_price,
                    unit=row.unit,
                    source=row.source,
                    source_record_id=row.source_record_id,
                    fetched_at=row.fetched_at,
                    data_age_days=data_age,
                )
            )

        # Calculate cache age and freshness
        cache_age_seconds: float | None = None
        if most_recent_fetch:
            # Ensure timezone awareness for math
            if most_recent_fetch.tzinfo is None:
                most_recent_fetch = most_recent_fetch.replace(tzinfo=timezone.utc)
            cache_age_seconds = max(0.0, (now_utc - most_recent_fetch).total_seconds())

        # Determine freshness level
        freshness: FreshnessLevel
        if not items:
            freshness = "NO_DATA"
        elif delivery_status == "LIVE_API":
            freshness = "LIVE"
        elif delivery_status == "DEMO" or inferred_source == "DEMO_SEED":
            freshness = "DEMO"
        elif cache_age_seconds is not None and cache_age_seconds <= (settings.PRICE_CACHE_TTL_HOURS * 3600):
            freshness = "RECENT_CACHE"
        else:
            freshness = "STALE_CACHE"

        is_live = delivery_status == "LIVE_API"

        return MandiPriceListResponse(
            prices=items,
            total=total_count,
            limit=limit,
            offset=offset,
            source=inferred_source,
            delivery_status=delivery_status,
            is_live=is_live,
            freshness=freshness,
            cache_age_seconds=round(cache_age_seconds, 1) if cache_age_seconds is not None else None,
            last_updated=most_recent_fetch,
        )

    def _generate_mock_response(
        self,
        commodity: str | None,
        market: str | None,
        limit: int,
        offset: int,
    ) -> MandiPriceListResponse:
        """Generate static mock response for disconnected unit testing."""
        now = datetime.now(timezone.utc)
        today = date.today()
        mock_item = MandiPriceItem(
            id="mock-price-1",
            commodity=commodity or "Wheat",
            variety="Sharbati",
            market=market or "Sehore Mandi",
            district="Sehore",
            state="Madhya Pradesh",
            arrival_date=today,
            min_price=Decimal("2350.00"),
            max_price=Decimal("2550.00"),
            modal_price=Decimal("2450.00"),
            unit="₹/quintal",
            source="MOCK",
            source_record_id="mock-1",
            fetched_at=now,
            data_age_days=0,
        )
        return MandiPriceListResponse(
            prices=[mock_item],
            total=1,
            limit=limit,
            offset=offset,
            source="MOCK",
            delivery_status="DEMO",
            is_live=False,
            freshness="DEMO",
            cache_age_seconds=0.0,
            last_updated=now,
        )
