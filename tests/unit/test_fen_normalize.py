"""Unit tests for the fen_normalize service."""

from __future__ import annotations

import pytest

from app.services.fen_normalize import normalize_fen

STANDARD_6_FIELD = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
STANDARD_4_FIELD = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -"

AFTER_E4_6_FIELD = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
AFTER_E4_4_FIELD = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3"


# ---------------------------------------------------------------------------
# Core behaviour
# ---------------------------------------------------------------------------


def test_strips_half_move_and_full_move():
    """6-field FEN is reduced to the first 4 fields."""
    assert normalize_fen(STANDARD_6_FIELD) == STANDARD_4_FIELD


def test_already_4_field_is_unchanged():
    """A FEN that is already 4 fields is returned as-is."""
    assert normalize_fen(STANDARD_4_FIELD) == STANDARD_4_FIELD


def test_en_passant_square_is_preserved():
    """The en-passant field (field 4) must not be stripped."""
    assert normalize_fen(AFTER_E4_6_FIELD) == AFTER_E4_4_FIELD


def test_returns_string():
    assert isinstance(normalize_fen(STANDARD_6_FIELD), str)


# ---------------------------------------------------------------------------
# Same position, different move counters → same normalized FEN
# ---------------------------------------------------------------------------


def test_different_counters_produce_same_result():
    """Two FENs that differ only in half-move/full-move counters normalize equal."""
    fen_a = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    fen_b = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 12 99"
    assert normalize_fen(fen_a) == normalize_fen(fen_b)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_fewer_than_4_fields_raises():
    with pytest.raises(ValueError, match="expected at least 4"):
        normalize_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w")


def test_empty_string_raises():
    with pytest.raises(ValueError):
        normalize_fen("")
