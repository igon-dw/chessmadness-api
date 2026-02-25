"""
Skill share service — encode/decode skill blocks as portable share codes.

Share code format (spec §13.7):
  1. Build a JSON payload (v=1):
       {"v": 1, "name": ..., "start_fen": ..., "moves": ...,
        "tags": [...], "desc": ...}
  2. Serialise to UTF-8 JSON bytes.
  3. Compress with zlib (level 9).
  4. Base64-encode (URL-safe alphabet, no padding stripped — standard base64).
  5. Prepend the prefix "chessmadness:".

Security:
  - import_skill_block validates all moves via build_fen_index (raises
    InvalidMoveError on any illegal move) before touching the DB.
"""

from __future__ import annotations

import base64
import json
import zlib
from typing import Any

import aiosqlite

from app.services.fen_index import InvalidMoveError, build_fen_index, normalize_moves
from app.services.skill_service import create_skill_block

PREFIX = "chessmadness:"
PAYLOAD_VERSION = 1


class ShareCodeDecodeError(Exception):
    """Raised when a share code cannot be decoded."""


class ShareCodeValidationError(Exception):
    """Raised when the decoded payload contains invalid or illegal data."""


# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------


def encode_share_payload(
    name: str,
    start_fen: str,
    moves: str,
    tags: list[str],
    description: str | None,
) -> str:
    """
    Build a share code string from skill block data.

    Returns a string like "chessmadness:H4sI...".
    """
    payload: dict[str, Any] = {
        "v": PAYLOAD_VERSION,
        "name": name,
        "start_fen": start_fen,
        "moves": moves,
        "tags": tags,
        "desc": description or "",
    }
    raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    compressed = zlib.compress(raw, level=9)
    encoded = base64.b64encode(compressed).decode("ascii")
    return f"{PREFIX}{encoded}"


