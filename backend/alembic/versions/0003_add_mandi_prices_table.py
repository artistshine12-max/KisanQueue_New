"""Add mandi_prices table with deduplication constraints and indices.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mandi_prices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("commodity", sa.String(length=100), nullable=False),
        sa.Column("variety", sa.String(length=100), server_default="Local", nullable=False),
        sa.Column("market", sa.String(length=150), nullable=False),
        sa.Column("district", sa.String(length=100), nullable=False),
        sa.Column("state", sa.String(length=100), nullable=False),
        sa.Column("arrival_date", sa.Date(), nullable=False),
        sa.Column("min_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("max_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("modal_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("unit", sa.String(length=30), server_default="₹/quintal", nullable=False),
        sa.Column("source", sa.String(length=50), server_default="AGMARKNET", nullable=False),
        sa.Column("source_record_id", sa.String(length=100), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "commodity",
            "variety",
            "market",
            "arrival_date",
            "source",
            name="uq_mandi_prices_natural_key",
        ),
    )

    op.create_index("ix_mandi_prices_commodity", "mandi_prices", ["commodity"])
    op.create_index("ix_mandi_prices_market", "mandi_prices", ["market"])
    op.create_index("ix_mandi_prices_district", "mandi_prices", ["district"])
    op.create_index("ix_mandi_prices_state", "mandi_prices", ["state"])
    op.create_index("ix_mandi_prices_arrival_date", "mandi_prices", ["arrival_date"])
    op.create_index("ix_mandi_prices_source_record_id", "mandi_prices", ["source_record_id"])
    op.create_index("ix_mandi_prices_commodity_market", "mandi_prices", ["commodity", "market"])
    op.create_index("ix_mandi_prices_state_district", "mandi_prices", ["state", "district"])


def downgrade() -> None:
    op.drop_index("ix_mandi_prices_state_district", table_name="mandi_prices")
    op.drop_index("ix_mandi_prices_commodity_market", table_name="mandi_prices")
    op.drop_index("ix_mandi_prices_source_record_id", table_name="mandi_prices")
    op.drop_index("ix_mandi_prices_arrival_date", table_name="mandi_prices")
    op.drop_index("ix_mandi_prices_state", table_name="mandi_prices")
    op.drop_index("ix_mandi_prices_district", table_name="mandi_prices")
    op.drop_index("ix_mandi_prices_market", table_name="mandi_prices")
    op.drop_index("ix_mandi_prices_commodity", table_name="mandi_prices")
    op.drop_table("mandi_prices")
