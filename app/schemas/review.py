from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ReviewItem(BaseModel):
    """A single line due for review today."""

    theme_line_id: int
    line_id: int
    theme_id: int
    theme_name: str
    moves: str
    start_fen: str
    note: str | None
    next_review: str | None
    interval_days: int
    repetitions: int
    ease_factor: float


class ReviewReport(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    theme_line_id: int
    grade: int = Field(..., ge=0, le=5, description="SM-2 grade 0–5")


class ReviewReportResponse(BaseModel):
    theme_line_id: int
    interval_days: int
    repetitions: int
    ease_factor: float
    next_review: str
