from __future__ import annotations

import logging

import aiosqlite

from app.schemas.lines import LineCreate, LineResponse
from app.services.fen_index import build_fen_index

logger = logging.getLogger(__name__)


async def register_line(db: aiosqlite.Connection, body: LineCreate) -> LineResponse:
    """
    Insert a line into the database and associate it with a theme.

    - Validates all moves with python-chess.
    - Computes final_fen and populates fen_index.
    - If an identical (start_fen, moves) already exists the existing line is
      returned and only the theme association is added (idempotent).

    Raises InvalidMoveError if any move fails chess validation.
    Raises ValueError if the theme does not exist.
    """
    fen_entries = build_fen_index(body.start_fen, body.moves)
    final_fen = str(fen_entries[-1]["fen"])
    move_count = len(body.moves.split()) if body.moves.strip() else 0

    # Validate theme
    async with db.execute(
        "SELECT id FROM themes WHERE id = ?", (body.theme_id,)
    ) as cur:
        if await cur.fetchone() is None:
            raise ValueError(f"Theme {body.theme_id} not found")

    # Upsert line (INSERT OR IGNORE keeps existing on duplicate)
    await db.execute(
        "INSERT OR IGNORE INTO lines (moves, move_count, start_fen, final_fen) "
        "VALUES (?, ?, ?, ?)",
        (body.moves, move_count, body.start_fen, final_fen),
    )

    # Fetch the line id (whether just inserted or pre-existing)
    async with db.execute(
        "SELECT id, moves, move_count, start_fen, final_fen, created_at "
        "FROM lines WHERE start_fen = ? AND moves = ?",
        (body.start_fen, body.moves),
    ) as cur:
        line_row = await cur.fetchone()

    assert line_row is not None
    line_id: int = line_row["id"]

    # Populate fen_index only if this is a genuinely new line
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

    # Associate with theme (ignore if already linked)
    await db.execute(
        "INSERT OR IGNORE INTO theme_lines (theme_id, line_id, sort_order, note) "
        "VALUES (?, ?, ?, ?)",
        (body.theme_id, line_id, body.sort_order, body.note),
    )

    await db.commit()

    # Fetch the theme_line id
    async with db.execute(
        "SELECT id FROM theme_lines WHERE theme_id = ? AND line_id = ?",
        (body.theme_id, line_id),
    ) as cur:
        tl_row = await cur.fetchone()
    theme_line_id: int | None = tl_row["id"] if tl_row is not None else None

    return LineResponse(
        id=line_row["id"],
        moves=line_row["moves"],
        move_count=line_row["move_count"],
        start_fen=line_row["start_fen"],
        final_fen=line_row["final_fen"],
        created_at=line_row["created_at"],
        theme_line_id=theme_line_id,
    )
