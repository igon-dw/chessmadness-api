from __future__ import annotations

import chess
import chess.pgn


class InvalidMoveError(Exception):
    """Raised when a move sequence fails python-chess validation."""


def build_fen_index(start_fen: str, moves: str) -> list[dict[str, object]]:
    """
    Replay every move in *moves* from *start_fen* and return one dict per ply.

    Moves may be provided in SAN or UCI format; they are stored as SAN in the
    returned dicts (and therefore in the fen_index table).

    The returned list can be bulk-inserted into the fen_index table::

        [{"ply": 0, "fen": "...", "next_move": "e4"},
         {"ply": 1, "fen": "...", "next_move": "e5"},
         ...
         {"ply": N, "fen": "...", "next_move": None}]

    Raises InvalidMoveError if any move is illegal or ambiguous.
    """
    board = chess.Board(start_fen)
    raw_list = moves.split() if moves.strip() else []
    # Resolve all moves upfront so we can use SAN for next_move references
    san_list: list[str] = []
    move_objects: list[chess.Move] = []

    for i, token in enumerate(raw_list):
        try:
            move = board.parse_san(token)
            san = board.san(move)
            san_list.append(san)
            move_objects.append(move)
            board.push(move)
        except (
            chess.InvalidMoveError,
            chess.IllegalMoveError,
            chess.AmbiguousMoveError,
            ValueError,
        ) as exc:
            raise InvalidMoveError(
                f"Invalid move at ply {i + 1}: '{token}' — {exc}"
            ) from exc

    # Build the index from scratch (board was advanced above — reset it)
    board = chess.Board(start_fen)
    result: list[dict[str, object]] = []

    result.append(
        {
            "ply": 0,
            "fen": board.fen(),
            "next_move": san_list[0] if san_list else None,
        }
    )

    for i, move in enumerate(move_objects):
        board.push(move)
        result.append(
            {
                "ply": i + 1,
                "fen": board.fen(),
                "next_move": san_list[i + 1] if i + 1 < len(san_list) else None,
            }
        )

    return result


def normalize_moves(start_fen: str, moves: str) -> str:
    """
    Validate *moves* (SAN or UCI) against *start_fen* and return them as a
    canonical space-separated SAN string.

    Raises InvalidMoveError if any move is illegal.
    """
    if not moves.strip():
        return ""
    board = chess.Board(start_fen)
    san_tokens: list[str] = []
    for i, token in enumerate(moves.split()):
        try:
            move = board.parse_san(token)
            san_tokens.append(board.san(move))
            board.push(move)
        except (
            chess.InvalidMoveError,
            chess.IllegalMoveError,
            chess.AmbiguousMoveError,
            ValueError,
        ) as exc:
            raise InvalidMoveError(
                f"Invalid move at ply {i + 1}: '{token}' — {exc}"
            ) from exc
    return " ".join(san_tokens)


def get_final_fen(start_fen: str, moves: str) -> str:
    """Return the FEN after replaying all moves. Raises InvalidMoveError on failure."""
    index = build_fen_index(start_fen, moves)
    return str(index[-1]["fen"])
