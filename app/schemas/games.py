from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

# ================================================================
# Game submission
# ================================================================


class GameCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    pgn: str
    player_color: Literal["white", "black"]
    opponent_name: str | None = None
    played_at: str | None = None


# ================================================================
# Game response
# ================================================================


class GameResponse(BaseModel):
    id: int
    player_color: str
    pgn: str
    opponent_name: str | None
    played_at: str | None
    analyzed_at: str

    # Summary counts derived at analysis time
    match_count: int = 0
    miss_count: int = 0


# ================================================================
# Game skill event
# ================================================================


class GameSkillEventResponse(BaseModel):
    id: int
    game_id: int
    skill_block_id: int
    event_type: str  # 'match' or 'miss'
    fen: str
    expected_move: str
    actual_move: str | None
    ply: int
    created_at: str
