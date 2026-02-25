"""Unit tests for the fen_index service."""

from __future__ import annotations

import pytest

from app.services.fen_index import InvalidMoveError, build_fen_index, get_final_fen

STANDARD_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


def test_build_fen_index_length():
    # SAN notation: e4 e5 Nf3 Nc6
    entries = build_fen_index(STANDARD_FEN, "e4 e5 Nf3 Nc6")
    # 4 moves → 5 entries (ply 0 through 4)
    assert len(entries) == 5


def test_build_fen_index_ply_zero_is_start():
    entries = build_fen_index(STANDARD_FEN, "e4")
    assert entries[0]["fen"] == STANDARD_FEN
    assert entries[0]["ply"] == 0
    assert entries[0]["next_move"] == "e4"


def test_build_fen_index_last_entry_has_no_next_move():
    entries = build_fen_index(STANDARD_FEN, "e4 e5")
    assert entries[-1]["next_move"] is None


def test_build_fen_index_empty_moves():
    entries = build_fen_index(STANDARD_FEN, "")
    assert len(entries) == 1
    assert entries[0]["next_move"] is None


def test_invalid_move_raises():
    with pytest.raises(InvalidMoveError, match="Nf6"):
        # Nf6 (Black knight) is illegal because it's White's turn at ply 0
        build_fen_index(STANDARD_FEN, "Nf6")


def test_get_final_fen_differs_from_start():
    final = get_final_fen(STANDARD_FEN, "e4 e5")
    assert final != STANDARD_FEN
