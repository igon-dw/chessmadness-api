"""Unit tests for the PGN importer service."""

from __future__ import annotations

import chess

from app.services.pgn_importer import LineData, expand_pgn_variations

STANDARD_FEN = chess.STARTING_FEN


# ---------------------------------------------------------------------------
# Basic parsing
# ---------------------------------------------------------------------------


def test_simple_game_returns_one_line():
    """A game with no variations produces exactly one LineData."""
    pgn = "1. e4 e5 2. Nf3 Nc6"
    lines = expand_pgn_variations(pgn)
    assert len(lines) == 1


def test_simple_game_moves_in_san():
    """Moves are returned as space-separated SAN tokens."""
    pgn = "1. e4 e5"
    lines = expand_pgn_variations(pgn)
    assert lines[0].moves == "e4 e5"


def test_simple_game_start_fen_is_standard():
    pgn = "1. e4 e5 2. Nf3 Nc6"
    lines = expand_pgn_variations(pgn)
    assert lines[0].start_fen == STANDARD_FEN


def test_returns_line_data_objects():
    pgn = "1. d4 d5"
    lines = expand_pgn_variations(pgn)
    assert all(isinstance(line, LineData) for line in lines)


# ---------------------------------------------------------------------------
# Variation explosion
# ---------------------------------------------------------------------------


def test_one_variation_produces_two_lines():
    """A single branch creates two LineData entries."""
    pgn = "1. e4 e5 2. Nf3 (2. Bc4 Nf6) 2... Nc6"
    lines = expand_pgn_variations(pgn)
    assert len(lines) == 2


def test_variation_moves_differ():
    """Main line and variation must have different move sequences."""
    pgn = "1. e4 e5 2. Nf3 (2. Bc4 Nf6) 2... Nc6"
    lines = expand_pgn_variations(pgn)
    move_sets = {line.moves for line in lines}
    assert len(move_sets) == 2


def test_nested_variation_produces_three_lines():
    """Two independent variations each create their own line."""
    pgn = """
    [Event "Test"]
    1. e4 e5 2. Nf3 Nc6 3. Bb5 (3. Bc4 Nf6) (3. d4 exd4)
    """
    lines = expand_pgn_variations(pgn)
    assert len(lines) == 3


def test_all_lines_share_same_start_fen():
    """All variation paths start from the same initial position."""
    pgn = "1. e4 (1. d4 d5) 1... e5"
    lines = expand_pgn_variations(pgn)
    fens = {line.start_fen for line in lines}
    assert len(fens) == 1


# ---------------------------------------------------------------------------
# Empty / no-move games
# ---------------------------------------------------------------------------


def test_empty_game_returns_one_empty_line():
    """A game with no moves returns a single LineData with moves=''."""
    # chess.pgn.read_game() accepts "empty" PGN headers without moves
    pgn = '[Event "Empty"]\n\n*'
    lines = expand_pgn_variations(pgn)
    assert len(lines) == 1
    assert lines[0].moves == ""


def test_invalid_pgn_text_returns_one_empty_line():
    """Completely unparseable text falls back to a single empty line."""
    lines = expand_pgn_variations("not a valid pgn at all")
    assert len(lines) == 1
    assert lines[0].moves == ""


# ---------------------------------------------------------------------------
# Non-standard start position (FEN header)
# ---------------------------------------------------------------------------


def test_custom_start_fen_is_preserved():
    """If the PGN has a FEN header, start_fen must reflect that position."""
    # King-and-pawn endgame: White King e1, White Pawn e2, Black King e8
    custom_fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
    pgn = f'[FEN "{custom_fen}"]\n[SetUp "1"]\n\n1. e4 *'
    lines = expand_pgn_variations(pgn)
    assert lines[0].start_fen == custom_fen


def test_custom_start_fen_move_in_san():
    """Moves from a custom FEN position are in SAN notation."""
    custom_fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
    pgn = f'[FEN "{custom_fen}"]\n[SetUp "1"]\n\n1. e4 *'
    lines = expand_pgn_variations(pgn)
    assert "e4" in lines[0].moves


# ---------------------------------------------------------------------------
# Move count consistency
# ---------------------------------------------------------------------------


def test_move_count_matches_tokens():
    """Number of space-separated tokens in moves equals expected ply count."""
    pgn = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6"
    lines = expand_pgn_variations(pgn)
    assert len(lines[0].moves.split()) == 6