async def generate_share_code(
    db: aiosqlite.Connection,
    block_id: int,
) -> str:
    """
    Generate a share code for an existing skill block and persist it.

    Returns the share code string.
    Raises ValueError if the block is not found.
    """
    async with db.execute(
        "SELECT sb.name, sb.description, sb.tags, "
        "l.start_fen, l.moves "
        "FROM skill_blocks sb "
        "JOIN lines l ON l.id = sb.line_id "
        "WHERE sb.id = ?",
        (block_id,),
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        raise ValueError(f"Skill block {block_id} not found")

    tags: list[str] = json.loads(row["tags"]) if row["tags"] else []
    code = encode_share_payload(
        name=row["name"],
        start_fen=row["start_fen"],
        moves=row["moves"],
        tags=tags,
        description=row["description"],
    )

    await db.execute(
        "UPDATE skill_blocks SET share_code = ? WHERE id = ?",
        (code, block_id),
    )
    await db.commit()
    return code


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------


def decode_share_code(code: str) -> dict[str, Any]:
    """
    Decode a share code string into its payload dict.

    Raises ShareCodeDecodeError on any decoding failure.
    """
    if not code.startswith(PREFIX):
        raise ShareCodeDecodeError(
            f"Share code must start with '{PREFIX}'; got {code[:20]!r}"
        )

    b64_part = code[len(PREFIX) :]
    try:
        compressed = base64.b64decode(b64_part)
        raw = zlib.decompress(compressed)
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise ShareCodeDecodeError(f"Failed to decode share code: {exc}") from exc

    if not isinstance(payload, dict) or payload.get("v") != PAYLOAD_VERSION:
        raise ShareCodeDecodeError(f"Unsupported payload version: {payload.get('v')!r}")

    for field in ("name", "start_fen", "moves"):
        if field not in payload:
            raise ShareCodeDecodeError(f"Missing required field '{field}' in payload")

    return payload


def preview_share_code(code: str) -> dict[str, Any]:
    """
    Decode a share code and return preview data without touching the DB.

    Returns a dict with: name, start_fen, moves, tags, description.
    Raises ShareCodeDecodeError on decode failure.
    """
    payload = decode_share_code(code)
    return {
        "name": payload["name"],
        "start_fen": payload["start_fen"],
        "moves": payload["moves"],
        "tags": payload.get("tags") or [],
        "description": payload.get("desc") or None,
    }


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


async def import_share_code(
    db: aiosqlite.Connection,
    code: str,
    name_override: str | None = None,
) -> dict[str, Any]:
    """
    Import a skill block from a share code.

    Steps:
      1. Decode the share code.
      2. Validate all moves via build_fen_index (raises ShareCodeValidationError
         if any move is illegal).
      3. Register the line (deduplicated by UNIQUE(start_fen, moves)).
      4. Create the skill block with source_type='imported', share_code set.
      5. Return the created block dict.

    Raises:
      ShareCodeDecodeError  — bad encoding
      ShareCodeValidationError — illegal moves
    """
    payload = decode_share_code(code)

    name = name_override or payload["name"]
    start_fen: str = payload["start_fen"]
    moves: str = payload["moves"]
    tags: list[str] = payload.get("tags") or []
    description: str | None = payload.get("desc") or None

    # Validate all moves before touching the DB, and reuse the result
    try:
        canonical_moves = normalize_moves(start_fen, moves)
        fen_entries = build_fen_index(start_fen, canonical_moves)
    except InvalidMoveError as exc:
        raise ShareCodeValidationError(f"Illegal move in share code: {exc}") from exc

    final_fen = str(fen_entries[-1]["fen"])
    move_count = len(canonical_moves.split()) if canonical_moves.strip() else 0

    await db.execute(
        "INSERT OR IGNORE INTO lines (moves, move_count, start_fen, final_fen) "
        "VALUES (?, ?, ?, ?)",
        (canonical_moves, move_count, start_fen, final_fen),
    )
    async with db.execute(
        "SELECT id FROM lines WHERE start_fen = ? AND moves = ?",
        (start_fen, canonical_moves),
    ) as cur:
        line_row = await cur.fetchone()

    assert line_row is not None
    line_id: int = line_row["id"]

    # Populate fen_index only if this is a new line
    async with db.execute(
        "SELECT COUNT(*) FROM fen_index WHERE line_id = ?", (line_id,)
    ) as cur:
        count_row = await cur.fetchone()
    if count_row is not None and count_row[0] == 0:
        await db.executemany(
            "INSERT OR IGNORE INTO fen_index (line_id, ply, fen, next_move) "
            "VALUES (?, ?, ?, ?)",
            [(line_id, e["ply"], e["fen"], e["next_move"]) for e in fen_entries],
        )

    # Record import provenance
    await db.execute(
        "INSERT INTO import_history"
        " (line_id, origin_type, origin_ref) VALUES (?, ?, ?)",
        (line_id, "manual", code),
    )

    await db.commit()

    block = await create_skill_block(
        db,
        line_id=line_id,
        name=name,
        description=description,
        tags=tags,
        source_type="imported",
    )

    # Set the share code on the newly created block
    await db.execute(
        "UPDATE skill_blocks SET share_code = ? WHERE id = ?",
        (code, block["id"]),
    )
    await db.commit()

    block["share_code"] = code
    return block


# ---------------------------------------------------------------------------
# Fork
# ---------------------------------------------------------------------------


async def fork_skill_block(
    db: aiosqlite.Connection,
    parent_block_id: int,
    additional_moves: str,
    name: str,
) -> dict[str, Any]:
    """
    Fork a skill block by extending it with additional moves (spec §13.8).

    Steps:
      1. Fetch the parent block's final_fen.
      2. Validate additional_moves via build_fen_index.
      3. Register a new line (start_fen = parent final_fen, moves = additional_moves).
      4. Create a new skill block (source_type='forked', forked_from_id=parent).
      5. Add a manual skill link: parent → fork.
      6. Return the new block dict.

    Raises ValueError if the parent block is not found.
    Raises InvalidMoveError (from fen_index) if additional_moves are illegal.
    """
    # Fetch parent block and its line's final_fen
    async with db.execute(
        "SELECT sb.id, l.final_fen "
        "FROM skill_blocks sb "
        "JOIN lines l ON l.id = sb.line_id "
        "WHERE sb.id = ?",
        (parent_block_id,),
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        raise ValueError(f"Skill block {parent_block_id} not found")

    parent_final_fen: str = row["final_fen"]

    # Validate the additional moves and normalize to SAN
    canonical_additional = normalize_moves(parent_final_fen, additional_moves)
    fen_entries = build_fen_index(parent_final_fen, canonical_additional)
    fork_final_fen = str(fen_entries[-1]["fen"])
    move_count = (
        len(canonical_additional.split()) if canonical_additional.strip() else 0
    )

    # Insert the new line (idempotent)
    await db.execute(
        "INSERT OR IGNORE INTO lines (moves, move_count, start_fen, final_fen) "
        "VALUES (?, ?, ?, ?)",
        (canonical_additional, move_count, parent_final_fen, fork_final_fen),
    )
    async with db.execute(
        "SELECT id FROM lines WHERE start_fen = ? AND moves = ?",
        (parent_final_fen, canonical_additional),
    ) as cur:
        line_row = await cur.fetchone()

    assert line_row is not None
    new_line_id: int = line_row["id"]

    # Populate fen_index only if new
    async with db.execute(
        "SELECT COUNT(*) FROM fen_index WHERE line_id = ?", (new_line_id,)
    ) as cur:
        count_row = await cur.fetchone()
    if count_row is not None and count_row[0] == 0:
        await db.executemany(
            "INSERT OR IGNORE INTO fen_index (line_id, ply, fen, next_move) "
            "VALUES (?, ?, ?, ?)",
            [(new_line_id, e["ply"], e["fen"], e["next_move"]) for e in fen_entries],
        )

    # Record import provenance
    await db.execute(
        "INSERT INTO import_history"
        " (line_id, origin_type, origin_ref) VALUES (?, ?, ?)",
        (new_line_id, "manual", f"fork_from:{parent_block_id}"),
    )

    await db.commit()

    # Create the forked skill block
    fork_block = await create_skill_block(
        db,
        line_id=new_line_id,
        name=name,
        source_type="forked",
        forked_from_id=parent_block_id,
    )

    # Ensure a manual skill link exists: parent → fork
    # Use INSERT OR REPLACE (via DELETE + INSERT) so that if an auto link
    # already exists (created by the auto-link engine) it is upgraded to manual.
    from app.services.fen_normalize import normalize_fen

    link_fen = normalize_fen(parent_final_fen)
    await db.execute(
        "DELETE FROM skill_links WHERE parent_block_id = ? AND child_block_id = ?",
        (parent_block_id, fork_block["id"]),
    )
    await db.execute(
        "INSERT INTO skill_links "
        "(parent_block_id, child_block_id, link_fen, link_type) "
        "VALUES (?, ?, ?, 'manual')",
        (parent_block_id, fork_block["id"], link_fen),
    )
    await db.commit()

    return fork_block
