"""
Unit tests for app/services/skill_service.py.

Uses a real in-memory SQLite database (tmp_path + monkeypatch) to keep tests
realistic without the overhead of a full HTTP client.
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.database import get_db, init_db
from app.schemas.lines import LineCreate
from app.services.line_service import register_line
from app.services.skill_service import (
    compute_rust_level,
    create_skill_block,
    delete_skill_block,
    get_ancestors,
    get_children,
    get_skill_block,
    get_skill_tree,
    list_rusty_blocks,
    list_signature_blocks,
    search_blocks,
    update_skill_block,
)

STANDARD_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db(tmp_path, monkeypatch):
    """Fresh in-memory SQLite DB for each test."""
    db_path = str(tmp_path / "unit_skill_test.db")
    monkeypatch.setattr(settings, "database_url", db_path)
    await init_db()
    async with get_db() as conn:
        await conn.execute("INSERT INTO themes (id, name) VALUES (1, 'Test Theme')")
        await conn.commit()
        yield conn


async def _make_line(conn, moves: str = "e2e4 e7e5", theme_id: int = 1) -> int:
    """Helper: register a line and return its line_id."""
    body = LineCreate(moves=moves, theme_id=theme_id)
    result = await register_line(conn, body)
    return result.id


# ---------------------------------------------------------------------------
# compute_rust_level — pure function, no DB needed
# ---------------------------------------------------------------------------


def test_rust_level_never_practiced():
    assert compute_rust_level(None, 7, None) == "rusty"


def test_rust_level_fresh():
    from datetime import UTC, datetime, timedelta

    recent = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert compute_rust_level(recent, 7, None) == "fresh"


def test_rust_level_aging():
    from datetime import UTC, datetime, timedelta

    old = (datetime.now(UTC) - timedelta(days=12)).isoformat()
    # interval=7, 12 > 7*1.5=10.5 but < 7*3=21
    assert compute_rust_level(old, 7, None) == "aging"


def test_rust_level_rusty():
    from datetime import UTC, datetime, timedelta

    very_old = (datetime.now(UTC) - timedelta(days=25)).isoformat()
    # 25 > 7*3=21
    assert compute_rust_level(very_old, 7, None) == "rusty"


def test_rust_level_critical_game_miss_after_success():
    from datetime import UTC, datetime, timedelta

    success = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    miss = datetime.now(UTC).isoformat()  # miss is after success
    assert compute_rust_level(success, 7, miss) == "critical"


def test_rust_level_game_miss_before_success_not_critical():
    from datetime import UTC, datetime, timedelta

    miss = (datetime.now(UTC) - timedelta(days=5)).isoformat()
    success = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    # miss occurred before success → not critical
    result = compute_rust_level(success, 7, miss)
    assert result != "critical"


# ---------------------------------------------------------------------------
# create_skill_block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_skill_block_basic(db):
    line_id = await _make_line(db)
    block = await create_skill_block(db, line_id=line_id, name="e4 opening")

    assert block["id"] is not None
    assert block["name"] == "e4 opening"
    assert block["line_id"] == line_id
    assert block["source_type"] == "original"
    assert block["mastery"] is not None
    assert block["mastery"]["xp"] == 0
    assert block["mastery"]["level"] == 1


@pytest.mark.asyncio
async def test_create_skill_block_unknown_line_raises(db):
    with pytest.raises(ValueError, match="9999"):
        await create_skill_block(db, line_id=9999, name="ghost block")


@pytest.mark.asyncio
async def test_create_skill_block_duplicate_line_raises(db):
    line_id = await _make_line(db)
    await create_skill_block(db, line_id=line_id, name="First")
    with pytest.raises((ValueError, Exception)):
        # UNIQUE(line_id) should raise on second insert
        await create_skill_block(db, line_id=line_id, name="Second")


@pytest.mark.asyncio
async def test_create_skill_block_with_tags(db):
    line_id = await _make_line(db)
    block = await create_skill_block(
        db, line_id=line_id, name="Tagged", tags=["open", "e4"]
    )
    assert "open" in block["tags"]
    assert "e4" in block["tags"]


@pytest.mark.asyncio
async def test_create_skill_block_mastery_row_created(db):
    line_id = await _make_line(db)
    block = await create_skill_block(db, line_id=line_id, name="Check mastery")

    async with db.execute(
        "SELECT COUNT(*) FROM skill_mastery WHERE skill_block_id = ?",
        (block["id"],),
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 1


# ---------------------------------------------------------------------------
# Auto-link engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_link_child_connects_to_parent(db):
    """A block whose start_fen matches another block's final_fen is auto-linked."""
    # Parent line: e2e4 (standard start → after e4)
    parent_line_id = await _make_line(db, moves="e2e4")
    parent_block = await create_skill_block(db, line_id=parent_line_id, name="Parent")

    # Child line: e2e4 e7e5 — starts from standard position, but its start_fen
    # matches parent's start_fen, not parent's final_fen.
    # For a true auto-link, the child must start where the parent ends.
    # Use a custom start_fen equal to parent's final_fen.
    from app.schemas.lines import LineCreate
    from app.services.line_service import register_line

    parent_final_fen = parent_block["mastery"]  # noqa: F841 — unused, fetch from DB below
    # fetch from DB
    async with db.execute(
        "SELECT final_fen FROM lines WHERE id = ?", (parent_line_id,)
    ) as cur:
        prow = await cur.fetchone()
    parent_final = prow["final_fen"]

    # Register a child line starting from parent's final_fen
    child_body = LineCreate(moves="e7e5", start_fen=parent_final, theme_id=1)
    child_result = await register_line(db, child_body)
    child_block = await create_skill_block(db, line_id=child_result.id, name="Child")

    # Verify skill_links table has the edge
    async with db.execute(
        "SELECT COUNT(*) FROM skill_links "
        "WHERE parent_block_id = ? AND child_block_id = ?",
        (parent_block["id"], child_block["id"]),
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 1


# ---------------------------------------------------------------------------
# get_skill_block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_skill_block_returns_block(db):
    line_id = await _make_line(db)
    created = await create_skill_block(db, line_id=line_id, name="Fetch me")
    fetched = await get_skill_block(db, created["id"])

    assert fetched is not None
    assert fetched["id"] == created["id"]
    assert fetched["name"] == "Fetch me"


@pytest.mark.asyncio
async def test_get_skill_block_missing_returns_none(db):
    result = await get_skill_block(db, 99999)
    assert result is None


# ---------------------------------------------------------------------------
# update_skill_block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_skill_block_name(db):
    line_id = await _make_line(db)
    block = await create_skill_block(db, line_id=line_id, name="Old Name")
    updated = await update_skill_block(db, block["id"], name="New Name")

    assert updated is not None
    assert updated["name"] == "New Name"


@pytest.mark.asyncio
async def test_update_skill_block_tags(db):
    line_id = await _make_line(db)
    block = await create_skill_block(db, line_id=line_id, name="Taggable")
    updated = await update_skill_block(db, block["id"], tags=["sicilian", "sharp"])

    assert updated is not None
    assert "sicilian" in updated["tags"]


@pytest.mark.asyncio
async def test_update_skill_block_signature_title(db):
    line_id = await _make_line(db)
    block = await create_skill_block(db, line_id=line_id, name="Weapon")
    updated = await update_skill_block(
        db, block["id"], signature_title="The Dragon Slayer"
    )

    assert updated is not None
    assert updated["mastery"] is not None
    assert updated["mastery"]["signature_title"] == "The Dragon Slayer"


@pytest.mark.asyncio
async def test_update_skill_block_missing_returns_none(db):
    result = await update_skill_block(db, 99999, name="Ghost")
    assert result is None


# ---------------------------------------------------------------------------
# delete_skill_block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_skill_block_returns_true(db):
    line_id = await _make_line(db)
    block = await create_skill_block(db, line_id=line_id, name="To Delete")
    deleted = await delete_skill_block(db, block["id"])

    assert deleted is True
    assert await get_skill_block(db, block["id"]) is None


@pytest.mark.asyncio
async def test_delete_skill_block_missing_returns_false(db):
    result = await delete_skill_block(db, 99999)
    assert result is False


@pytest.mark.asyncio
async def test_delete_skill_block_cascades_mastery(db):
    line_id = await _make_line(db)
    block = await create_skill_block(db, line_id=line_id, name="Cascade")
    block_id = block["id"]
    await delete_skill_block(db, block_id)

    async with db.execute(
        "SELECT COUNT(*) FROM skill_mastery WHERE skill_block_id = ?", (block_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 0


# ---------------------------------------------------------------------------
# get_skill_tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_skill_tree_empty(db):
    tree = await get_skill_tree(db)
    assert tree["nodes"] == []
    assert tree["edges"] == []


@pytest.mark.asyncio
async def test_get_skill_tree_nodes(db):
    line_id = await _make_line(db)
    await create_skill_block(db, line_id=line_id, name="Node A")

    tree = await get_skill_tree(db)
    assert len(tree["nodes"]) == 1
    assert tree["nodes"][0]["name"] == "Node A"


# ---------------------------------------------------------------------------
# get_children / get_ancestors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_children_empty(db):
    line_id = await _make_line(db)
    block = await create_skill_block(db, line_id=line_id, name="Lone")
    children = await get_children(db, block["id"])
    assert children == []


@pytest.mark.asyncio
async def test_get_ancestors_empty(db):
    line_id = await _make_line(db)
    block = await create_skill_block(db, line_id=line_id, name="Root")
    ancestors = await get_ancestors(db, block["id"])
    assert ancestors == []


# ---------------------------------------------------------------------------
# search_blocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_by_name(db):
    line_id = await _make_line(db)
    await create_skill_block(db, line_id=line_id, name="Sicilian Dragon")

    results = await search_blocks(db, name="Dragon")
    assert len(results) == 1
    assert results[0]["name"] == "Sicilian Dragon"


@pytest.mark.asyncio
async def test_search_by_tag(db):
    line_id = await _make_line(db)
    await create_skill_block(
        db, line_id=line_id, name="Tagged Block", tags=["dragon", "sicilian"]
    )

    results = await search_blocks(db, tag="dragon")
    assert len(results) == 1


@pytest.mark.asyncio
async def test_search_no_filters_returns_all(db):
    line_id_a = await _make_line(db, moves="e2e4")
    line_id_b = await _make_line(db, moves="d2d4")
    await create_skill_block(db, line_id=line_id_a, name="Alpha")
    await create_skill_block(db, line_id=line_id_b, name="Beta")

    results = await search_blocks(db)
    assert len(results) == 2


# ---------------------------------------------------------------------------
# list_rusty_blocks / list_signature_blocks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_rusty_blocks_empty_initially(db):
    line_id = await _make_line(db)
    await create_skill_block(db, line_id=line_id, name="Fresh Block")
    # A brand-new block has last_success_at=NULL → rust_level='rusty'
    rusty = await list_rusty_blocks(db)
    assert len(rusty) == 1


@pytest.mark.asyncio
async def test_list_signature_blocks_empty_initially(db):
    line_id = await _make_line(db)
    await create_skill_block(db, line_id=line_id, name="Not a signature yet")

    sigs = await list_signature_blocks(db)
    assert sigs == []


@pytest.mark.asyncio
async def test_list_signature_blocks_returns_when_set(db):
    line_id = await _make_line(db)
    block = await create_skill_block(db, line_id=line_id, name="Weapon")
    # Manually set is_signature in the mastery row
    await db.execute(
        "UPDATE skill_mastery SET is_signature = 1, weapon_score = 4.5 "
        "WHERE skill_block_id = ?",
        (block["id"],),
    )
    await db.commit()

    sigs = await list_signature_blocks(db)
    assert len(sigs) == 1
    assert sigs[0]["id"] == block["id"]
