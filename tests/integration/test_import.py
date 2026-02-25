from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.database import init_db
from app.main import app


@pytest.fixture(autouse=True)
async def setup_db(tmp_path):
    """Set up a test database for each test."""
    db_path = tmp_path / "test.db"

    # Monkey-patch the database URL for this test
    import app.core.config as cfg

    original_url = cfg.settings.database_url
    cfg.settings.database_url = str(db_path)

    # Initialize the test database
    await init_db()

    yield

    # Restore original URL
    cfg.settings.database_url = original_url


@pytest.fixture
def client():
    """Return a TestClient for the app."""
    return TestClient(app)


def test_import_pgn_basic(client):
    """Test basic PGN import with a single line."""
    # First, create a theme
    theme_res = client.post("/themes", json={"name": "Test"})
    assert theme_res.status_code == 201
    theme_id = theme_res.json()["id"]

    # Import a simple PGN
    pgn = "1. e4 e5 2. Nf3 Nc6"
    import_res = client.post(
        "/import/pgn",
        json={"pgn": pgn, "theme_id": theme_id, "base_sort_order": 0},
    )

    assert import_res.status_code == 201
    result = import_res.json()
    assert result["lines_created"] == 1
    assert result["lines_total"] == 1
    assert len(result["lines"]) == 1

    line = result["lines"][0]
    # PGN parser returns moves in SAN format
    assert line["moves"] == "e4 e5 Nf3 Nc6"
    assert line["move_count"] == 4


def test_import_pgn_with_variations(client):
    """Test PGN import with multiple variations."""
    # Create a theme
    theme_res = client.post("/themes", json={"name": "Test"})
    assert theme_res.status_code == 201
    theme_id = theme_res.json()["id"]

    # Import a PGN with variations
    pgn = """
    [Event "Test"]
    1. e4 e5 2. Nf3 Nc6 3. Bb5 (3. Bc4 Nf6) 3... a6
    """
    import_res = client.post(
        "/import/pgn",
        json={"pgn": pgn, "theme_id": theme_id},
    )

    assert import_res.status_code == 201
    result = import_res.json()
    # Should have 2 variations: main line (Bb5) and variation (Bc4)
    assert result["lines_total"] == 2
    assert result["lines_created"] == 2


def test_import_pgn_invalid_fen(client):
    """Test that PGN without valid moves is accepted but has no lines."""
    # Create a theme
    theme_res = client.post("/themes", json={"name": "Test"})
    assert theme_res.status_code == 201
    theme_id = theme_res.json()["id"]

    # Try to import invalid PGN
    # Note: chess.pgn.read_game() is very lenient and returns a default game
    # with no moves when given invalid input. This is accepted as empty line.
    import_res = client.post(
        "/import/pgn",
        json={"pgn": "not a valid pgn", "theme_id": theme_id},
    )

    # Empty PGN results in a line with no moves
    assert import_res.status_code == 201
    result = import_res.json()
    assert result["lines_total"] == 1
    assert result["lines_created"] == 1
    assert result["lines"][0]["moves"] == ""


def test_import_pgn_nonexistent_theme(client):
    """Test that import fails if theme doesn't exist."""
    pgn = "1. e4 e5"
    import_res = client.post(
        "/import/pgn",
        json={"pgn": pgn, "theme_id": 9999},
    )

    assert import_res.status_code == 404
