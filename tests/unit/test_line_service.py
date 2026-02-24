"""
Unit tests for the line_service module.

These tests use a real in-memory SQLite database (via the conftest fixtures)
rather than mocks, because line_service is tightly coupled to the DB schema.
This is intentionally lightweight — heavy scenario testing lives in
tests/integration/test_lines.py.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.database import get_db, init_db
from app.schemas.lines import LineCreate
from app.services.fen_index import InvalidMoveError
from app.services.line_service import register_line

STANDARD_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db(tmp_path, monkeypatch):
    """Fresh in-memory SQLite DB for each test."""
    db_path = str(tmp_path / "unit_test.db")
    monkeypatch.setattr(settings, "database_url", db_path)
    await init_db()
    async with get_db() as conn:
        # Create a seed theme to use in tests
        await conn.execute("INSERT INTO themes (id, name) VALUES (1, 'Test Theme')")
        await conn.commit()
        yield conn


# ---------------------------------------------------------------------------
# register_line — happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_line_returns_response(db):
    body = LineCreate(moves="e4 e5", theme_id=1)
    result = await register_line(db, body)
    assert result.moves == "e4 e5"
    assert result.move_count == 2
    assert result.start_fen == STANDARD_FEN
    assert result.final_fen != STANDARD_FEN


@pytest.mark.asyncio
async def test_register_line_theme_line_id_populated(db):
    """theme_line_id must be set after registration."""
    body = LineCreate(moves="d4 d5", theme_id=1)
    result = await register_line(db, body)
    assert result.theme_line_id is not None
    assert isinstance(result.theme_line_id, int)


@pytest.mark.asyncio
async def test_register_line_empty_moves(db):
    """A line with no moves (empty string) is valid."""
    body = LineCreate(moves="", theme_id=1)
    result = await register_line(db, body)
    assert result.moves == ""
    assert result.move_count == 0
    assert result.start_fen == STANDARD_FEN


# ---------------------------------------------------------------------------
# register_line — deduplication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_line_duplicate_returns_same_id(db):
    """Registering the same (start_fen, moves) twice yields the same line id."""
    body = LineCreate(moves="e4 e5", theme_id=1)
    r1 = await register_line(db, body)
    r2 = await register_line(db, body)
    assert r1.id == r2.id


@pytest.mark.asyncio
async def test_register_duplicate_across_themes(db):
    """Same moves in two different themes share one line record."""
    async with db.execute("INSERT INTO themes (id, name) VALUES (2, 'Theme B')"):
        pass
    await db.commit()

    r1 = await register_line(db, LineCreate(moves="e4 e5", theme_id=1))
    r2 = await register_line(db, LineCreate(moves="e4 e5", theme_id=2))
    assert r1.id == r2.id
    # But theme_line_id should be different
    assert r1.theme_line_id != r2.theme_line_id


# ---------------------------------------------------------------------------
# register_line — fen_index population
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_line_populates_fen_index(db):
    """fen_index rows must be created for each ply of the new line."""
    body = LineCreate(moves="e4 e5 Nf3", theme_id=1)
    result = await register_line(db, body)

    async with db.execute(
        "SELECT COUNT(*) FROM fen_index WHERE line_id = ?", (result.id,)
    ) as cur:
        row = await cur.fetchone()
    # 3 moves → plies 0, 1, 2, 3 = 4 entries
    assert row[0] == 4


@pytest.mark.asyncio
async def test_register_line_does_not_duplicate_fen_index(db):
    """Registering the same line twice must not double the fen_index rows."""
    body = LineCreate(moves="e4 e5", theme_id=1)
    r1 = await register_line(db, body)
    await register_line(db, body)  # second registration

    async with db.execute(
        "SELECT COUNT(*) FROM fen_index WHERE line_id = ?", (r1.id,)
    ) as cur:
        row = await cur.fetchone()
    # 2 moves → 3 plies; must still be exactly 3
    assert row[0] == 3


# ---------------------------------------------------------------------------
# register_line — error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_line_unknown_theme_raises(db):
    """Registering a line against a non-existent theme must raise ValueError."""
    body = LineCreate(moves="e4 e5", theme_id=9999)
    with pytest.raises(ValueError, match="9999"):
        await register_line(db, body)


@pytest.mark.asyncio
async def test_register_line_invalid_moves_raises(db):
    """An illegal move must raise InvalidMoveError before any DB write."""
    body = LineCreate(moves="e4 Nf6 GARBAGE", theme_id=1)
    with pytest.raises(InvalidMoveError):
        await register_line(db, body)


# ---------------------------------------------------------------------------
# register_line — custom start FEN
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_register_line_custom_start_fen(db):
    """Lines starting from a non-standard position are stored correctly."""
    # King + pawn endgame, White to move
    custom_fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
    body = LineCreate(moves="e4", start_fen=custom_fen, theme_id=1)
    result = await register_line(db, body)
    assert result.start_fen == custom_fen
    assert result.move_count == 1
