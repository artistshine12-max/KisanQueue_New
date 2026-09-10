"""
modules/prices/sync.py — Observable scheduled & batch synchronization worker.

Synchronizes daily wholesale commodity prices from AGMARKNET / data.gov.in into
the KisanQueue PostgreSQL database.

Observability Features:
1. Emits structured JSON log events at startup, per-batch, and completion with latency and counts.
2. Maintains the latest sync execution telemetry in module-level state for API observability.
3. Independently executable via CLI: `python -m modules.prices.sync` or `python -m backend.modules.prices.sync`.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import datetime, timezone
from typing import Sequence

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import structlog

from core.config import settings
from core.database import close_db_pool, get_session_factory, init_db_pool
from modules.prices.agmarknet_client import AgmarknetClient
from modules.prices.normalizer import normalize_agmarknet_record
from modules.prices.schemas import PriceSyncSummary
from modules.prices.service import PriceService

log = structlog.get_logger(__name__)

# Telemetry tracker for latest sync run (observable by API)
_LATEST_SYNC_SUMMARY: PriceSyncSummary | None = None

# Default high-priority agricultural commodities for KisanQueue mandis
DEFAULT_SYNC_COMMODITIES = (
    "Wheat",
    "Paddy(Dhan)",
    "Mustard",
    "Soyabean",
    "Maize",
    "Gram",
    "Cotton",
    "Tomato",
    "Onion",
    "Potato",
)


def get_latest_sync_summary() -> PriceSyncSummary | None:
    """Return the telemetry summary of the most recent sync execution."""
    return _LATEST_SYNC_SUMMARY


async def run_price_sync(
    commodities: Sequence[str] = DEFAULT_SYNC_COMMODITIES,
    state: str | None = None,
    limit_per_commodity: int = 50,
    api_key: str | None = None,
    client: AgmarknetClient | None = None,
) -> PriceSyncSummary:
    """
    Execute daily price synchronization across monitored commodities.
    """
    global _LATEST_SYNC_SUMMARY

    start_time = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    total_fetched = 0
    total_normalized = 0
    total_upserted = 0
    total_skipped = 0
    error_message = None
    success = True

    log.info(
        "prices.sync.started",
        provider=settings.PRICE_PROVIDER,
        commodities_count=len(commodities),
        state=state,
        started_at=started_at.isoformat(),
    )

    ag_client = client or AgmarknetClient(api_key=api_key)

    try:
        session_factory = get_session_factory()
        async with session_factory() as session:
            service = PriceService(db_session=session, agmarknet_client=ag_client)

            for commodity in commodities:
                commodity_start = time.perf_counter()
                try:
                    fetch_res = await ag_client.fetch_prices(
                        commodity=commodity,
                        state=state,
                        limit=limit_per_commodity,
                    )
                    raw_count = len(fetch_res.records)
                    total_fetched += raw_count

                    valid_items = []
                    for raw in fetch_res.records:
                        norm = normalize_agmarknet_record(raw, fetch_res.fetched_at)
                        if norm:
                            valid_items.append(norm)
                        else:
                            total_skipped += 1

                    total_normalized += len(valid_items)

                    if valid_items:
                        upserted = await service.upsert_prices(valid_items)
                        total_upserted += upserted

                    log.info(
                        "prices.sync.commodity_batch",
                        commodity=commodity,
                        fetched=raw_count,
                        valid=len(valid_items),
                        duration_ms=round((time.perf_counter() - commodity_start) * 1000, 2),
                    )

                    # Polite rate-limiting between commodity calls
                    await asyncio.sleep(0.3)

                except Exception as comm_err:
                    log.warning(
                        "prices.sync.commodity_failed",
                        commodity=commodity,
                        error=str(comm_err),
                    )
                    # Do not abort entire sync job on single commodity failure
                    continue

    except Exception as exc:
        success = False
        error_message = str(exc)
        log.error("prices.sync.fatal_error", error=error_message)

    completed_at = datetime.now(timezone.utc)
    duration_seconds = round(time.perf_counter() - start_time, 2)

    summary = PriceSyncSummary(
        provider=settings.PRICE_PROVIDER,
        started_at=started_at,
        completed_at=completed_at,
        duration_seconds=duration_seconds,
        total_fetched=total_fetched,
        total_normalized=total_normalized,
        total_upserted=total_upserted,
        total_skipped=total_skipped,
        success=success,
        error_message=error_message,
    )

    _LATEST_SYNC_SUMMARY = summary

    log.info(
        "prices.sync.completed",
        success=success,
        total_fetched=total_fetched,
        total_normalized=total_normalized,
        total_upserted=total_upserted,
        total_skipped=total_skipped,
        duration_seconds=duration_seconds,
    )

    return summary


def main() -> None:
    """CLI entrypoint for executing sync jobs from crontab or command line."""
    parser = argparse.ArgumentParser(description="KisanQueue Mandi Price Synchronization")
    parser.add_argument(
        "--commodity",
        nargs="*",
        default=list(DEFAULT_SYNC_COMMODITIES),
        help="Commodity names to synchronize (default: core agricultural commodities)",
    )
    parser.add_argument("--state", default=None, help="State filter (e.g., 'Madhya Pradesh')")
    parser.add_argument("--limit", type=int, default=50, help="Max records per commodity")
    args = parser.parse_args()

    async def _runner() -> None:
        await init_db_pool()
        try:
            summary = await run_price_sync(
                commodities=args.commodity,
                state=args.state,
                limit_per_commodity=args.limit,
            )
            print(summary.model_dump_json(indent=2))
        finally:
            await close_db_pool()

    asyncio.run(_runner())


if __name__ == "__main__":
    main()
