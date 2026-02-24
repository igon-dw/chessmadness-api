"""
Shared pytest fixtures.

Each test gets a fresh in-memory SQLite database so tests are fully isolated.
The FastAPI TestClient is patched to use this temporary DB.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.database import init_db


@pytest.fixture(autouse=True)
def use_temp_db(tmp_path, monkeypatch):
    """Point the app at a fresh SQLite file for each test."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(settings, "database_url", db_path)


@pytest.fixture
async def client():
    """Async HTTPX client wired to the FastAPI app with a fresh DB."""
    # Import app *after* monkeypatching settings so the lifespan uses the temp DB
    from app.main import app

    await init_db()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac
