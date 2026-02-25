from __future__ import annotations

import logging

import aiosqlite
from fastapi import APIRouter, HTTPException

from app.database import get_db
from app.schemas.lines import (
    FenMoveCount,
    LineCreate,
    LineResponse,
    LineThemeUpdate,
    LineWithThemeResponse,
)
from app.services.fen_index import InvalidMoveError
from app.services.line_service import register_line

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/lines", tags=["lines"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_response(row: aiosqlite.Row) -> LineResponse:
    return LineResponse(
        id=row["id"],
        moves=row["moves"],
        move_count=row["move_count"],
        start_fen=row["start_fen"],
        final_fen=row["final_fen"],
        created_at=row["created_at"],
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("", response_model=LineResponse, status_code=201)
async def create_line(body: LineCreate) -> LineResponse:
    """
    Register a new line.

    - Validates all moves with python-chess.
    - Computes final_fen and populates fen_index.
    - If an identical (start_fen, moves) already exists the existing line is
      returned and only the theme association is added (idempotent).
    """
    try:
        async with get_db() as db:
            return await register_line(db, body)
    except InvalidMoveError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{line_id}", response_model=LineResponse)
async def get_line(line_id: int) -> LineResponse:
    """Return a single line by ID."""
    async with (
        get_db() as db,
        db.execute(
            "SELECT id, moves, move_count, start_fen, final_fen, created_at "
            "FROM lines WHERE id = ?",
            (line_id,),
        ) as cur,
    ):
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Line {line_id} not found")
    return _row_to_response(row)


@router.patch("/{line_id}", response_model=LineWithThemeResponse)
async def update_line_theme_metadata(
    line_id: int, body: LineThemeUpdate
) -> LineWithThemeResponse:
    """
    Update per-theme metadata (note and/or sort_order) for a line.

    The request body must include the theme_id to identify which
    theme_lines record to update. At least one of note or sort_order
    must be provided.
    """
    async with get_db() as db:
        # Verify line exists
        async with db.execute("SELECT id FROM lines WHERE id = ?", (line_id,)) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(status_code=404, detail=f"Line {line_id} not found")

        # Verify theme_lines record exists
        async with db.execute(
            "SELECT id FROM theme_lines WHERE line_id = ? AND theme_id = ?",
            (line_id, body.theme_id),
        ) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Line {line_id} not found in theme {body.theme_id}",
                )

        # Build UPDATE dynamically — only fields provided
        updates: list[str] = []
        params: list[object] = []
        if body.note is not None:
            updates.append("note = ?")
            params.append(body.note)
        if body.sort_order is not None:
            updates.append("sort_order = ?")
            params.append(body.sort_order)

        if not updates:
            raise HTTPException(
                status_code=422,
                detail="At least one of note or sort_order must be provided",
            )

        params.extend([line_id, body.theme_id])
        await db.execute(
            f"UPDATE theme_lines SET {', '.join(updates)} "
            "WHERE line_id = ? AND theme_id = ?",
            params,
        )
        await db.commit()

        async with db.execute(
            "SELECT l.id, l.moves, l.move_count, l.start_fen, l.final_fen, l.created_at, "
            "tl.theme_id, tl.sort_order, tl.note "
            "FROM lines l "
            "JOIN theme_lines tl ON tl.line_id = l.id "
            "WHERE l.id = ? AND tl.theme_id = ?",
            (line_id, body.theme_id),
        ) as cur:
            updated_row = await cur.fetchone()

    assert updated_row is not None
    return LineWithThemeResponse(
        id=updated_row["id"],
        moves=updated_row["moves"],
        move_count=updated_row["move_count"],
        start_fen=updated_row["start_fen"],
        final_fen=updated_row["final_fen"],
        created_at=updated_row["created_at"],
        theme_id=updated_row["theme_id"],
        sort_order=updated_row["sort_order"],
        note=updated_row["note"],
    )


@router.delete("/{line_id}", status_code=204)
async def delete_line(line_id: int) -> None:
    """
    Delete a line and all associated data (fen_index, theme_lines, etc.)
    via ON DELETE CASCADE.
    """
    async with get_db() as db:
        async with db.execute("SELECT id FROM lines WHERE id = ?", (line_id,)) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(status_code=404, detail=f"Line {line_id} not found")
        await db.execute("DELETE FROM lines WHERE id = ?", (line_id,))
        await db.commit()


@router.get("/by-theme/{theme_id}", response_model=list[LineWithThemeResponse])
async def list_lines_by_theme(
    theme_id: int, include_descendants: bool = False
) -> list[LineWithThemeResponse]:
    """
    Return all lines belonging to a theme.

    Set *include_descendants=true* to also include lines from child themes
    (uses WITH RECURSIVE).
    """
    async with get_db() as db:
        async with db.execute("SELECT id FROM themes WHERE id = ?", (theme_id,)) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(
                    status_code=404, detail=f"Theme {theme_id} not found"
                )

        if include_descendants:
            query = """
            WITH RECURSIVE subtree AS (
                SELECT id FROM themes WHERE id = ?
                UNION ALL
                SELECT t.id FROM themes t
                JOIN subtree s ON t.parent_id = s.id
            )
            SELECT l.id, l.moves, l.move_count, l.start_fen, l.final_fen, l.created_at,
                   tl.theme_id, tl.sort_order, tl.note
            FROM lines l
            JOIN theme_lines tl ON tl.line_id = l.id
            WHERE tl.theme_id IN (SELECT id FROM subtree)
            ORDER BY tl.sort_order
            """
        else:
            query = """
            SELECT l.id, l.moves, l.move_count, l.start_fen, l.final_fen, l.created_at,
                   tl.theme_id, tl.sort_order, tl.note
            FROM lines l
            JOIN theme_lines tl ON tl.line_id = l.id
            WHERE tl.theme_id = ?
            ORDER BY tl.sort_order
            """

        async with db.execute(query, (theme_id,)) as cur:
            rows = await cur.fetchall()

    return [
        LineWithThemeResponse(
            id=r["id"],
            moves=r["moves"],
            move_count=r["move_count"],
            start_fen=r["start_fen"],
            final_fen=r["final_fen"],
            created_at=r["created_at"],
            theme_id=r["theme_id"],
            sort_order=r["sort_order"],
            note=r["note"],
        )
        for r in rows
    ]


@router.get("/by-fen/{fen:path}", response_model=list[FenMoveCount])
async def moves_from_fen(fen: str) -> list[FenMoveCount]:
    """
    Return all possible next moves from the given FEN position,
    aggregated across all stored lines.
    """
    async with (
        get_db() as db,
        db.execute(
            """
            SELECT next_move, COUNT(DISTINCT line_id) AS line_count
            FROM fen_index
            WHERE fen = ? AND next_move IS NOT NULL
            GROUP BY next_move
            ORDER BY line_count DESC
            """,
            (fen,),
        ) as cur,
    ):
        rows = await cur.fetchall()

    return [
        FenMoveCount(next_move=r["next_move"], line_count=r["line_count"]) for r in rows
    ]
