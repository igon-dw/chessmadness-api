"""
Game analyser service.

Analyses a manually submitted PGN against the skill blocks stored in the DB
using pure FEN string matching (no engine evaluation required).

Analysis flow (per spec §7.2 / §13):
  1. Parse the PGN with python-chess.
  2. Replay the game move-by-move, computing the normalised FEN at each ply.
  3. For each ply where it is the *player's* turn:
       a. Look up the normalised FEN in fen_index to find all skill blocks that
          "know" this position (i.e. have a fen_index entry with a non-NULL
          next_move).
       b. Compare the skill block's expected next_move (SAN) with the actual
          move played in the game (SAN).
       c. Record a 'match' or 'miss' event in game_skill_events.
  4. After recording events, update skill_mastery for each affected block via
     record_game_match / record_game_miss.
  5. Insert the game row and return a summary.

Design constraints:
  - FEN normalisation: 4-field only (normalize_fen from fen_normalize.py).
  - No engine calls.
  - player_color determines which plies to inspect.
  - Moves are stored and compared in SAN format.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import aiosqlite
import chess
import chess.pgn

from app.services.fen_normalize import normalize_fen
from app.services.skill_mastery import record_game_match, record_game_miss

logger = logging.getLogger(__name__)


class PgnParseError(Exception):
    """Raised when the PGN cannot be parsed."""


async def analyze_game(
    db: aiosqlite.Connection,
    pgn: str,
    player_color: str,  # 'white' or 'black'
    opponent_name: str | None = None,
    played_at: str | None = None,
) -> dict[str, Any]:
    """
    Analyse a PGN against stored skill blocks.

    Returns a dict describing the inserted game and event summary.
    Raises PgnParseError if the PGN is malformed.
    Raises ValueError for invalid player_color.
    """
    if player_color not in ("white", "black"):
        raise ValueError(
            f"player_color must be 'white' or 'black', got {player_color!r}"
        )

    # Parse the PGN
    game = chess.pgn.read_game(io.StringIO(pgn))
    if game is None:
        raise PgnParseError("Could not parse PGN — empty or malformed input")

    # Determine the colour to track
    track_white = player_color == "white"

    # Insert game row
    await db.execute(
        "INSERT INTO games (player_color, pgn, opponent_name, played_at) "
        "VALUES (?, ?, ?, ?)",
        (player_color, pgn, opponent_name, played_at),
    )
    async with db.execute("SELECT last_insert_rowid()") as cur:
        game_id: int = (await cur.fetchone())[0]  # type: ignore[index]

    # Replay the game and record events
    board = game.board()
    match_count = 0
    miss_count = 0

    # Track which blocks had a miss this game to avoid double-processing
    blocks_with_match: set[int] = set()
    blocks_with_miss: set[int] = set()

    for move in game.mainline_moves():
        # Check if it's the player's turn
        is_player_turn = (board.turn == chess.WHITE) == track_white

        if is_player_turn:
            norm_fen = normalize_fen(board.fen())
            # Convert actual move to SAN (fen_index stores next_move in SAN)
            actual_san = board.san(move)

            # Look up all skill blocks that have this FEN in their fen_index
            # with a non-NULL next_move (i.e. they "know" this position)
            async with db.execute(
                "SELECT fi.next_move, sb.id AS block_id "
                "FROM fen_index fi "
                "JOIN lines l ON l.id = fi.line_id "
                "JOIN skill_blocks sb ON sb.line_id = l.id "
                "WHERE normalize_fen_4(fi.fen) = ? AND fi.next_move IS NOT NULL",
                (norm_fen,),
            ) as cur:
                entries = await cur.fetchall()

            for entry in entries:
                block_id: int = entry["block_id"]
                expected_san: str = entry["next_move"]
                is_match = expected_san == actual_san
                event_type = "match" if is_match else "miss"

                # Record the event
                await db.execute(
                    "INSERT INTO game_skill_events "
                    "(game_id, skill_block_id, event_type, fen, "
                    "expected_move, actual_move, ply) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        game_id,
                        block_id,
                        event_type,
                        norm_fen,
                        expected_san,
                        actual_san,
                        board.ply(),
                    ),
                )

                if is_match:
                    match_count += 1
                    blocks_with_match.add(block_id)
                else:
                    miss_count += 1
                    blocks_with_miss.add(block_id)

        board.push(move)

    await db.commit()

    # Update skill_mastery for each affected block.
    # A block that had both match and miss events in the same game:
    # treat as a miss overall (the miss overrides the match).
    for block_id in blocks_with_miss:
        await record_game_miss(db, block_id)

    for block_id in blocks_with_match - blocks_with_miss:
        await record_game_match(db, block_id)

    return {
        "id": game_id,
        "player_color": player_color,
        "pgn": pgn,
        "opponent_name": opponent_name,
        "played_at": played_at,
        "match_count": match_count,
        "miss_count": miss_count,
    }


async def list_games(db: aiosqlite.Connection) -> list[dict[str, Any]]:
    """Return all analysed games with event summary counts."""
    async with db.execute(
        "SELECT g.id, g.player_color, g.pgn, g.opponent_name, "
        "g.played_at, g.analyzed_at, "
        "SUM(CASE WHEN e.event_type = 'match' THEN 1 ELSE 0 END) AS match_count, "
        "SUM(CASE WHEN e.event_type = 'miss'  THEN 1 ELSE 0 END) AS miss_count "
        "FROM games g "
        "LEFT JOIN game_skill_events e ON e.game_id = g.id "
        "GROUP BY g.id "
        "ORDER BY g.id DESC"
    ) as cur:
        rows = await cur.fetchall()

    return [
        {
            "id": row["id"],
            "player_color": row["player_color"],
            "pgn": row["pgn"],
            "opponent_name": row["opponent_name"],
            "played_at": row["played_at"],
            "analyzed_at": row["analyzed_at"],
            "match_count": row["match_count"] or 0,
            "miss_count": row["miss_count"] or 0,
        }
        for row in rows
    ]


async def get_game_events(
    db: aiosqlite.Connection,
    game_id: int,
) -> list[dict[str, Any]]:
    """Return all skill events for a given game, ordered by ply."""
    async with db.execute(
        "SELECT id, game_id, skill_block_id, event_type, fen, "
        "expected_move, actual_move, ply, created_at "
        "FROM game_skill_events "
        "WHERE game_id = ? ORDER BY ply ASC",
        (game_id,),
    ) as cur:
        rows = await cur.fetchall()

    return [
        {
            "id": row["id"],
            "game_id": row["game_id"],
            "skill_block_id": row["skill_block_id"],
            "event_type": row["event_type"],
            "fen": row["fen"],
            "expected_move": row["expected_move"],
            "actual_move": row["actual_move"],
            "ply": row["ply"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


async def get_game(
    db: aiosqlite.Connection,
    game_id: int,
) -> dict[str, Any] | None:
    """Return a single game by id with event summary counts, or None if not found."""
    async with db.execute(
        "SELECT g.id, g.player_color, g.pgn, g.opponent_name, "
        "g.played_at, g.analyzed_at, "
        "SUM(CASE WHEN e.event_type = 'match' THEN 1 ELSE 0 END) AS match_count, "
        "SUM(CASE WHEN e.event_type = 'miss'  THEN 1 ELSE 0 END) AS miss_count "
        "FROM games g "
        "LEFT JOIN game_skill_events e ON e.game_id = g.id "
        "WHERE g.id = ? "
        "GROUP BY g.id",
        (game_id,),
    ) as cur:
        row = await cur.fetchone()

    if row is None:
        return None

    return {
        "id": row["id"],
        "player_color": row["player_color"],
        "pgn": row["pgn"],
        "opponent_name": row["opponent_name"],
        "played_at": row["played_at"],
        "analyzed_at": row["analyzed_at"],
        "match_count": row["match_count"] or 0,
        "miss_count": row["miss_count"] or 0,
    }
