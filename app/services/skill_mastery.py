"""
Skill mastery service — XP, level, streak, weapon_score, and is_signature.

This module is responsible for updating skill_mastery rows after review events
and real-game analysis events. It also exposes the pure compute_weapon_score
function used for testing and re-computation.

XP / Level design:
  - Each successful review of a skill block grants XP equal to the SM-2 grade
    (3–5). A perfect review (grade 5) gives 5 XP.
  - A real-game match grants 10 XP (higher reward for practical performance).
  - Levels follow a geometric threshold: level N requires N * 100 cumulative XP.
    e.g. level 2 at 200 XP, level 3 at 300 XP, level 10 at 1000 XP.
  - Level is the largest integer N such that xp >= N * 100 (floor-divide by 100,
    minimum 1).

Streak:
  - Incremented by 1 on every successful review (grade >= 3) or game match.
  - Reset to 0 on a failed review (grade < 3) or game miss.
  - max_streak is the high-water mark, never decremented.

perfect_runs:
  - Incremented by 1 on a perfect review (grade == 5) or a game match.

weapon_score:
  - Computed and stored on every update (event-driven, not on-read).
  - Formula from spec §13.6.

is_signature:
  - Set to 1 when weapon_score >= SIGNATURE_THRESHOLD (3.0).
  - Never automatically reverted to 0 once set (the user owns the badge).
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import aiosqlite

from app.services.sm2 import SM2State, apply_game_miss_decay

# Threshold above which a skill block becomes a signature weapon
SIGNATURE_THRESHOLD = 3.0

# XP granted for real-game events
XP_GAME_MATCH = 10
XP_GAME_MISS = 0

# XP granted for review events (equal to the SM-2 grade for grade >= 3)
XP_REVIEW_SUCCESS_BASE = 3  # fallback if grade not passed in


def compute_weapon_score(
    perfect_runs: int,
    game_matches: int,
    game_misses: int,
    days_since_success: float,
) -> float:
    """
    Compute the weapon_score for a skill block.

    Formula (from spec §13.6):
      depth = log(1 + perfect_runs + game_matches * 2)
      game_rate = game_matches / (game_matches + game_misses)  # 0.5 if no data
      decay = exp(-0.023 * days_since_success)
      score = depth * (0.4 + 0.6 * game_rate) * decay
    """
    depth = math.log(1 + perfect_runs + game_matches * 2)
    total = game_matches + game_misses
    game_rate = game_matches / total if total > 0 else 0.5
    decay = math.exp(-0.023 * days_since_success)
    return depth * (0.4 + 0.6 * game_rate) * decay


def _compute_level(xp: int) -> int:
    """Return the level for a given cumulative XP total."""
    return max(1, xp // 100)


def _days_since(iso_str: str | None) -> float:
    """Return fractional days since the given ISO timestamp, or 0.0 if None."""
    if iso_str is None:
        return 0.0
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        delta = datetime.now(UTC) - dt
        return max(0.0, delta.total_seconds() / 86400)
    except ValueError:
        return 0.0


async def record_review_success(
    db: aiosqlite.Connection,
    skill_block_id: int,
    grade: int,
) -> None:
    """
    Update skill_mastery after a successful SRS review (grade 3–5).

    - Grants XP equal to the grade value.
    - Increments streak; updates max_streak.
    - If grade == 5, increments perfect_runs.
    - Updates last_success_at.
    - Recomputes weapon_score and is_signature.
    """
    now_iso = datetime.now(UTC).isoformat()

    async with db.execute(
        "SELECT xp, streak, max_streak, perfect_runs, "
        "game_matches, game_misses, last_success_at, is_signature "
        "FROM skill_mastery WHERE skill_block_id = ?",
        (skill_block_id,),
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        return  # block not found — nothing to update

    xp = row["xp"] + grade
    streak = row["streak"] + 1
    max_streak = max(row["max_streak"], streak)
    perfect_runs = row["perfect_runs"] + (1 if grade == 5 else 0)
    level = _compute_level(xp)

    days = 0.0  # last_success_at is being set to now
    score = compute_weapon_score(
        perfect_runs,
        row["game_matches"],
        row["game_misses"],
        days,
    )
    is_sig = 1 if (score >= SIGNATURE_THRESHOLD or row["is_signature"]) else 0

    await db.execute(
        "UPDATE skill_mastery SET "
        "xp = ?, level = ?, streak = ?, max_streak = ?, perfect_runs = ?, "
        "last_success_at = ?, weapon_score = ?, is_signature = ? "
        "WHERE skill_block_id = ?",
        (
            xp,
            level,
            streak,
            max_streak,
            perfect_runs,
            now_iso,
            score,
            is_sig,
            skill_block_id,
        ),
    )
    await db.commit()


async def record_review_fail(
    db: aiosqlite.Connection,
    skill_block_id: int,
) -> None:
    """
    Update skill_mastery after a failed SRS review (grade 0–2).

    - No XP granted.
    - Resets streak to 0.
    - Recomputes weapon_score.
    """
    async with db.execute(
        "SELECT xp, max_streak, perfect_runs, game_matches, game_misses, "
        "last_success_at, is_signature "
        "FROM skill_mastery WHERE skill_block_id = ?",
        (skill_block_id,),
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        return

    days = _days_since(row["last_success_at"])
    score = compute_weapon_score(
        row["perfect_runs"],
        row["game_matches"],
        row["game_misses"],
        days,
    )
    is_sig = 1 if (score >= SIGNATURE_THRESHOLD or row["is_signature"]) else 0

    await db.execute(
        "UPDATE skill_mastery SET streak = 0, weapon_score = ?, is_signature = ? "
        "WHERE skill_block_id = ?",
        (score, is_sig, skill_block_id),
    )
    await db.commit()


async def record_game_match(
    db: aiosqlite.Connection,
    skill_block_id: int,
) -> None:
    """
    Update skill_mastery after a real-game match event.

    - Grants XP_GAME_MATCH XP.
    - Increments game_matches and perfect_runs.
    - Increments streak; updates max_streak.
    - Updates last_success_at.
    - Recomputes weapon_score and is_signature.
    """
    now_iso = datetime.now(UTC).isoformat()

    async with db.execute(
        "SELECT xp, streak, max_streak, perfect_runs, game_matches, game_misses, "
        "is_signature "
        "FROM skill_mastery WHERE skill_block_id = ?",
        (skill_block_id,),
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        return

    xp = row["xp"] + XP_GAME_MATCH
    game_matches = row["game_matches"] + 1
    perfect_runs = row["perfect_runs"] + 1
    streak = row["streak"] + 1
    max_streak = max(row["max_streak"], streak)
    level = _compute_level(xp)

    days = 0.0  # last_success_at is being updated to now
    score = compute_weapon_score(perfect_runs, game_matches, row["game_misses"], days)
    is_sig = 1 if (score >= SIGNATURE_THRESHOLD or row["is_signature"]) else 0

    await db.execute(
        "UPDATE skill_mastery SET "
        "xp = ?, level = ?, streak = ?, max_streak = ?, perfect_runs = ?, "
        "game_matches = ?, last_success_at = ?, weapon_score = ?, is_signature = ? "
        "WHERE skill_block_id = ?",
        (
            xp,
            level,
            streak,
            max_streak,
            perfect_runs,
            game_matches,
            now_iso,
            score,
            is_sig,
            skill_block_id,
        ),
    )
    await db.commit()


async def record_game_miss(
    db: aiosqlite.Connection,
    skill_block_id: int,
) -> None:
    """
    Update skill_mastery and review_progress after a real-game miss event.

    - Increments game_misses.
    - Updates last_game_miss_at.
    - Resets streak to 0.
    - Recomputes weapon_score (will go down due to higher game_misses).
    - Applies SM-2 partial decay (apply_game_miss_decay) to all review_progress
      rows linked to this skill block's line.
    """
    now_iso = datetime.now(UTC).isoformat()

    async with db.execute(
        "SELECT xp, perfect_runs, game_matches, game_misses, "
        "last_success_at, is_signature, "
        "(SELECT line_id FROM skill_blocks WHERE id = ?) AS line_id "
        "FROM skill_mastery WHERE skill_block_id = ?",
        (skill_block_id, skill_block_id),
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        return

    game_misses = row["game_misses"] + 1
    days = _days_since(row["last_success_at"])
    score = compute_weapon_score(
        row["perfect_runs"],
        row["game_matches"],
        game_misses,
        days,
    )
    is_sig = 1 if (score >= SIGNATURE_THRESHOLD or row["is_signature"]) else 0

    await db.execute(
        "UPDATE skill_mastery SET "
        "streak = 0, game_misses = ?, last_game_miss_at = ?, "
        "weapon_score = ?, is_signature = ? "
        "WHERE skill_block_id = ?",
        (game_misses, now_iso, score, is_sig, skill_block_id),
    )

    # Apply partial SM-2 decay to all review_progress rows for this line
    line_id: int | None = row["line_id"]
    if line_id is not None:
        async with db.execute(
            "SELECT rp.id, rp.interval_days, rp.repetitions, rp.ease_factor "
            "FROM review_progress rp "
            "JOIN theme_lines tl ON tl.id = rp.theme_line_id "
            "WHERE tl.line_id = ?",
            (line_id,),
        ) as cur:
            rp_rows = await cur.fetchall()

        for rp in rp_rows:
            state = SM2State(
                interval_days=rp["interval_days"],
                repetitions=rp["repetitions"],
                ease_factor=rp["ease_factor"],
            )
            decayed = apply_game_miss_decay(state)
            await db.execute(
                "UPDATE review_progress SET "
                "interval_days = ?, repetitions = ?, ease_factor = ? "
                "WHERE id = ?",
                (
                    decayed.interval_days,
                    decayed.repetitions,
                    decayed.ease_factor,
                    rp["id"],
                ),
            )

    await db.commit()
