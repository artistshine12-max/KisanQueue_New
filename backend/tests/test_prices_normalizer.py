"""
tests/test_prices_normalizer.py — Unit tests for AGMARKNET record normalization.

Tests date parsing, string sanitization, monetary validation, and error rejection.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from modules.prices.normalizer import (
    clean_text,
    normalize_agmarknet_record,
    parse_arrival_date,
    parse_price,
)


def test_parse_arrival_date_formats():
    """Verify various standard Indian date formats parse correctly."""
    assert parse_arrival_date("04/10/2026") == date(2026, 10, 4)
    assert parse_arrival_date("2026-10-04") == date(2026, 10, 4)
    assert parse_arrival_date("04-10-2026") == date(2026, 10, 4)
    assert parse_arrival_date("2026/10/04") == date(2026, 10, 4)
    assert parse_arrival_date("04.10.2026") == date(2026, 10, 4)
    assert parse_arrival_date(date(2026, 10, 4)) == date(2026, 10, 4)
    assert parse_arrival_date(datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)) == date(2026, 10, 4)


def test_parse_arrival_date_invalid():
    """Verify malformed and empty dates return None."""
    assert parse_arrival_date(None) is None
    assert parse_arrival_date("") is None
    assert parse_arrival_date("   ") is None
    assert parse_arrival_date("not-a-date") is None
    assert parse_arrival_date("32/01/2026") is None
    assert parse_arrival_date(12345) is None


def test_parse_price_valid():
    """Verify positive monetary values parse to Decimal with 2 decimal places."""
    assert parse_price("2100") == Decimal("2100.00")
    assert parse_price("2100.5") == Decimal("2100.50")
    assert parse_price("2,350.75") == Decimal("2350.75")
    assert parse_price("₹ 2400") == Decimal("2400.00")
    assert parse_price(2500) == Decimal("2500.00")
    assert parse_price(2500.25) == Decimal("2500.25")
    assert parse_price(Decimal("2500.50")) == Decimal("2500.50")


def test_parse_price_invalid_never_becomes_zero():
    """
    CRITICAL RULE: Empty, null-sentinel, zero, or negative prices must return None,
    NEVER silently convert into 0.
    """
    assert parse_price(None) is None
    assert parse_price("") is None
    assert parse_price("  ") is None
    assert parse_price("N/A") is None
    assert parse_price("na") is None
    assert parse_price("-") is None
    assert parse_price("--") is None
    assert parse_price("null") is None
    assert parse_price("none") is None
    assert parse_price("0") is None
    assert parse_price(0) is None
    assert parse_price("0.00") is None
    assert parse_price("-100") is None
    assert parse_price(-50.0) is None


def test_clean_text():
    """Verify whitespace stripping and casing normalization."""
    assert clean_text("  wheat  ") == "Wheat"
    assert clean_text("PADDY (DHAN)") == "Paddy (Dhan)"
    assert clean_text("sehore   mandi") == "Sehore Mandi"
    assert clean_text("", default="Local") == "Local"
    assert clean_text(None, default="Local") == "Local"
    assert clean_text("N/A", default="Local") == "Local"


def test_normalize_valid_agmarknet_record():
    """Verify end-to-end normalization of a realistic government payload."""
    raw = {
        "state": "Madhya Pradesh",
        "district": "Sehore",
        "market": "Sehore Mandi",
        "commodity": "Wheat",
        "variety": "Sharbati",
        "arrival_date": "04/10/2026",
        "min_price": "2400",
        "max_price": "2650",
        "modal_price": "2520",
        "_id": "row-12345",
    }
    fixed_now = datetime(2026, 10, 4, 10, 0, tzinfo=timezone.utc)
    result = normalize_agmarknet_record(raw, fetched_at=fixed_now)

    assert result is not None
    assert result.commodity == "Wheat"
    assert result.variety == "Sharbati"
    assert result.market == "Sehore Mandi"
    assert result.district == "Sehore"
    assert result.state == "Madhya Pradesh"
    assert result.arrival_date == date(2026, 10, 4)
    assert result.min_price == Decimal("2400.00")
    assert result.max_price == Decimal("2650.00")
    assert result.modal_price == Decimal("2520.00")
    assert result.unit == "₹/quintal"
    assert result.source == "AGMARKNET"
    assert result.source_record_id == "row-12345"
    assert result.fetched_at == fixed_now


def test_normalize_record_swaps_inverted_min_max():
    """If min_price > max_price due to entry error, swap them."""
    raw = {
        "state": "Punjab",
        "district": "Amritsar",
        "market": "Amritsar",
        "commodity": "Wheat",
        "arrival_date": "2026-10-04",
        "min_price": "2600",
        "max_price": "2400",
        "modal_price": "2500",
    }
    result = normalize_agmarknet_record(raw)
    assert result is not None
    assert result.min_price == Decimal("2400.00")
    assert result.max_price == Decimal("2600.00")
    assert result.modal_price == Decimal("2500.00")


def test_normalize_record_missing_required_fields_returns_none():
    """Records missing critical fields must be rejected, not stored with corrupt data."""
    # Missing commodity
    assert normalize_agmarknet_record({
        "state": "MP", "market": "Sehore", "arrival_date": "04/10/2026", "modal_price": "2500"
    }) is None

    # Missing location
    assert normalize_agmarknet_record({
        "commodity": "Wheat", "arrival_date": "04/10/2026", "modal_price": "2500"
    }) is None

    # Missing arrival date
    assert normalize_agmarknet_record({
        "commodity": "Wheat", "state": "MP", "market": "Sehore", "modal_price": "2500"
    }) is None

    # Missing or sentinel modal price (must be rejected)
    assert normalize_agmarknet_record({
        "commodity": "Wheat", "state": "MP", "market": "Sehore", "arrival_date": "04/10/2026",
        "modal_price": "N/A"
    }) is None

    assert normalize_agmarknet_record({
        "commodity": "Wheat", "state": "MP", "market": "Sehore", "arrival_date": "04/10/2026",
        "modal_price": "0"
    }) is None
