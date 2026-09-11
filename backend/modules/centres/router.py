"""
modules/centres/router.py — Centre listing endpoint.

Routes:
    GET /v1/centres  — List all active centres with live ETA
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Query
from sqlalchemy import func, select

from core.dependencies import AnyAuthenticatedUser, DbSession
from models.capacity_update import CapacityUpdate
from models.centre import Centre
from models.queue_entry import QueueEntry
from modules.centres.schemas import CentreListResponse, CentreSummary
from modules.eta.engine import compute_eta

router = APIRouter()
log = structlog.get_logger(__name__)

ACTIVE_STATUSES = ("WAITING", "CHECKED_IN", "PROCESSING")


@router.get("", response_model=CentreListResponse)
async def list_centres(
    db: DbSession,
    payload: AnyAuthenticatedUser,
    district: str | None = Query(None),
    crop: str | None = Query(None),
) -> CentreListResponse:
    """
    List all active procurement centres with live queue length and ETA.

    Optional filters:
        district: filter by district name (case-insensitive contains)
        crop: filter to centres that support this crop
    """
    stmt = select(Centre).where(Centre.is_active == True)  # noqa: E712
    result = await db.execute(stmt)
    centres = result.scalars().all()

    summaries = []
    for centre in centres:
        # Optional filtering
        if district and district.lower() not in centre.district.lower():
            continue
        if crop and crop not in centre.supported_crops:
            continue

        # Latest capacity update
        cap_result = await db.execute(
            select(CapacityUpdate)
            .where(CapacityUpdate.centre_id == centre.id)
            .order_by(CapacityUpdate.effective_from.desc())
            .limit(1)
        )
        cap = cap_result.scalar_one_or_none()

        status = cap.status if cap else "NORMAL"
        capacity_factor = cap.capacity_factor if cap else 1.0
        active_counters = cap.active_counters if cap else centre.active_counters_default
        note = cap.note if cap else None
        last_update_at = cap.effective_from if cap else None

        # Queue length = count of active entries
        count_result = await db.execute(
            select(func.count(QueueEntry.id)).where(
                QueueEntry.centre_id == centre.id,
                QueueEntry.status.in_(ACTIVE_STATUSES),
            )
        )
        queue_length = count_result.scalar() or 0

        # ETA for last position in queue (= queue_length)
        eta_result = compute_eta(
            n=max(queue_length, 0),
            t_base=centre.avg_processing_minutes,
            active_counters=active_counters,
            capacity_factor=capacity_factor,
            status=status,
            last_update_at=last_update_at,
        )

        # Freshness in minutes
        updated_minutes_ago: int | None = None
        if last_update_at:
            if last_update_at.tzinfo is None:
                last_update_at = last_update_at.replace(tzinfo=timezone.utc)
            delta = datetime.now(timezone.utc) - last_update_at
            updated_minutes_ago = int(delta.total_seconds() / 60)

        summaries.append(
            CentreSummary(
                id=centre.id,
                name=centre.name,
                hindi_name=centre.hindi_name,
                district=centre.district,
                state=centre.state,
                status=status,
                queue_length=queue_length,
                eta_minutes=eta_result.eta_minutes,
                eta_confidence=eta_result.confidence,
                active_counters=active_counters,
                capacity_factor=capacity_factor,
                avg_processing_minutes=centre.avg_processing_minutes,
                supported_crops=centre.supported_crops,
                note=note,
                updated_minutes_ago=updated_minutes_ago,
            )
        )

    return CentreListResponse(centres=summaries, count=len(summaries))
from fastapi import APIRouter

router = APIRouter()
from fastapi import APIRouter

router = APIRouter()

sample_centres = [
    {
        "centre_id": 101,
        "name": "Karnal Grain Procurement Centre",
        "location": "Karnal, Haryana",
        "capacity_quintals": 5000,
        "current_queue_length": 42,
        "contact_number": "+91-9876543210"
    },
    {
        "centre_id": 102,
        "name": "Panipat Mandi Procurement Centre",
        "location": "Panipat, Haryana",
        "capacity_quintals": 3500,
        "current_queue_length": 28,
        "contact_number": "+91-9812345678"
    },
    {
        "centre_id": 103,
        "name": "Kurukshetra MSP Procurement Centre",
        "location": "Kurukshetra, Haryana",
        "capacity_quintals": 4200,
        "current_queue_length": 15,
        "contact_number": "+91-9123456789"
    },
    {
        "centre_id": 104,
        "name": "Ambala Grain Collection Centre",
        "location": "Ambala, Haryana",
        "capacity_quintals": 6000,
        "current_queue_length": 55,
        "contact_number": "+91-9988776655"
    },
    {
        "centre_id": 105,
        "name": "Delhi Azadpur Procurement Centre",
        "location": "Delhi",
        "capacity_quintals": 7000,
        "current_queue_length": 63,
        "contact_number": "+91-9876501234"
    },
    {
        "centre_id": 106,
        "name": "Hisar Grain Procurement Centre",
        "location": "Hisar, Haryana",
        "capacity_quintals": 4800,
        "current_queue_length": 34,
        "contact_number": "+91-9765432109"
    },
    {
        "centre_id": 107,
        "name": "Sonipat MSP Procurement Centre",
        "location": "Sonipat, Haryana",
        "capacity_quintals": 5200,
        "current_queue_length": 22,
        "contact_number": "+91-9654321098"
    }
]

@router.get("/nearby")
async def get_nearby_centres():
    return sample_centres



@router.get("/nearby")
async def get_nearby_centres():
    return sample_centres
