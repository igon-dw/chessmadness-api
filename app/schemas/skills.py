from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

# ================================================================
# Skill Block schemas
# ================================================================


class SkillBlockCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    line_id: int
    name: str
    description: str | None = None
    tags: list[str] = Field(default_factory=list)


class SkillBlockUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    signature_title: str | None = None


class SkillMasteryResponse(BaseModel):
    xp: int
    level: int
    streak: int
    max_streak: int
    perfect_runs: int
    last_success_at: str | None
    last_game_miss_at: str | None
    game_matches: int
    game_misses: int
    weapon_score: float
    is_signature: bool
    signature_title: str | None
    # Computed on-read — never stored
    rust_level: str


class SkillBlockResponse(BaseModel):
    id: int
    line_id: int
    name: str
    description: str | None
    tags: list[str]
    source_type: str
    share_code: str | None
    forked_from_id: int | None
    created_at: str
    mastery: SkillMasteryResponse | None = None


# ================================================================
# Skill Link schemas
# ================================================================


class SkillLinkResponse(BaseModel):
    id: int
    parent_block_id: int
    child_block_id: int
    link_fen: str
    link_type: str


# ================================================================
# Graph response
# ================================================================


class SkillTreeResponse(BaseModel):
    nodes: list[SkillBlockResponse]
    edges: list[SkillLinkResponse]


# ================================================================
# Fork
# ================================================================


class SkillForkRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    additional_moves: str
    name: str


# ================================================================
# Share / import
# ================================================================


class SkillShareResponse(BaseModel):
    share_code: str


class SkillImportRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    share_code: str
    name: str | None = None  # Override the name from the share code


class SkillPreviewResponse(BaseModel):
    name: str
    start_fen: str
    moves: str
    tags: list[str]
    description: str | None


# ================================================================
# Mastery dashboard
# ================================================================


class RustDistribution(BaseModel):
    fresh: int
    aging: int
    rusty: int
    critical: int


class MasteryDashboardResponse(BaseModel):
    total_blocks: int
    total_xp: int
    average_level: float
    level_distribution: dict[int, int]  # level → count
    rust_distribution: RustDistribution
    signature_count: int
    top_signatures: list[SkillBlockResponse]
