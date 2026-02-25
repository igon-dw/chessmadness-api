from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import aiosqlite

from app.services.fen_normalize import normalize_fen

logger = logging.getLogger(__name__)

# Threshold above which a skill block becomes a "signature weapon"
SIGNATURE_THRESHOLD = 3.0


class DuplicateSkillBlockError(ValueError):
    """Raised when a skill block for the given line_id already exists."""


# ================================================================
# Rust-level computation (never stored, always computed on-read)
# ================================================================


def compute_rust_level(
    last_success_at: str | None,
    interval_days: int,
    last_game_miss_at: str | None,
) -> str:
    """Return the rust level for a skill block.

    Levels (in priority order):
      'critical' — real-game miss recorded after the last success
      'rusty'    — no practice ever, or last success > 3× interval ago
      'aging'    — last success > 1.5× interval ago
      'fresh'    — within interval
    """
    now = datetime.now(UTC)

    # Determine days since last success
    if last_success_at is None:
        # Never practised → immediately rusty
        return "rusty"

    try:
        success_dt = datetime.fromisoformat(last_success_at)
        if success_dt.tzinfo is None:
            success_dt = success_dt.replace(tzinfo=UTC)
        days_since = (now - success_dt).total_seconds() / 86400
    except ValueError:
        return "rusty"

    # Critical: real-game miss after last success
    if last_game_miss_at is not None:
        try:
            miss_dt = datetime.fromisoformat(last_game_miss_at)
            if miss_dt.tzinfo is None:
                miss_dt = miss_dt.replace(tzinfo=UTC)
            if miss_dt > success_dt:
                return "critical"
        except ValueError:
            pass

    effective_interval = max(interval_days, 1)
    if days_since > effective_interval * 3.0:
        return "rusty"
    if days_since > effective_interval * 1.5:
        return "aging"
    return "fresh"


# ================================================================
# CRUD helpers
# ================================================================


