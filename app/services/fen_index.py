from __future__ import annotations

import chess
import chess.pgn


class InvalidMoveError(Exception):
    """Raised when a move sequence fails python-chess validation."""


def build_fen_index(start_fen: str, moves: str) -> list[dict[str, object]]:
    """
    Replay every move in *moves* from *start_fen* and return one dict per ply.

    The returned list can be bulk-inserted into the fen_index table::

        [{"ply": 0, "fen": "...", "next_move": "e4"},
         {"ply": 1, "fen": "...", "next_move": "e5"},
         ...
         {"ply": N, "fen": "...", "next_move": None}]

    Raises InvalidMoveError if any move is illegal or ambiguous.
    """
    board = chess.Board(start_fen)
    move_list = moves.split() if moves.strip() else []
    result: list[dict[str, object]] = []

    result.append(
        {
            "ply": 0,
            "fen": board.fen(),
            "next_move": move_list[0] if move_list else None,
        }
    )

    for i, san in enumerate(move_list):
        try:
            board.push_san(san)
        except (
            chess.InvalidMoveError,
            chess.IllegalMoveError,
            chess.AmbiguousMoveError,
        ) as exc:
            raise InvalidMoveError(
                f"Invalid move at ply {i + 1}: '{san}' — {exc}"
            ) from exc

        result.append(
            {
                "ply": i + 1,
                "fen": board.fen(),
                "next_move": move_list[i + 1] if i + 1 < len(move_list) else None,
            }
        )

    return result


def get_final_fen(start_fen: str, moves: str) -> str:
    """Return the FEN after replaying all moves. Raises InvalidMoveError on failure."""
    index = build_fen_index(start_fen, moves)
    return str(index[-1]["fen"])
