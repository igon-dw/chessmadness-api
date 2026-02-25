"""
SM-2 spaced repetition algorithm.

Reference: https://www.supermemo.com/en/blog/application-of-a-computer-to-improve-the-results-obtained-in-working-with-the-super-memo-method

Grade scale (passed in from the review UI):
    5 — perfect response
    4 — correct response after a hesitation
    3 — correct response recalled with serious difficulty
    2 — incorrect response; where the correct one seemed easy to recall
    1 — incorrect response; the correct one remembered
    0 — complete blackout

interval_days / repetitions / ease_factor are stored in review_progress.
"""

from __future__ import annotations

from dataclasses import dataclass

EASE_FACTOR_MIN = 1.3
INITIAL_EASE_FACTOR = 2.5


@dataclass
class SM2State:
    interval_days: int
    repetitions: int
    ease_factor: float


def apply_sm2(state: SM2State, grade: int) -> SM2State:
    """
    Return the updated SM-2 state after a review with the given grade (0–5).

    - grade >= 3: correct response → advance interval
    - grade < 3:  incorrect → reset repetitions and interval (relearn)
    """
    if grade < 0 or grade > 5:
        raise ValueError(f"Grade must be 0–5, got {grade}")

    if grade >= 3:
        if state.repetitions == 0:
            new_interval = 1
        elif state.repetitions == 1:
            new_interval = 6
        else:
            new_interval = round(state.interval_days * state.ease_factor)

        new_repetitions = state.repetitions + 1
        new_ease = state.ease_factor + (0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
        new_ease = max(EASE_FACTOR_MIN, new_ease)
    else:
        # Incorrect: reset to relearn
        new_interval = 1
        new_repetitions = 0
        new_ease = max(EASE_FACTOR_MIN, state.ease_factor - 0.2)

    return SM2State(
        interval_days=new_interval,
        repetitions=new_repetitions,
        ease_factor=round(new_ease, 4),
    )


def apply_game_miss_decay(state: SM2State) -> SM2State:
    """
    Apply partial SM-2 decay after a real-game miss.

    Instead of a full reset, interval is halved, repetitions decremented by 1,
    and ease_factor slightly reduced. This avoids an avalanche of re-reviews
    while still surfacing the block sooner.
    """
    return SM2State(
        interval_days=max(1, state.interval_days // 2),
        repetitions=max(0, state.repetitions - 1),
        ease_factor=max(EASE_FACTOR_MIN, round(state.ease_factor - 0.1, 4)),
    )
