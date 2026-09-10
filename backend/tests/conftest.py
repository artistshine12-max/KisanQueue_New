"""
tests/conftest.py — Pytest configuration.

Markers:
  db — tests that require a live PostgreSQL connection. Apply with
       @pytest.mark.db or pytestmark = [pytest.mark.db] at module level.
       Pure unit tests (e.g. test_eta.py) do NOT use this marker and
       run without any infrastructure.
"""
import asyncio
import os
import sys

# Ensure required environment variables exist for tests before settings are initialized
os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://postgres:password@127.0.0.1:5432/kisanqueue")
os.environ.setdefault("JWT_SECRET_KEY", "test_jwt_secret_key_minimum_32_bytes_long_123456")
os.environ.setdefault("QR_HMAC_SECRET", "test_qr_hmac_secret_minimum_32_bytes_long_123456")

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import pytest
from httpx import AsyncClient, ASGITransport

from main import app
from core.database import init_db_pool, close_db_pool, get_session_factory
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def db_pool():
    """Initialise and tear down the async DB connection pool.

    Use via @pytest.mark.usefixtures("db_pool") or as an explicit
    fixture argument. Do NOT add autouse=True — tests without a DB
    dependency must remain infrastructure-free.
    """
    await init_db_pool()
    yield
    await close_db_pool()


@pytest.fixture
async def db_session(db_pool) -> AsyncSession:
    """Scoped async session fixture for database-level integration tests."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


@pytest.fixture
async def async_client(db_pool) -> AsyncClient:
    """HTTP test client backed by the ASGI app (requires db_pool)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

