from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.database import get_db
from app.schemas.skills import (
    MasteryDashboardResponse,
    RustDistribution,
    SkillBlockCreate,
    SkillBlockResponse,
    SkillBlockUpdate,
    SkillForkRequest,
    SkillImportRequest,
    SkillLinkResponse,
    SkillMasteryResponse,
    SkillPreviewResponse,
    SkillShareResponse,
    SkillTreeResponse,
)
from app.services.skill_service import (
    DuplicateSkillBlockError,
    create_skill_block,
    delete_skill_block,
    get_ancestors,
    get_children,
    get_mastery_dashboard,
    get_skill_block,
    get_skill_tree,
    list_critical_blocks,
    list_rusty_blocks,
    list_signature_blocks,
    search_blocks,
    update_skill_block,
)
from app.services.skill_share import (
    ShareCodeDecodeError,
    ShareCodeValidationError,
    fork_skill_block,
    generate_share_code,
    import_share_code,
    preview_share_code,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skills", tags=["skills"])

# ================================================================
# Helpers
# ================================================================


def _mastery_to_response(mastery: dict[str, Any] | None) -> SkillMasteryResponse | None:
    if mastery is None:
        return None
    return SkillMasteryResponse(**mastery)


def _block_to_response(block: dict[str, Any]) -> SkillBlockResponse:
    return SkillBlockResponse(
        id=block["id"],
        line_id=block["line_id"],
        name=block["name"],
        description=block["description"],
        tags=block["tags"],
        source_type=block["source_type"],
        share_code=block["share_code"],
        forked_from_id=block["forked_from_id"],
        created_at=block["created_at"],
        mastery=_mastery_to_response(block.get("mastery")),
    )


def _link_to_response(edge: dict[str, Any]) -> SkillLinkResponse:
    return SkillLinkResponse(
        id=edge["id"],
        parent_block_id=edge["parent_block_id"],
        child_block_id=edge["child_block_id"],
        link_fen=edge["link_fen"],
        link_type=edge["link_type"],
    )


# ================================================================
# Endpoints — named routes first (before parameterised ones)
# ================================================================


@router.get("/tree", response_model=SkillTreeResponse)
async def get_tree() -> SkillTreeResponse:
    """Return the full skill graph: all blocks (nodes) and links (edges)."""
    async with get_db() as db:
        result = await get_skill_tree(db)
    return SkillTreeResponse(
        nodes=[_block_to_response(n) for n in result["nodes"]],
        edges=[_link_to_response(e) for e in result["edges"]],
    )


@router.get("/rusty", response_model=list[SkillBlockResponse])
async def get_rusty() -> list[SkillBlockResponse]:
    """Return skill blocks with rust_level = aging / rusty / critical."""
    async with get_db() as db:
        blocks = await list_rusty_blocks(db)
    return [_block_to_response(b) for b in blocks]


@router.get("/critical", response_model=list[SkillBlockResponse])
async def get_critical() -> list[SkillBlockResponse]:
    """Return skill blocks where a real-game miss occurred after last success."""
    async with get_db() as db:
        blocks = await list_critical_blocks(db)
    return [_block_to_response(b) for b in blocks]


@router.get("/signatures", response_model=list[SkillBlockResponse])
async def get_signatures() -> list[SkillBlockResponse]:
    """Return skill blocks marked as signature weapons, best first."""
    async with get_db() as db:
        blocks = await list_signature_blocks(db)
    return [_block_to_response(b) for b in blocks]


@router.get("/search", response_model=list[SkillBlockResponse])
async def search(
    fen: str | None = Query(
        default=None, description="FEN to match (4-field normalised)"
    ),
    name: str | None = Query(default=None, description="Name substring"),
    tag: str | None = Query(default=None, description="Exact tag value"),
) -> list[SkillBlockResponse]:
    """Search skill blocks by FEN, name, or tag."""
    async with get_db() as db:
        blocks = await search_blocks(db, fen=fen, name=name, tag=tag)
    return [_block_to_response(b) for b in blocks]


@router.get("/mastery/dashboard", response_model=MasteryDashboardResponse)
async def mastery_dashboard() -> MasteryDashboardResponse:
    """
    Return an aggregated dashboard of skill mastery status:
    level distribution, rust state counts, and top signature weapons.
    """
    async with get_db() as db:
        data = await get_mastery_dashboard(db)
    return MasteryDashboardResponse(
        total_blocks=data["total_blocks"],
        total_xp=data["total_xp"],
        average_level=data["average_level"],
        level_distribution=data["level_distribution"],
        rust_distribution=RustDistribution(**data["rust_distribution"]),
        signature_count=data["signature_count"],
        top_signatures=[_block_to_response(b) for b in data["top_signatures"]],
    )


# ================================================================
# Endpoints — Share / Import / Fork
# (named routes — must come before /{block_id} parameterised routes)
# ================================================================


@router.post("/share", response_model=SkillShareResponse)
async def share_block(
    block_id: int = Query(..., description="ID of the skill block to share"),
) -> SkillShareResponse:
    """Generate a portable share code for an existing skill block."""
    try:
        async with get_db() as db:
            code = await generate_share_code(db, block_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return SkillShareResponse(share_code=code)


@router.post("/import-code", response_model=SkillBlockResponse, status_code=201)
async def import_code(body: SkillImportRequest) -> SkillBlockResponse:
    """Import a skill block from a share code."""
    try:
        async with get_db() as db:
            block = await import_share_code(
                db, code=body.share_code, name_override=body.name
            )
    except ShareCodeDecodeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ShareCodeValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _block_to_response(block)


@router.get("/preview/{code:path}", response_model=SkillPreviewResponse)
async def preview_code(code: str) -> SkillPreviewResponse:
    """Decode a share code and return a preview without touching the DB."""
    try:
        data = preview_share_code(code)
    except ShareCodeDecodeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SkillPreviewResponse(**data)


# ================================================================
# Endpoints — CRUD
# ================================================================


@router.post("", response_model=SkillBlockResponse, status_code=201)
async def create_block(body: SkillBlockCreate) -> SkillBlockResponse:
    """Create a skill block and run the auto-link engine."""
    try:
        async with get_db() as db:
            block = await create_skill_block(
                db,
                line_id=body.line_id,
                name=body.name,
                description=body.description,
                tags=body.tags,
            )
    except DuplicateSkillBlockError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _block_to_response(block)


@router.get("/{block_id}", response_model=SkillBlockResponse)
async def get_block(block_id: int) -> SkillBlockResponse:
    """Fetch a single skill block including mastery and rust_level."""
    async with get_db() as db:
        block = await get_skill_block(db, block_id)
    if block is None:
        raise HTTPException(status_code=404, detail=f"Skill block {block_id} not found")
    return _block_to_response(block)


@router.patch("/{block_id}", response_model=SkillBlockResponse)
async def patch_block(block_id: int, body: SkillBlockUpdate) -> SkillBlockResponse:
    """Edit a skill block's name, tags, description, or signature title."""
    async with get_db() as db:
        block = await update_skill_block(
            db,
            block_id=block_id,
            name=body.name,
            description=body.description,
            tags=body.tags,
            signature_title=body.signature_title,
        )
    if block is None:
        raise HTTPException(status_code=404, detail=f"Skill block {block_id} not found")
    return _block_to_response(block)


@router.delete("/{block_id}", status_code=204)
async def delete_block(block_id: int) -> None:
    """Delete a skill block (cascades to links and mastery)."""
    async with get_db() as db:
        deleted = await delete_skill_block(db, block_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Skill block {block_id} not found")


@router.get("/{block_id}/children", response_model=list[SkillBlockResponse])
async def get_block_children(block_id: int) -> list[SkillBlockResponse]:
    """Return direct children of a skill block in the skill graph."""
    async with get_db() as db:
        children = await get_children(db, block_id)
    return [_block_to_response(c) for c in children]


@router.get("/{block_id}/ancestors", response_model=list[SkillBlockResponse])
async def get_block_ancestors(block_id: int) -> list[SkillBlockResponse]:
    """Return the ancestor path from this block up to the root(s)."""
    async with get_db() as db:
        ancestors = await get_ancestors(db, block_id)
    return [_block_to_response(a) for a in ancestors]


@router.post("/{block_id}/fork", response_model=SkillBlockResponse, status_code=201)
async def fork_block(block_id: int, body: SkillForkRequest) -> SkillBlockResponse:
    """
    Fork a skill block: extend it with additional moves and create a new block.
    """
    try:
        async with get_db() as db:
            block = await fork_skill_block(
                db,
                parent_block_id=block_id,
                additional_moves=body.additional_moves,
                name=body.name,
            )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _block_to_response(block)
