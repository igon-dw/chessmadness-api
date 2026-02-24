from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.database import get_db
from app.schemas.lines import (
    LineCreate,
    LineResponse,
    PgnImportRequest,
    PgnImportResponse,
)
from app.services.fen_index import InvalidMoveError
from app.services.line_service import register_line
from app.services.pgn_importer import expand_pgn_variations

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import", tags=["import"])


@router.post("/pgn", response_model=PgnImportResponse, status_code=201)
async def import_pgn(body: PgnImportRequest) -> PgnImportResponse:
    """
    Import a PGN string into the database.

    - Parses the PGN and expands all variations into separate lines.
    - Each line is inserted (or linked if already exists) to the given theme.
    - Returns summary and list of all processed lines.
    """
    # Parse PGN and extract lines
    try:
        line_data_list = expand_pgn_variations(body.pgn)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if not line_data_list:
        raise HTTPException(status_code=422, detail="PGN contains no valid moves")

    # Process each line
    created_lines: list[LineResponse] = []

    async with get_db() as db:
        # Validate theme exists before processing any lines
        async with db.execute(
            "SELECT id FROM themes WHERE id = ?", (body.theme_id,)
        ) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(
                    status_code=404, detail=f"Theme {body.theme_id} not found"
                )

        for idx, line_data in enumerate(line_data_list):
            sort_order = body.base_sort_order + idx
            line_create = LineCreate(
                moves=line_data.moves,
                start_fen=line_data.start_fen,
                theme_id=body.theme_id,
                sort_order=sort_order,
            )

            try:
                line_response = await register_line(db, line_create)
                created_lines.append(line_response)
            except InvalidMoveError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except ValueError as exc:
                # Theme not found — already validated above, so re-raise as 500
                logger.error("Unexpected error registering line %d: %s", idx, exc)
                raise HTTPException(status_code=500, detail=str(exc)) from exc

    return PgnImportResponse(
        lines_created=len(created_lines),
        lines_total=len(line_data_list),
        lines=created_lines,
    )
