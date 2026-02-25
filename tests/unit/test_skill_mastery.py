"""
Unit tests for app/services/skill_mastery.py.

Tests cover:
  - compute_weapon_score (pure function)
  - record_review_success
  - record_review_fail
  - record_game_match
  - record_game_miss (including SM-2 partial decay)
  - apply_game_miss_decay (from sm2.py, tested here for integration)
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.database import get_db, init_db
from app.schemas.lines import LineCreate
from app.services.line_service import register_line
from app.services.skill_mastery import (
    SIGNATURE_THRESHOLD,
    compute_weapon_score,
    record_game_match,
    record_game_miss,
    record_review_fail,
    record_review_success,
)
from app.services.skill_service import create_skill_block
from app.services.sm2 import EASE_FACTOR_MIN, SM2State, apply_game_miss_decay

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db(tmp_path, monkeypatch):
    db_path = str(tmp_path / "unit_mastery_test.db")
    monkeypatch.setattr(settings, "database_url", db_path)
    await init_db()
    async with get_db() as conn:
        await conn.execute("INSERT INTO themes (id, name) VALUES (1, 'Theme')")
        await conn.commit()
        yield conn


async def _make_block(conn, moves: str = "e2e4 e7e5") -> int:
    body = LineCreate(moves=moves, theme_id=1)
    result = await register_line(conn, body)
    block = await create_skill_block(conn, line_id=result.id, name="Test Block")
    return block["id"]


async def _get_mastery(conn, block_id: int) -> dict:
    async with conn.execute(
        "SELECT xp, level, streak, max_streak, perfect_runs, "
        "game_matches, game_misses, weapon_score, is_signature, "
        "last_success_at, last_game_miss_at "
        "FROM skill_mastery WHERE skill_block_id = ?",
        (block_id,),
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    return dict(row)


# ---------------------------------------------------------------------------
# compute_weapon_score — pure function
# ---------------------------------------------------------------------------


def test_weapon_score_no_data():
    """With no data, game_rate defaults to 0.5, depth=0 → score=0."""
    score = compute_weapon_score(0, 0, 0, 0)
    assert score == 0.0


def test_weapon_score_increases_with_perfect_runs():
    s1 = compute_weapon_score(1, 0, 0, 0)
    s2 = compute_weapon_score(5, 0, 0, 0)
    assert s2 > s1


def test_weapon_score_increases_with_game_matches():
    s1 = compute_weapon_score(0, 1, 0, 0)
    s2 = compute_weapon_score(0, 5, 0, 0)
    assert s2 > s1


def test_weapon_score_game_misses_reduce_score():
    s_perfect = compute_weapon_score(5, 5, 0, 0)
    s_missed = compute_weapon_score(5, 5, 10, 0)
    assert s_missed < s_perfect


def test_weapon_score_decays_over_time():
    s_recent = compute_weapon_score(5, 5, 0, 0)
    s_old = compute_weapon_score(5, 5, 0, 60)
    assert s_old < s_recent


def test_weapon_score_above_threshold():
    """Enough activity should push score above SIGNATURE_THRESHOLD."""
    score = compute_weapon_score(20, 30, 2, 0)
    assert score >= SIGNATURE_THRESHOLD


# ---------------------------------------------------------------------------
# apply_game_miss_decay — from sm2.py
# ---------------------------------------------------------------------------


def test_apply_game_miss_decay_halves_interval():
    state = SM2State(interval_days=10, repetitions=3, ease_factor=2.5)
    decayed = apply_game_miss_decay(state)
    assert decayed.interval_days == 5


def test_apply_game_miss_decay_interval_floor_1():
    state = SM2State(interval_days=1, repetitions=1, ease_factor=2.5)
    decayed = apply_game_miss_decay(state)
    assert decayed.interval_days == 1


def test_apply_game_miss_decay_repetitions_decremented():
    state = SM2State(interval_days=6, repetitions=3, ease_factor=2.5)
    decayed = apply_game_miss_decay(state)
    assert decayed.repetitions == 2


def test_apply_game_miss_decay_repetitions_floor_0():
    state = SM2State(interval_days=6, repetitions=0, ease_factor=2.5)
    decayed = apply_game_miss_decay(state)
    assert decayed.repetitions == 0


def test_apply_game_miss_decay_ease_reduced():
    state = SM2State(interval_days=6, repetitions=2, ease_factor=2.5)
    decayed = apply_game_miss_decay(state)
    assert decayed.ease_factor == pytest.approx(2.4, abs=1e-3)


def test_apply_game_miss_decay_ease_floor():
    state = SM2State(interval_days=6, repetitions=2, ease_factor=EASE_FACTOR_MIN)
    decayed = apply_game_miss_decay(state)
    assert decayed.ease_factor == EASE_FACTOR_MIN


# ---------------------------------------------------------------------------
# record_review_success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_success_grants_xp(db):
    block_id = await _make_block(db)
    await record_review_success(db, block_id, grade=5)
    mastery = await _get_mastery(db, block_id)
    assert mastery["xp"] == 5


@pytest.mark.asyncio
async def test_review_success_increments_streak(db):
    block_id = await _make_block(db)
    await record_review_success(db, block_id, grade=4)
    await record_review_success(db, block_id, grade=4)
    mastery = await _get_mastery(db, block_id)
    assert mastery["streak"] == 2


@pytest.mark.asyncio
async def test_review_success_updates_max_streak(db):
    block_id = await _make_block(db)
    await record_review_success(db, block_id, grade=5)
    await record_review_success(db, block_id, grade=5)
    await record_review_success(db, block_id, grade=5)
    mastery = await _get_mastery(db, block_id)
    assert mastery["max_streak"] == 3


@pytest.mark.asyncio
async def test_review_perfect_increments_perfect_runs(db):
    block_id = await _make_block(db)
    await record_review_success(db, block_id, grade=5)
    mastery = await _get_mastery(db, block_id)
    assert mastery["perfect_runs"] == 1


@pytest.mark.asyncio
async def test_review_non_perfect_no_perfect_runs(db):
    block_id = await _make_block(db)
    await record_review_success(db, block_id, grade=4)
    mastery = await _get_mastery(db, block_id)
    assert mastery["perfect_runs"] == 0


@pytest.mark.asyncio
async def test_review_success_updates_last_success_at(db):
    block_id = await _make_block(db)
    await record_review_success(db, block_id, grade=5)
    mastery = await _get_mastery(db, block_id)
    assert mastery["last_success_at"] is not None


@pytest.mark.asyncio
async def test_review_success_updates_level(db):
    block_id = await _make_block(db)
    # Get to level 2 (needs 200 XP)
    for _ in range(40):
        await record_review_success(db, block_id, grade=5)
    mastery = await _get_mastery(db, block_id)
    assert mastery["level"] >= 2


# ---------------------------------------------------------------------------
# record_review_fail
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_fail_resets_streak(db):
    block_id = await _make_block(db)
    await record_review_success(db, block_id, grade=5)
    await record_review_success(db, block_id, grade=5)
    await record_review_fail(db, block_id)
    mastery = await _get_mastery(db, block_id)
    assert mastery["streak"] == 0


@pytest.mark.asyncio
async def test_review_fail_preserves_max_streak(db):
    block_id = await _make_block(db)
    await record_review_success(db, block_id, grade=5)
    await record_review_success(db, block_id, grade=5)
    await record_review_fail(db, block_id)
    mastery = await _get_mastery(db, block_id)
    assert mastery["max_streak"] == 2


@pytest.mark.asyncio
async def test_review_fail_no_xp_change(db):
    block_id = await _make_block(db)
    await record_review_success(db, block_id, grade=5)
    xp_before = (await _get_mastery(db, block_id))["xp"]
    await record_review_fail(db, block_id)
    mastery = await _get_mastery(db, block_id)
    assert mastery["xp"] == xp_before


# ---------------------------------------------------------------------------
# record_game_match
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_game_match_grants_xp(db):
    from app.services.skill_mastery import XP_GAME_MATCH

    block_id = await _make_block(db)
    await record_game_match(db, block_id)
    mastery = await _get_mastery(db, block_id)
    assert mastery["xp"] == XP_GAME_MATCH


@pytest.mark.asyncio
async def test_game_match_increments_game_matches(db):
    block_id = await _make_block(db)
    await record_game_match(db, block_id)
    mastery = await _get_mastery(db, block_id)
    assert mastery["game_matches"] == 1


@pytest.mark.asyncio
async def test_game_match_increments_perfect_runs(db):
    block_id = await _make_block(db)
    await record_game_match(db, block_id)
    mastery = await _get_mastery(db, block_id)
    assert mastery["perfect_runs"] == 1


@pytest.mark.asyncio
async def test_game_match_updates_streak(db):
    block_id = await _make_block(db)
    await record_game_match(db, block_id)
    await record_game_match(db, block_id)
    mastery = await _get_mastery(db, block_id)
    assert mastery["streak"] == 2


# ---------------------------------------------------------------------------
# record_game_miss
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_game_miss_increments_game_misses(db):
    block_id = await _make_block(db)
    await record_game_miss(db, block_id)
    mastery = await _get_mastery(db, block_id)
    assert mastery["game_misses"] == 1


@pytest.mark.asyncio
async def test_game_miss_resets_streak(db):
    block_id = await _make_block(db)
    await record_game_match(db, block_id)
    await record_game_miss(db, block_id)
    mastery = await _get_mastery(db, block_id)
    assert mastery["streak"] == 0


@pytest.mark.asyncio
async def test_game_miss_sets_last_game_miss_at(db):
    block_id = await _make_block(db)
    await record_game_miss(db, block_id)
    mastery = await _get_mastery(db, block_id)
    assert mastery["last_game_miss_at"] is not None


@pytest.mark.asyncio
async def test_game_miss_applies_sm2_partial_decay(db):
    """A game miss should reduce the review_progress interval for the linked line."""
    block_id = await _make_block(db)

    # Get the line_id from the block
    async with db.execute(
        "SELECT line_id FROM skill_blocks WHERE id = ?", (block_id,)
    ) as cur:
        row = await cur.fetchone()
    line_id = row["line_id"]

    # Fetch the existing theme_line_id (created by register_line above)
    async with db.execute(
        "SELECT id FROM theme_lines WHERE line_id = ? AND theme_id = 1",
        (line_id,),
    ) as cur:
        tl_row = await cur.fetchone()
    tl_id = tl_row["id"]

    # Insert a review_progress with a non-trivial interval
    await db.execute(
        "INSERT INTO review_progress "
        "(theme_line_id, interval_days, repetitions, ease_factor) "
        "VALUES (?, 10, 3, 2.5)",
        (tl_id,),
    )
    await db.commit()

    # Apply the game miss
    await record_game_miss(db, block_id)

    # Check that interval was halved
    async with db.execute(
        "SELECT interval_days, repetitions, ease_factor "
        "FROM review_progress WHERE theme_line_id = ?",
        (tl_id,),
    ) as cur:
        rp = await cur.fetchone()

    assert rp["interval_days"] == 5  # 10 // 2
    assert rp["repetitions"] == 2  # 3 - 1
    assert rp["ease_factor"] == pytest.approx(2.4, abs=1e-3)  # 2.5 - 0.1


# ---------------------------------------------------------------------------
# is_signature promotion
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_signature_promoted_after_enough_activity(db):
    """Many game matches should eventually push weapon_score above threshold."""
    block_id = await _make_block(db)
    for _ in range(30):
        await record_game_match(db, block_id)
    mastery = await _get_mastery(db, block_id)
    assert mastery["weapon_score"] >= SIGNATURE_THRESHOLD
    assert mastery["is_signature"] == 1
