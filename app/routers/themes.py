from __future__ import annotations

import logging

import aiosqlite
from fastapi import APIRouter, HTTPException

from app.database import get_db
from app.schemas.themes import ThemeCreate, ThemeNode, ThemeResponse, ThemeUpdate

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/themes", tags=["themes"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_to_response(row: aiosqlite.Row) -> ThemeResponse:
    return ThemeResponse(
        id=row["id"],
        parent_id=row["parent_id"],
        name=row["name"],
        description=row["description"],
        sort_order=row["sort_order"],
        created_at=row["created_at"],
    )


def _build_tree(
    nodes: list[ThemeResponse], parent_id: int | None = None
) -> list[ThemeNode]:
    result: list[ThemeNode] = []
    for node in nodes:
        if node.parent_id == parent_id:
            tree_node = ThemeNode(**node.model_dump())
            tree_node.children = _build_tree(nodes, parent_id=node.id)
            result.append(tree_node)
    result.sort(key=lambda n: n.sort_order)
    return result


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=list[ThemeNode])
async def list_themes() -> list[ThemeNode]:
    """Return all themes as a nested tree (roots first)."""
    async with (
        get_db() as db,
        db.execute(
            "SELECT id, parent_id, name, description, sort_order, created_at "
            "FROM themes ORDER BY sort_order, name"
        ) as cur,
    ):
        rows = await cur.fetchall()
    flat = [_row_to_response(r) for r in rows]
    return _build_tree(flat)


@router.post("", response_model=ThemeResponse, status_code=201)
async def create_theme(body: ThemeCreate) -> ThemeResponse:
    """Create a new theme."""
    async with get_db() as db:
        # Validate parent exists
        if body.parent_id is not None:
            async with db.execute(
                "SELECT id FROM themes WHERE id = ?", (body.parent_id,)
            ) as cur:
                if await cur.fetchone() is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Parent theme {body.parent_id} not found",
                    )

        async with db.execute(
            "INSERT INTO themes (name, parent_id, description, sort_order) "
            "VALUES (?, ?, ?, ?) RETURNING id, parent_id, name, description, sort_order, created_at",  # noqa: E501
            (body.name, body.parent_id, body.description, body.sort_order),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()

    assert row is not None
    return _row_to_response(row)


@router.get("/{theme_id}", response_model=ThemeResponse)
async def get_theme(theme_id: int) -> ThemeResponse:
    """Return a single theme by ID."""
    async with (
        get_db() as db,
        db.execute(
            "SELECT id, parent_id, name, description, sort_order, created_at "
            "FROM themes WHERE id = ?",
            (theme_id,),
        ) as cur,
    ):
        row = await cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail=f"Theme {theme_id} not found")
    return _row_to_response(row)


@router.patch("/{theme_id}", response_model=ThemeResponse)
async def update_theme(theme_id: int, body: ThemeUpdate) -> ThemeResponse:
    """Partially update a theme."""
    async with get_db() as db:
        # Fetch existing
        async with db.execute(
            "SELECT id, parent_id, name, description, sort_order, created_at "
            "FROM themes WHERE id = ?",
            (theme_id,),
        ) as cur:
            existing = await cur.fetchone()

        if existing is None:
            raise HTTPException(status_code=404, detail=f"Theme {theme_id} not found")

        # Validate new parent if provided
        if body.parent_id is not None and body.parent_id != existing["parent_id"]:
            async with db.execute(
                "SELECT id FROM themes WHERE id = ?", (body.parent_id,)
            ) as cur:
                if await cur.fetchone() is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Parent theme {body.parent_id} not found",
                    )

        new_name = body.name if body.name is not None else existing["name"]
        new_parent = (
            body.parent_id if body.parent_id is not None else existing["parent_id"]
        )
        new_desc = (
            body.description
            if body.description is not None
            else existing["description"]
        )
        new_sort = (
            body.sort_order if body.sort_order is not None else existing["sort_order"]
        )

        async with db.execute(
            "UPDATE themes SET name=?, parent_id=?, description=?, sort_order=? "
            "WHERE id=? RETURNING id, parent_id, name, description, sort_order, created_at",  # noqa: E501
            (new_name, new_parent, new_desc, new_sort, theme_id),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()

    assert row is not None
    return _row_to_response(row)


@router.delete("/{theme_id}", status_code=204)
async def delete_theme(theme_id: int) -> None:
    """Delete a theme and all its descendants (cascade)."""
    async with get_db() as db:
        async with db.execute("SELECT id FROM themes WHERE id = ?", (theme_id,)) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(
                    status_code=404, detail=f"Theme {theme_id} not found"
                )
        await db.execute("DELETE FROM themes WHERE id = ?", (theme_id,))
        await db.commit()


@router.get("/{theme_id}/subtree", response_model=list[ThemeNode])
async def get_subtree(theme_id: int) -> list[ThemeNode]:
    """Return the theme and all its descendants as a nested tree."""
    async with get_db() as db:
        async with db.execute("SELECT id FROM themes WHERE id = ?", (theme_id,)) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(
                    status_code=404, detail=f"Theme {theme_id} not found"
                )

        async with db.execute(
            """
            WITH RECURSIVE subtree AS (
                SELECT id, parent_id, name, description, sort_order, created_at, 0 AS depth
                FROM themes WHERE id = ?
                UNION ALL
                SELECT t.id, t.parent_id, t.name, t.description, t.sort_order, t.created_at,
                       s.depth + 1
                FROM themes t
                JOIN subtree s ON t.parent_id = s.id
            )
            SELECT id, parent_id, name, description, sort_order, created_at
            FROM subtree
            ORDER BY depth, sort_order
            """,
            (theme_id,),
        ) as cur:
            rows = await cur.fetchall()

    flat = [_row_to_response(r) for r in rows]
    return _build_tree(flat, parent_id=None)
