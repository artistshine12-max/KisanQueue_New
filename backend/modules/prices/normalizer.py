"""
modules/prices/normalizer.py — Data sanitization and normalization for AGMARKNET records.

Transforms raw, inconsistent government platform dictionaries into validated,
strictly typed NormalizedMandiPrice instances.

Key Invariants:
1. Invalid prices ("", "N/A", "-", null, <= 0) are NEVER silently converted to 0.
   Such malformed records are rejected and logged.
2. Multiple arrival date formats ("DD/MM/YYYY", "YYYY-MM-DD", "DD-MM-YYYY") are supported.
3. String attributes are trimmed, standardized in title case, and checked for empty values.
4. Monetary values are rounded and stored as Decimal to prevent floating point inaccuracies.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# Common placeholders indicating missing/null data in government tables
_NULL_SENTINELS = frozenset({"", "n/a", "na", "-", "--", "null", "none", "nil", "0", "0.0", "0.00"})


@dataclass(frozen=True)
class NormalizedMandiPrice:
    """Immutable, strongly typed representation of a validated market arrival price."""

    commodity: str
    variety: str
    market: str
    district: str
    state: str
    arrival_date: date
    min_price: Decimal
    max_price: Decimal
    modal_price: Decimal
    unit: str
    source: str
    source_record_id: str | None
    fetched_at: datetime


def parse_arrival_date(value: Any) -> date | None:
    """
    Parse a date string or object into a datetime.date.

    Supports:
    - datetime.date or datetime.datetime instances
    - "DD/MM/YYYY" (most common in AGMARKNET data.gov.in)
    - "YYYY-MM-DD" (ISO format)
    - "DD-MM-YYYY"
    - "YYYY/MM/DD"
    """
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    if not isinstance(value, str):
        return None

    clean_str = value.strip()
    if not clean_str:
        return None

    formats = [
        "%d/%m/%Y",  # 04/10/2026
        "%Y-%m-%d",  # 2026-10-04
        "%d-%m-%Y",  # 04-10-2026
        "%Y/%m/%d",  # 2026/10/04
        "%d.%m.%Y",  # 04.10.2026
    ]

    for fmt in formats:
        try:
            return datetime.strptime(clean_str, fmt).date()
        except ValueError:
            continue

    return None


def parse_price(value: Any, field_name: str = "price") -> Decimal | None:
    """
    Parse a monetary string into a positive Decimal rounded to 2 decimal places.

    Rejects missing, null-sentinel, zero, and negative values. Never returns 0.
    """
    if value is None:
        return None

    if isinstance(value, (int, float, Decimal)):
        try:
            d = Decimal(str(value))
        except (InvalidOperation, TypeError):
            return None
    elif isinstance(value, str):
        clean = value.strip().lower()
        if clean in _NULL_SENTINELS:
            return None
        is_negative = clean.startswith("-") or "-" in clean
        # Remove currency symbols (₹, Rs, INR) and thousands separators
        clean_num = re.sub(r"[^\d.]", "", clean)
        if not clean_num:
            return None
        try:
            d = Decimal(clean_num)
            if is_negative:
                d = -d
        except InvalidOperation:
            return None
    else:
        return None

    # Mandi wholesale prices must be strictly positive
    if d <= Decimal("0"):
        return None

    return d.quantize(Decimal("0.01"))


def clean_text(value: Any, default: str = "") -> str:
    """Strip whitespace and normalize spaces."""
    if value is None:
        return default
    s = str(value).strip()
    if not s or s.lower() in _NULL_SENTINELS:
        return default
    # Collapse multiple spaces into one
    return re.sub(r"\s+", " ", s).title()


def normalize_agmarknet_record(
    raw: dict[str, Any],
    fetched_at: datetime | None = None,
    source: str = "AGMARKNET",
) -> NormalizedMandiPrice | None:
    """
    Normalize a raw record from data.gov.in AGMARKNET response.

    Returns NormalizedMandiPrice if valid, or None if malformed/unusable.
    """
    if not isinstance(raw, dict):
        log.debug("normalizer.skipped_non_dict_record", raw=raw)
        return None

    # 1. Commodity validation
    commodity = clean_text(raw.get("commodity") or raw.get("Commodity"))
    if not commodity:
        log.debug("normalizer.skipped_missing_commodity", raw=raw)
        return None

    # 2. Location hierarchy validation
    market = clean_text(raw.get("market") or raw.get("Market") or raw.get("mandi"))
    district = clean_text(raw.get("district") or raw.get("District"))
    state = clean_text(raw.get("state") or raw.get("State"))

    if not market or not state:
        log.debug("normalizer.skipped_missing_location", market=market, state=state)
        return None
    if not district:
        district = market  # Fallback to market name if district is blank

    # 3. Variety (defaults to "Local" if omitted)
    variety = clean_text(raw.get("variety") or raw.get("Variety"), default="Local")

    # 4. Arrival Date validation
    raw_date = raw.get("arrival_date") or raw.get("Arrival_Date") or raw.get("date")
    arrival_date = parse_arrival_date(raw_date)
    if not arrival_date:
        log.debug("normalizer.skipped_invalid_date", raw_date=raw_date)
        return None

    # 5. Price validations (modal_price is strictly mandatory)
    raw_modal = raw.get("modal_price") or raw.get("Modal_Price") or raw.get("modal")
    modal_price = parse_price(raw_modal, field_name="modal_price")
    if modal_price is None:
        log.debug("normalizer.skipped_missing_modal_price", raw_modal=raw_modal)
        return None

    raw_min = raw.get("min_price") or raw.get("Min_Price") or raw.get("min")
    raw_max = raw.get("max_price") or raw.get("Max_Price") or raw.get("max")
    min_price = parse_price(raw_min, field_name="min_price") or modal_price
    max_price = parse_price(raw_max, field_name="max_price") or modal_price

    # Ensure min <= max invariant
    if min_price > max_price:
        min_price, max_price = max_price, min_price

    # Clamp modal if out of bounds due to reporting discrepancies
    if modal_price < min_price:
        modal_price = min_price
    elif modal_price > max_price:
        modal_price = max_price

    # 6. Metadata
    now_utc = fetched_at or datetime.now(timezone.utc)
    source_record_id = None
    for id_key in ("_id", "id", "record_id", "timestamp"):
        if raw.get(id_key) is not None:
            source_record_id = str(raw[id_key]).strip()
            break

    return NormalizedMandiPrice(
        commodity=commodity,
        variety=variety,
        market=market,
        district=district,
        state=state,
        arrival_date=arrival_date,
        min_price=min_price,
        max_price=max_price,
        modal_price=modal_price,
        unit="₹/quintal",
        source=source,
        source_record_id=source_record_id,
        fetched_at=now_utc,
    )