async def _build_mastery_dict(
    db: aiosqlite.Connection,
    skill_block_id: int,
    interval_days: int,
) -> dict[str, Any] | None:
    """Fetch skill_mastery row and enrich it with rust_level."""
    async with db.execute(
        "SELECT xp, level, streak, max_streak, perfect_runs, "
        "last_success_at, last_game_miss_at, game_matches, game_misses, "
        "weapon_score, is_signature, signature_title "
        "FROM skill_mastery WHERE skill_block_id = ?",
        (skill_block_id,),
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        return None

    return {
        "xp": row["xp"],
        "level": row["level"],
        "streak": row["streak"],
        "max_streak": row["max_streak"],
        "perfect_runs": row["perfect_runs"],
        "last_success_at": row["last_success_at"],
        "last_game_miss_at": row["last_game_miss_at"],
        "game_matches": row["game_matches"],
        "game_misses": row["game_misses"],
        "weapon_score": row["weapon_score"],
        "is_signature": bool(row["is_signature"]),
        "signature_title": row["signature_title"],
        "rust_level": compute_rust_level(
            row["last_success_at"],
            interval_days,
            row["last_game_miss_at"],
        ),
    }


def _parse_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


async def _block_row_to_dict(
    db: aiosqlite.Connection,
    row: aiosqlite.Row,
    include_mastery: bool = True,
) -> dict[str, Any]:
    """Convert a skill_blocks DB row + optional mastery into a plain dict."""
    # Fetch interval_days from the best-matching review_progress for mastery rust calc
    interval_days = 0
    if include_mastery:
        async with db.execute(
            "SELECT COALESCE(MAX(rp.interval_days), 0) "
            "FROM review_progress rp "
            "JOIN theme_lines tl ON tl.id = rp.theme_line_id "
            "WHERE tl.line_id = ?",
            (row["line_id"],),
        ) as cur:
            iv_row = await cur.fetchone()
            if iv_row:
                interval_days = iv_row[0] or 0

    mastery = None
    if include_mastery:
        mastery = await _build_mastery_dict(db, row["id"], interval_days)

    return {
        "id": row["id"],
        "line_id": row["line_id"],
        "name": row["name"],
        "description": row["description"],
        "tags": _parse_tags(row["tags"]),
        "source_type": row["source_type"],
        "share_code": row["share_code"],
        "forked_from_id": row["forked_from_id"],
        "created_at": row["created_at"],
        "mastery": mastery,
    }


# ================================================================
# Public service functions
# ================================================================


async def create_skill_block(
    db: aiosqlite.Connection,
    line_id: int,
    name: str,
    description: str | None = None,
    tags: list[str] | None = None,
    source_type: str = "original",
    forked_from_id: int | None = None,
) -> dict[str, Any]:
    """
    Insert a skill block and run the auto-link engine.

    Raises ValueError if the line does not exist or a skill block for that
    line already exists.
    """
    # Validate line exists and fetch its start/final FEN
    async with db.execute(
        "SELECT id, start_fen, final_fen FROM lines WHERE id = ?",
        (line_id,),
    ) as cur:
        line_row = await cur.fetchone()
    if line_row is None:
        raise ValueError(f"Line {line_id} not found")

    # Check for existing skill block for this line
    async with db.execute(
        "SELECT id FROM skill_blocks WHERE line_id = ?", (line_id,)
    ) as cur:
        if await cur.fetchone() is not None:
            raise DuplicateSkillBlockError(
                f"A skill block for line {line_id} already exists"
            )

    start_fen_norm = normalize_fen(line_row["start_fen"])
    final_fen_norm = normalize_fen(line_row["final_fen"])

    tags_json = json.dumps(tags or [])

    await db.execute(
        "INSERT INTO skill_blocks "
        "(line_id, name, description, tags, source_type, forked_from_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (line_id, name, description, tags_json, source_type, forked_from_id),
    )

    async with db.execute("SELECT last_insert_rowid()") as cur:
        row = await cur.fetchone()
    block_id: int = row[0]  # type: ignore[index]

    # Create the companion skill_mastery row
    await db.execute(
        "INSERT INTO skill_mastery (skill_block_id) VALUES (?)",
        (block_id,),
    )

    # ---- Auto-link engine ----
    # Parents: existing blocks whose line's final_fen matches our start_fen
    async with db.execute(
        "SELECT sb.id, normalize_fen_4(l.final_fen) AS nfinal "
        "FROM skill_blocks sb "
        "JOIN lines l ON l.id = sb.line_id "
        "WHERE normalize_fen_4(l.final_fen) = ? AND sb.id != ?",
        (start_fen_norm, block_id),
    ) as cur:
        parent_rows = await cur.fetchall()

    # Children: existing blocks whose line's start_fen matches our final_fen
    async with db.execute(
        "SELECT sb.id, normalize_fen_4(l.start_fen) AS nstart "
        "FROM skill_blocks sb "
        "JOIN lines l ON l.id = sb.line_id "
        "WHERE normalize_fen_4(l.start_fen) = ? AND sb.id != ?",
        (final_fen_norm, block_id),
    ) as cur:
        child_rows = await cur.fetchall()

    for parent_row in parent_rows:
        await db.execute(
            "INSERT OR IGNORE INTO skill_links "
            "(parent_block_id, child_block_id, link_fen, link_type) "
            "VALUES (?, ?, ?, 'auto')",
            (parent_row["id"], block_id, start_fen_norm),
        )

    for child_row in child_rows:
        await db.execute(
            "INSERT OR IGNORE INTO skill_links "
            "(parent_block_id, child_block_id, link_fen, link_type) "
            "VALUES (?, ?, ?, 'auto')",
            (block_id, child_row["id"], final_fen_norm),
        )

    await db.commit()

    # Fetch back the full row
    async with db.execute(
        "SELECT * FROM skill_blocks WHERE id = ?", (block_id,)
    ) as cur:
        block_row = await cur.fetchone()

    assert block_row is not None
    return await _block_row_to_dict(db, block_row)


async def get_skill_block(
    db: aiosqlite.Connection,
    block_id: int,
) -> dict[str, Any] | None:
    """Fetch a single skill block by ID, including mastery and rust_level."""
    async with db.execute(
        "SELECT * FROM skill_blocks WHERE id = ?", (block_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return await _block_row_to_dict(db, row)


async def update_skill_block(
    db: aiosqlite.Connection,
    block_id: int,
    name: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    signature_title: str | None = None,
) -> dict[str, Any] | None:
    """Patch a skill block's editable fields. Returns None if not found."""
    async with db.execute(
        "SELECT * FROM skill_blocks WHERE id = ?", (block_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None

    new_name = name if name is not None else row["name"]
    new_desc = description if description is not None else row["description"]
    new_tags = json.dumps(tags) if tags is not None else row["tags"]

    await db.execute(
        "UPDATE skill_blocks SET name = ?, description = ?, tags = ? WHERE id = ?",
        (new_name, new_desc, new_tags, block_id),
    )

    if signature_title is not None:
        await db.execute(
            "UPDATE skill_mastery SET signature_title = ? WHERE skill_block_id = ?",
            (signature_title, block_id),
        )

    await db.commit()

    async with db.execute(
        "SELECT * FROM skill_blocks WHERE id = ?", (block_id,)
    ) as cur:
        updated_row = await cur.fetchone()

    assert updated_row is not None
    return await _block_row_to_dict(db, updated_row)


async def delete_skill_block(
    db: aiosqlite.Connection,
    block_id: int,
) -> bool:
    """Delete a skill block. Returns True if deleted, False if not found."""
    async with db.execute(
        "SELECT id FROM skill_blocks WHERE id = ?", (block_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return False

    await db.execute("DELETE FROM skill_blocks WHERE id = ?", (block_id,))
    await db.commit()
    return True


async def get_skill_tree(
    db: aiosqlite.Connection,
) -> dict[str, Any]:
    """Return all skill blocks (nodes) and skill links (edges)."""
    async with db.execute("SELECT * FROM skill_blocks ORDER BY id") as cur:
        block_rows = await cur.fetchall()

    nodes = []
    for row in block_rows:
        nodes.append(await _block_row_to_dict(db, row, include_mastery=False))

    async with db.execute(
        "SELECT id, parent_block_id, child_block_id, link_fen, link_type "
        "FROM skill_links ORDER BY id"
    ) as cur:
        link_rows = await cur.fetchall()

    edges = [
        {
            "id": lr["id"],
            "parent_block_id": lr["parent_block_id"],
            "child_block_id": lr["child_block_id"],
            "link_fen": lr["link_fen"],
            "link_type": lr["link_type"],
        }
        for lr in link_rows
    ]

    return {"nodes": nodes, "edges": edges}


async def get_children(
    db: aiosqlite.Connection,
    block_id: int,
) -> list[dict[str, Any]]:
    """Return all direct children of a skill block."""
    async with db.execute(
        "SELECT sb.* FROM skill_blocks sb "
        "JOIN skill_links sl ON sl.child_block_id = sb.id "
        "WHERE sl.parent_block_id = ? ORDER BY sb.id",
        (block_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [await _block_row_to_dict(db, r, include_mastery=False) for r in rows]


async def get_ancestors(
    db: aiosqlite.Connection,
    block_id: int,
) -> list[dict[str, Any]]:
    """Return the path from a skill block up to the root(s), ordered root-first."""
    # Walk the graph upward with a recursive CTE via Python loop
    # (SQLite doesn't have a built-in recursive graph walk, but we can simulate)
    visited: set[int] = set()
    path: list[dict[str, Any]] = []
    current_id = block_id

    while True:
        async with db.execute(
            "SELECT parent_block_id FROM skill_links WHERE child_block_id = ? LIMIT 1",
            (current_id,),
        ) as cur:
            link_row = await cur.fetchone()
        if link_row is None:
            break
        parent_id: int = link_row["parent_block_id"]
        if parent_id in visited:
            break  # cycle guard
        visited.add(parent_id)

        async with db.execute(
            "SELECT * FROM skill_blocks WHERE id = ?", (parent_id,)
        ) as cur:
            parent_row = await cur.fetchone()
        if parent_row is None:
            break

        path.append(await _block_row_to_dict(db, parent_row, include_mastery=False))
        current_id = parent_id

    path.reverse()  # root-first
    return path


async def list_rusty_blocks(
    db: aiosqlite.Connection,
) -> list[dict[str, Any]]:
    """Return all skill blocks whose computed rust_level is aging/rusty/critical."""
    async with db.execute("SELECT * FROM skill_blocks ORDER BY id") as cur:
        rows = await cur.fetchall()

    result = []
    for row in rows:
        block_dict = await _block_row_to_dict(db, row, include_mastery=True)
        if block_dict.get("mastery") and block_dict["mastery"]["rust_level"] != "fresh":
            result.append(block_dict)
    return result


async def list_critical_blocks(
    db: aiosqlite.Connection,
) -> list[dict[str, Any]]:
    """Return skill blocks with real-game misses after last success."""
    async with db.execute("SELECT * FROM skill_blocks ORDER BY id") as cur:
        rows = await cur.fetchall()

    result = []
    for row in rows:
        block_dict = await _block_row_to_dict(db, row, include_mastery=True)
        if (
            block_dict.get("mastery")
            and block_dict["mastery"]["rust_level"] == "critical"
        ):
            result.append(block_dict)
    return result


async def list_signature_blocks(
    db: aiosqlite.Connection,
) -> list[dict[str, Any]]:
    """Return skill blocks marked as signature weapons, ordered by weapon_score desc."""
    async with db.execute(
        "SELECT sb.* FROM skill_blocks sb "
        "JOIN skill_mastery sm ON sm.skill_block_id = sb.id "
        "WHERE sm.is_signature = 1 "
        "ORDER BY sm.weapon_score DESC"
    ) as cur:
        rows = await cur.fetchall()
    return [await _block_row_to_dict(db, r) for r in rows]


async def search_blocks(
    db: aiosqlite.Connection,
    fen: str | None = None,
    name: str | None = None,
    tag: str | None = None,
) -> list[dict[str, Any]]:
    """Search skill blocks by FEN, name substring, or tag."""
    clauses: list[str] = []
    params: list[object] = []

    if fen:
        norm = normalize_fen(fen)
        clauses.append(
            "EXISTS ("
            "SELECT 1 FROM lines l "
            "WHERE l.id = sb.line_id "
            "AND (normalize_fen_4(l.start_fen) = ? OR normalize_fen_4(l.final_fen) = ?)"
            ")"
        )
        params.extend([norm, norm])

    if name:
        clauses.append("sb.name LIKE ?")
        params.append(f"%{name}%")

    if tag:
        # tags is a JSON array; use LIKE as a simple substring check
        clauses.append("sb.tags LIKE ?")
        params.append(f'%"{tag}"%')

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT sb.* FROM skill_blocks sb {where} ORDER BY sb.id"

    async with db.execute(sql, params) as cur:
        rows = await cur.fetchall()

    return [await _block_row_to_dict(db, r, include_mastery=False) for r in rows]


async def get_mastery_dashboard(db: aiosqlite.Connection) -> dict[str, Any]:
    """
    Aggregate skill mastery data into an overall dashboard summary.

    Returns:
      total_blocks        — number of skill blocks
      total_xp            — sum of all XP across all blocks
      average_level       — mean level (0.0 if no blocks)
      level_distribution  — {level: count} mapping
      rust_distribution   — counts per rust level (fresh/aging/rusty/critical)
      signature_count     — number of signature weapon blocks
      top_signatures      — top 5 signature blocks (highest weapon_score first)
    """
    # Fetch all mastery rows
    async with db.execute(
        """
        SELECT sm.skill_block_id, sm.xp, sm.level,
               sm.last_success_at, sm.last_game_miss_at, sm.is_signature
        FROM skill_mastery sm
        """
    ) as cur:
        mastery_rows = list(await cur.fetchall())

    # Fetch maximum interval_days per skill block (via theme_lines → review_progress)
    async with db.execute(
        """
        SELECT sb.id AS block_id, COALESCE(MAX(rp.interval_days), 0) AS interval_days
        FROM skill_blocks sb
        LEFT JOIN theme_lines tl ON tl.line_id = sb.line_id
        LEFT JOIN review_progress rp ON rp.theme_line_id = tl.id
        GROUP BY sb.id
        """
    ) as cur:
        interval_rows = await cur.fetchall()

    interval_map: dict[int, int] = {
        r["block_id"]: r["interval_days"] for r in interval_rows
    }

    total_blocks = len(mastery_rows)
    total_xp = 0
    level_distribution: dict[int, int] = {}
    rust_counts: dict[str, int] = {"fresh": 0, "aging": 0, "rusty": 0, "critical": 0}
    signature_count = 0

    for row in mastery_rows:
        total_xp += row["xp"]
        level = row["level"]
        level_distribution[level] = level_distribution.get(level, 0) + 1

        if row["is_signature"]:
            signature_count += 1

        interval_days = interval_map.get(row["skill_block_id"], 0)
        rust = compute_rust_level(
            row["last_success_at"], interval_days, row["last_game_miss_at"]
        )
        rust_counts[rust] = rust_counts.get(rust, 0) + 1

    average_level = (
        sum(lvl * cnt for lvl, cnt in level_distribution.items()) / total_blocks
        if total_blocks > 0
        else 0.0
    )

    # Top 5 signature blocks
    top_sigs = await list_signature_blocks(db)
    top_5 = top_sigs[:5]

    return {
        "total_blocks": total_blocks,
        "total_xp": total_xp,
        "average_level": average_level,
        "level_distribution": level_distribution,
        "rust_distribution": rust_counts,
        "signature_count": signature_count,
        "top_signatures": top_5,
    }
