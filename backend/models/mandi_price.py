"""
models/mandi_price.py — SQLAlchemy model for daily mandi commodity prices.

Stores normalized market arrival prices fetched from AGMARKNET / data.gov.in
or seeded fallback data.

Deduplication & Natural Key Decision:
AGMARKNET (data.gov.in resource 9ef84268-d588-465a-a308-a864a43d0070) returns
records containing: state, district, market, commodity, variety, arrival_date,
min_price, max_price, modal_price.

Upstream records lack a permanent global GUID across daily batches. Therefore,
we store `source_record_id` when present (e.g., OGD row index or record id),
and enforce an authoritative composite natural unique constraint:
    (commodity, variety, market, arrival_date, source)
This guarantees:
1. Re-running the daily sync job updates existing prices via ON CONFLICT DO UPDATE
   instead of inserting duplicate rows.
2. Distinct varieties or commodities arriving at the same mandi on the same day
   are preserved independently.
3. Monetary values use Numeric(10, 2) to eliminate floating-point imprecision.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from models.base import Base, TimestampMixin, uuid_pk


class MandiPrice(Base, TimestampMixin):
    """
    Daily wholesale arrival price for an agricultural commodity at a specific mandi.
    """

    __tablename__ = "mandi_prices"

    id: Mapped[str] = uuid_pk()

    # Commodity and variety categorization
    commodity: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    variety: Mapped[str] = mapped_column(String(100), nullable=False, default="Local")

    # Geospatial market hierarchy
    market: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    district: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Market arrival date (data age)
    arrival_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Price attributes (stored as Numeric(10, 2) — ₹ per unit)
    min_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    max_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    modal_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    # Unit of measure (e.g., ₹/quintal)
    unit: Mapped[str] = mapped_column(String(30), nullable=False, default="₹/quintal")

    # Provenance and caching audit metadata
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="AGMARKNET")
    source_record_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "commodity",
            "variety",
            "market",
            "arrival_date",
            "source",
            name="uq_mandi_prices_natural_key",
        ),
        Index("ix_mandi_prices_commodity_market", "commodity", "market"),
        Index("ix_mandi_prices_state_district", "state", "district"),
        Index("ix_mandi_prices_arrival_date_desc", arrival_date.desc()),
    )

    def __repr__(self) -> str:
        return (
            f"<MandiPrice(commodity='{self.commodity}', variety='{self.variety}', "
            f"market='{self.market}', date='{self.arrival_date}', modal={self.modal_price})>"
        )
