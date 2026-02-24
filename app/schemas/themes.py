from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ThemeCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str
    parent_id: int | None = None
    description: str | None = None
    sort_order: int = 0


class ThemeUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = None
    parent_id: int | None = None
    description: str | None = None
    sort_order: int | None = None


class ThemeResponse(BaseModel):
    id: int
    parent_id: int | None
    name: str
    description: str | None
    sort_order: int
    created_at: str


class ThemeNode(ThemeResponse):
    """ThemeResponse with nested children for tree responses."""

    children: list[ThemeNode] = []


# Required for recursive model self-reference
ThemeNode.model_rebuild()
