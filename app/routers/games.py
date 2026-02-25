from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.database import get_db
from app.schemas.games import GameCreate, GameResponse, GameSkillEventResponse
from app.services.game_analyzer import (
    PgnParseError,
    analyze_game,
    get_game,
    get_game_events,
    list_games,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/games", tags=["games"])


# ================================================================
# POST /games/analyze
# ================================================================


@router.post("/analyze", response_model=GameResponse, status_code=201)
async def analyze(body: GameCreate) -> GameResponse:
    """
    Submit a real-game PGN for analysis against stored skill blocks.

    Returns the created game record including match/miss summary counts.
    """
    try:
        async with get_db() as db:
            result = await analyze_game(
                db,
                pgn=body.pgn,
                player_color=body.player_color,
                opponent_name=body.opponent_name,
                played_at=body.played_at,
            )
    except PgnParseError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # analyze_game doesn't return analyzed_at; fetch it from the DB
    async with (
        get_db() as db,
        db.execute(
            "SELECT analyzed_at FROM games WHERE id = ?", (result["id"],)
        ) as cur,
    ):
        row = await cur.fetchone()
    analyzed_at: str = row["analyzed_at"] if row else ""

    return GameResponse(
        id=result["id"],
        player_color=result["player_color"],
        pgn=result["pgn"],
        opponent_name=result["opponent_name"],
        played_at=result["played_at"],
        analyzed_at=analyzed_at,
        match_count=result["match_count"],
        miss_count=result["miss_count"],
    )


# ================================================================
# GET /games
# ================================================================


@router.get("", response_model=list[GameResponse])
async def get_games() -> list[GameResponse]:
    """Return all analysed games with event summary counts."""
    async with get_db() as db:
        games = await list_games(db)
    return [
        GameResponse(
            id=g["id"],
            player_color=g["player_color"],
            pgn=g["pgn"],
            opponent_name=g["opponent_name"],
            played_at=g["played_at"],
            analyzed_at=g["analyzed_at"] or "",
            match_count=g["match_count"],
            miss_count=g["miss_count"],
        )
        for g in games
    ]


# ================================================================
# GET /games/{game_id}
# ================================================================


@router.get("/{game_id}", response_model=GameResponse)
async def get_single_game(game_id: int) -> GameResponse:
    """Return a single analysed game by ID with event summary counts."""
    async with get_db() as db:
        game = await get_game(db, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail=f"Game {game_id} not found")
    return GameResponse(
        id=game["id"],
        player_color=game["player_color"],
        pgn=game["pgn"],
        opponent_name=game["opponent_name"],
        played_at=game["played_at"],
        analyzed_at=game["analyzed_at"] or "",
        match_count=game["match_count"],
        miss_count=game["miss_count"],
    )


# ================================================================
# GET /games/{game_id}/events
# ================================================================


@router.get("/{game_id}/events", response_model=list[GameSkillEventResponse])
async def get_events(game_id: int) -> list[GameSkillEventResponse]:
    """Return all skill events for a given game, ordered by ply."""
    async with get_db() as db:
        # Verify game exists
        async with db.execute("SELECT id FROM games WHERE id = ?", (game_id,)) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(status_code=404, detail=f"Game {game_id} not found")
        events = await get_game_events(db, game_id)
    return [GameSkillEventResponse(**e) for e in events]
