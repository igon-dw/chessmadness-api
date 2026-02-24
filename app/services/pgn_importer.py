from __future__ import annotations

import io
import logging
from dataclasses import dataclass

import chess.pgn

logger = logging.getLogger(__name__)


@dataclass
class LineData:
    """Represents a single linear sequence extracted from PGN."""

    start_fen: str
    moves: str


def expand_pgn_variations(pgn_text: str) -> list[LineData]:
    """
    Parse a PGN string and expand all variations into separate linear lines.

    If a game has branches (variations), each variation path is extracted as
    a separate line from the same starting position.

    Returns a list of LineData, one per variation path (including the main line).
    Raises ValueError if PGN parsing fails.
    """
    lines: list[LineData] = []

    try:
        pgn_io = io.StringIO(pgn_text)
        game = chess.pgn.read_game(pgn_io)
    except Exception as exc:
        raise ValueError(f"Failed to parse PGN: {exc}") from exc

    if game is None:
        raise ValueError("No valid game found in PGN")

    # Extract the starting FEN (or default to standard initial position)
    start_fen = game.headers.get("FEN", chess.STARTING_FEN)

    # Recursively walk the game tree and collect all paths
    def collect_paths(
        node: chess.pgn.GameNode, current_moves: list[str]
    ) -> list[list[str]]:
        """
        Recursively extract all variation paths from a game node.

        Returns a list of complete move sequences (main line + all branches).
        """
        paths: list[list[str]] = []

        # Try to get the next move
        next_node = node.next()
        if next_node is None:
            # Leaf node: record this path
            paths.append(current_moves)
            return paths

        # Add the next move to the current path
        if next_node.move is not None:
            new_moves = current_moves + [next_node.move.uci()]
        else:
            new_moves = current_moves

        # Explore main line (the first variation)
        paths.extend(collect_paths(next_node, new_moves))

        # Explore alternative variations (from index 1 onwards)
        for variation in node.variations[1:]:
            # Each variation starts from the current node, not from next_node
            if variation.move is not None:
                var_moves = current_moves + [variation.move.uci()]
            else:
                var_moves = current_moves
            paths.extend(collect_paths(variation, var_moves))

        return paths

    # Start walking from the root (before any moves are played)
    all_paths = collect_paths(game, [])

    # Convert each path to a LineData
    for path in all_paths:
        moves_str = " ".join(path) if path else ""
        lines.append(LineData(start_fen=start_fen, moves=moves_str))

    return lines if lines else [LineData(start_fen=start_fen, moves="")]
