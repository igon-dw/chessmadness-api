from __future__ import annotations

from pydantic import BaseModel, ConfigDict

STANDARD_START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


class LineCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    moves: str
    start_fen: str = STANDARD_START_FEN
    theme_id: int
    sort_order: int = 0
    note: str | None = None


class LineResponse(BaseModel):
    id: int
    moves: str
    move_count: int
    start_fen: str
    final_fen: str
    created_at: str
    theme_line_id: int | None = None


class LineWithThemeResponse(LineResponse):
    theme_id: int
    sort_order: int
    note: str | None


class FenMoveCount(BaseModel):
    next_move: str
    line_count: int


class LineThemeUpdate(BaseModel):
    """Mutable per-theme fields for a line (note and sort_order on theme_lines)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    theme_id: int
    note: str | None = None
    sort_order: int | None = None


class PgnImportRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    pgn: str
    theme_id: int
    base_sort_order: int = 0


class PgnImportResponse(BaseModel):
    lines_created: int
    lines_total: int
    lines: list[LineResponse]
