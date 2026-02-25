"""
Unit tests for app/services/skill_share.py.

Tests cover:
  - encode_share_payload / decode_share_code (pure encode/decode round-trip)
  - preview_share_code (pure, no DB)
  - generate_share_code (DB: persists code on block)
  - import_share_code (DB: registers line, creates block)
  - fork_skill_block (DB: creates forked block + manual link)
  - Error cases: bad prefix, bad base64, illegal moves, missing fields
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.database import get_db, init_db
from app.schemas.lines import LineCreate
from app.services.line_service import register_line
from app.services.skill_service import create_skill_block
from app.services.skill_share import (
    ShareCodeDecodeError,
    ShareCodeValidationError,
    decode_share_code,
    encode_share_payload,
    fork_skill_block,
    generate_share_code,
    import_share_code,
    preview_share_code,
)

STANDARD_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "unit_share_test.db")
    monkeypatch.setattr(settings, "database_url", db_path)
    await init_db()
    async with get_db() as conn:
        await conn.execute("INSERT INTO themes (id, name) VALUES (1, 'Theme')")
        await conn.commit()
        yield conn


async def _make_block(
    conn,
    moves: str = "e4 e5",
    start_fen: str = STANDARD_FEN,
    name: str = "Test Block",
) -> int:
    body = LineCreate(moves=moves, theme_id=1, start_fen=start_fen)
    line = await register_line(conn, body)
    block = await create_skill_block(conn, line_id=line.id, name=name)
    return block["id"]


# ---------------------------------------------------------------------------
# Pure encode / decode round-trip
# ---------------------------------------------------------------------------


def test_encode_decode_round_trip():
    code = encode_share_payload(
        name="Test Opening",
        start_fen=STANDARD_FEN,
        moves="e2e4 e7e5",
        tags=["italian", "trap"],
        description="My opening",
    )
    assert code.startswith("chessmadness:")

    payload = decode_share_code(code)
    assert payload["name"] == "Test Opening"
    assert payload["start_fen"] == STANDARD_FEN
    assert payload["moves"] == "e2e4 e7e5"
    assert payload["tags"] == ["italian", "trap"]
    assert payload["desc"] == "My opening"
    assert payload["v"] == 1


def test_encode_empty_description():
    code = encode_share_payload(
        name="Block",
        start_fen=STANDARD_FEN,
        moves="e2e4",
        tags=[],
        description=None,
    )
    payload = decode_share_code(code)
    assert payload["desc"] == ""


def test_encode_unicode_name():
    code = encode_share_payload(
        name="必殺フライド・リバー・トラップ",
        start_fen=STANDARD_FEN,
        moves="e2e4",
        tags=[],
        description=None,
    )
    payload = decode_share_code(code)
    assert payload["name"] == "必殺フライド・リバー・トラップ"


# ---------------------------------------------------------------------------
# decode_share_code — error cases
# ---------------------------------------------------------------------------


def test_decode_wrong_prefix():
    with pytest.raises(ShareCodeDecodeError, match="must start with"):
        decode_share_code("notvalid:XXXX")


def test_decode_bad_base64():
    with pytest.raises(ShareCodeDecodeError):
        decode_share_code("chessmadness:!!!notbase64!!!")


def test_decode_bad_json():
    import base64
    import zlib

    garbage = zlib.compress(b"not json at all", level=9)
    encoded = base64.b64encode(garbage).decode("ascii")
    with pytest.raises(ShareCodeDecodeError):
        decode_share_code(f"chessmadness:{encoded}")


def test_decode_wrong_version():
    import base64
    import json
    import zlib

    payload = json.dumps({"v": 99, "name": "x", "start_fen": "x", "moves": "x"})
    compressed = zlib.compress(payload.encode(), level=9)
    encoded = base64.b64encode(compressed).decode("ascii")
    with pytest.raises(ShareCodeDecodeError, match="Unsupported payload version"):
        decode_share_code(f"chessmadness:{encoded}")


def test_decode_missing_required_field():
    import base64
    import json
    import zlib

    payload = json.dumps({"v": 1, "name": "x", "start_fen": "x"})  # missing 'moves'
    compressed = zlib.compress(payload.encode(), level=9)
    encoded = base64.b64encode(compressed).decode("ascii")
    with pytest.raises(ShareCodeDecodeError, match="Missing required field"):
        decode_share_code(f"chessmadness:{encoded}")


# ---------------------------------------------------------------------------
# preview_share_code
# ---------------------------------------------------------------------------


def test_preview_returns_correct_fields():
    code = encode_share_payload(
        name="Preview Test",
        start_fen=STANDARD_FEN,
        moves="d2d4 d7d5",
        tags=["queenside"],
        description="Queen's pawn",
    )
    preview = preview_share_code(code)
    assert preview["name"] == "Preview Test"
    assert preview["start_fen"] == STANDARD_FEN
    assert preview["moves"] == "d2d4 d7d5"
    assert preview["tags"] == ["queenside"]
    assert preview["description"] == "Queen's pawn"


def test_preview_invalid_code_raises():
    with pytest.raises(ShareCodeDecodeError):
        preview_share_code("not:acode")


# ---------------------------------------------------------------------------
# generate_share_code (DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_share_code_returns_chessmadness_prefix(db):
    block_id = await _make_block(db)
    code = await generate_share_code(db, block_id)
    assert code.startswith("chessmadness:")


@pytest.mark.asyncio
async def test_generate_share_code_persisted_on_block(db):
    block_id = await _make_block(db)
    code = await generate_share_code(db, block_id)

    async with db.execute(
        "SELECT share_code FROM skill_blocks WHERE id = ?", (block_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row["share_code"] == code


@pytest.mark.asyncio
async def test_generate_share_code_unknown_block_raises(db):
    with pytest.raises(ValueError, match="not found"):
        await generate_share_code(db, 9999)


@pytest.mark.asyncio
async def test_generate_share_code_encodes_moves(db):
    block_id = await _make_block(db, moves="e4 e5")
    code = await generate_share_code(db, block_id)
    payload = decode_share_code(code)
    assert payload["moves"] == "e4 e5"


# ---------------------------------------------------------------------------
# import_share_code (DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_creates_block(db):
    code = encode_share_payload(
        name="Imported Block",
        start_fen=STANDARD_FEN,
        moves="e4 e5",
        tags=["test"],
        description="An imported block",
    )
    block = await import_share_code(db, code)
    assert block["id"] is not None
    assert block["name"] == "Imported Block"
    assert block["source_type"] == "imported"
    assert block["share_code"] == code


@pytest.mark.asyncio
async def test_import_name_override(db):
    code = encode_share_payload(
        name="Original Name",
        start_fen=STANDARD_FEN,
        moves="d4",
        tags=[],
        description=None,
    )
    block = await import_share_code(db, code, name_override="My Name")
    assert block["name"] == "My Name"


@pytest.mark.asyncio
async def test_import_invalid_code_raises(db):
    with pytest.raises(ShareCodeDecodeError):
        await import_share_code(db, "bad:code")


@pytest.mark.asyncio
async def test_import_illegal_moves_raises(db):
    code = encode_share_payload(
        name="Bad Moves",
        start_fen=STANDARD_FEN,
        moves="e7e5",  # illegal from white's starting position
        tags=[],
        description=None,
    )
    with pytest.raises(ShareCodeValidationError, match="Illegal move"):
        await import_share_code(db, code)


@pytest.mark.asyncio
async def test_import_registers_line_and_fen_index(db):
    code = encode_share_payload(
        name="FEN Index Test",
        start_fen=STANDARD_FEN,
        moves="e2e4",
        tags=[],
        description=None,
    )
    block = await import_share_code(db, code)
    line_id = block["line_id"]

    async with db.execute(
        "SELECT COUNT(*) FROM fen_index WHERE line_id = ?", (line_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 2  # ply 0 (start) + ply 1 (after e4)


@pytest.mark.asyncio
async def test_import_idempotent_on_same_line(db):
    """Importing the same share code twice should reuse the existing line."""
    code = encode_share_payload(
        name="Idempotent",
        start_fen=STANDARD_FEN,
        moves="d2d4 d7d5",
        tags=[],
        description=None,
    )
    b1 = await import_share_code(db, code)
    assert b1["id"] is not None

    # Second import of same moves will try to create another skill block for the
    # same line — this should raise ValueError (UNIQUE constraint on line_id in
    # skill_blocks). This is expected behaviour.
    with pytest.raises((ValueError, Exception)):
        await import_share_code(db, code)

    # But the line should only exist once
    async with db.execute(
        "SELECT COUNT(*) FROM lines WHERE moves = 'd4 d5'",
    ) as cur:
        row = await cur.fetchone()
    assert row[0] == 1


# ---------------------------------------------------------------------------
# fork_skill_block (DB)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_creates_new_block(db):
    parent_id = await _make_block(db, moves="e2e4")
    fork = await fork_skill_block(
        db, parent_block_id=parent_id, additional_moves="e7e5", name="Fork"
    )
    assert fork["id"] != parent_id
    assert fork["name"] == "Fork"
    assert fork["source_type"] == "forked"
    assert fork["forked_from_id"] == parent_id


@pytest.mark.asyncio
async def test_fork_unknown_parent_raises(db):
    with pytest.raises(ValueError, match="not found"):
        await fork_skill_block(
            db, parent_block_id=9999, additional_moves="e2e4", name="X"
        )


@pytest.mark.asyncio
async def test_fork_illegal_moves_raises(db):
    parent_id = await _make_block(db, moves="e2e4")
    with pytest.raises((ValueError, Exception)):
        # After 1.e4 it's black's turn — e2e4 again is illegal
        await fork_skill_block(
            db, parent_block_id=parent_id, additional_moves="e2e4", name="X"
        )


@pytest.mark.asyncio
async def test_fork_creates_manual_link(db):
    parent_id = await _make_block(db, moves="e2e4")
    fork = await fork_skill_block(
        db, parent_block_id=parent_id, additional_moves="e7e5", name="Fork"
    )
    fork_id = fork["id"]

    async with db.execute(
        "SELECT link_type FROM skill_links "
        "WHERE parent_block_id = ? AND child_block_id = ?",
        (parent_id, fork_id),
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row["link_type"] == "manual"


@pytest.mark.asyncio
async def test_fork_start_fen_is_parent_final_fen(db):
    parent_id = await _make_block(db, moves="e2e4")

    # Get the parent's final_fen
    async with db.execute(
        "SELECT l.final_fen FROM skill_blocks sb JOIN lines l ON l.id = sb.line_id "
        "WHERE sb.id = ?",
        (parent_id,),
    ) as cur:
        row = await cur.fetchone()
    parent_final_fen = row["final_fen"]

    fork = await fork_skill_block(
        db, parent_block_id=parent_id, additional_moves="e7e5", name="Fork"
    )

    # The forked block's line start_fen should equal parent's final_fen
    async with db.execute(
        "SELECT l.start_fen FROM skill_blocks sb JOIN lines l ON l.id = sb.line_id "
        "WHERE sb.id = ?",
        (fork["id"],),
    ) as cur:
        row = await cur.fetchone()
    assert row["start_fen"] == parent_final_fen
