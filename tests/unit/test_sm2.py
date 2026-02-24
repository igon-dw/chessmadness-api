"""Unit tests for the SM-2 spaced repetition algorithm."""

from __future__ import annotations

import pytest

from app.services.sm2 import EASE_FACTOR_MIN, INITIAL_EASE_FACTOR, SM2State, apply_sm2

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

INITIAL_STATE = SM2State(
    interval_days=1,
    repetitions=0,
    ease_factor=INITIAL_EASE_FACTOR,
)


# ---------------------------------------------------------------------------
# Correct responses (grade >= 3) — interval progression
# ---------------------------------------------------------------------------


def test_first_correct_review_gives_interval_1():
    """Rep 0 → rep 1: interval must be 1 regardless of grade."""
    state = apply_sm2(INITIAL_STATE, grade=5)
    assert state.interval_days == 1
    assert state.repetitions == 1


def test_second_correct_review_gives_interval_6():
    """Rep 1 → rep 2: interval must jump to 6."""
    state = apply_sm2(INITIAL_STATE, grade=5)  # rep 0 → 1
    state = apply_sm2(state, grade=5)  # rep 1 → 2
    assert state.interval_days == 6
    assert state.repetitions == 2


def test_third_correct_review_multiplies_by_ease():
    """Rep 2 → rep 3: interval = round(6 * ease_factor)."""
    state = apply_sm2(INITIAL_STATE, grade=5)
    state = apply_sm2(state, grade=5)
    ef_before = state.ease_factor
    interval_before = state.interval_days  # 6
    state = apply_sm2(state, grade=5)
    assert state.interval_days == round(interval_before * ef_before)
    assert state.repetitions == 3


def test_grade_3_still_correct():
    """Grade 3 is the minimum for a 'correct' response."""
    state = apply_sm2(INITIAL_STATE, grade=3)
    assert state.interval_days == 1
    assert state.repetitions == 1


# ---------------------------------------------------------------------------
# Incorrect responses (grade < 3) — reset behaviour
# ---------------------------------------------------------------------------


def test_fail_resets_repetitions_to_zero():
    """After two correct reviews, a grade=1 must reset repetitions to 0."""
    state = apply_sm2(INITIAL_STATE, grade=5)
    state = apply_sm2(state, grade=5)
    assert state.repetitions == 2

    state = apply_sm2(state, grade=1)
    assert state.repetitions == 0
    assert state.interval_days == 1


def test_grade_2_resets():
    state = apply_sm2(INITIAL_STATE, grade=2)
    assert state.repetitions == 0
    assert state.interval_days == 1


def test_grade_0_resets():
    state = apply_sm2(INITIAL_STATE, grade=0)
    assert state.repetitions == 0
    assert state.interval_days == 1


# ---------------------------------------------------------------------------
# Ease factor adjustments
# ---------------------------------------------------------------------------


def test_ease_factor_increases_on_perfect_grade():
    """Grade 5 should increase ease_factor above the initial value."""
    state = apply_sm2(INITIAL_STATE, grade=5)
    assert state.ease_factor > INITIAL_EASE_FACTOR


def test_ease_factor_decreases_on_low_correct_grade():
    """Grade 3 (barely correct) should decrease ease_factor."""
    state = apply_sm2(INITIAL_STATE, grade=3)
    assert state.ease_factor < INITIAL_EASE_FACTOR


def test_ease_factor_never_below_minimum():
    """Repeated failures must not push ease_factor below EASE_FACTOR_MIN."""
    state = INITIAL_STATE
    for _ in range(20):
        state = apply_sm2(state, grade=0)
    assert state.ease_factor >= EASE_FACTOR_MIN


def test_ease_factor_rounded_to_4_decimal_places():
    state = apply_sm2(INITIAL_STATE, grade=4)
    # ease_factor should have at most 4 decimal places
    assert state.ease_factor == round(state.ease_factor, 4)


# ---------------------------------------------------------------------------
# Boundary / validation
# ---------------------------------------------------------------------------


def test_grade_above_5_raises():
    with pytest.raises(ValueError, match="Grade must be 0"):
        apply_sm2(INITIAL_STATE, grade=6)


def test_grade_below_0_raises():
    with pytest.raises(ValueError, match="Grade must be 0"):
        apply_sm2(INITIAL_STATE, grade=-1)


def test_grade_5_is_valid():
    state = apply_sm2(INITIAL_STATE, grade=5)
    assert state.repetitions == 1


def test_grade_0_is_valid():
    state = apply_sm2(INITIAL_STATE, grade=0)
    assert state.repetitions == 0


# ---------------------------------------------------------------------------
# Idempotency / state immutability
# ---------------------------------------------------------------------------


def test_apply_sm2_returns_new_state():
    """apply_sm2 must return a new SM2State, not mutate the original."""
    original = SM2State(interval_days=6, repetitions=2, ease_factor=2.5)
    new_state = apply_sm2(original, grade=5)
    assert original.interval_days == 6
    assert original.repetitions == 2
    assert new_state is not original
