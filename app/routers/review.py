from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException

from app.database import get_db
from app.schemas.review import ReviewItem, ReviewReport, ReviewReportResponse
from app.services.skill_mastery import record_review_fail, record_review_success
from app.services.sm2 import INITIAL_EASE_FACTOR, SM2State, apply_sm2

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/review", tags=["review"])


@router.get("/today", response_model=list[ReviewItem])
async def get_today_reviews(theme_id: int | None = None) -> list[ReviewItem]:
    """
    Return all lines due for review today (next_review <= today).

    Optionally filter by theme_id (includes descendants via WITH RECURSIVE).
    Lines that have never been reviewed (no review_progress row) are excluded —
    they must be explicitly started via POST /review/report with grade 5.
    """
    params: tuple[int, ...] | tuple[()] = ()
    async with get_db() as db:
        if theme_id is not None:
            async with db.execute(
                "SELECT id FROM themes WHERE id = ?", (theme_id,)
            ) as cur:
                if await cur.fetchone() is None:
                    raise HTTPException(
                        status_code=404, detail=f"Theme {theme_id} not found"
                    )

            query = """
            WITH RECURSIVE subtree AS (
                SELECT id FROM themes WHERE id = ?
                UNION ALL
                SELECT t.id FROM themes t
                JOIN subtree s ON t.parent_id = s.id
            )
            SELECT rp.id AS rp_id, rp.theme_line_id, rp.interval_days,
                   rp.repetitions, rp.ease_factor, rp.next_review,
                   tl.line_id, tl.theme_id, tl.note,
                   l.moves, l.start_fen, l.final_fen,
                   th.name AS theme_name
            FROM review_progress rp
            JOIN theme_lines tl ON tl.id = rp.theme_line_id
            JOIN lines l ON l.id = tl.line_id
            JOIN themes th ON th.id = tl.theme_id
            WHERE rp.next_review <= date('now')
              AND tl.theme_id IN (SELECT id FROM subtree)
            ORDER BY rp.next_review ASC
            """
            params = (theme_id,)
        else:
            query = """
            SELECT rp.id AS rp_id, rp.theme_line_id, rp.interval_days,
                   rp.repetitions, rp.ease_factor, rp.next_review,
                   tl.line_id, tl.theme_id, tl.note,
                   l.moves, l.start_fen, l.final_fen,
                   th.name AS theme_name
            FROM review_progress rp
            JOIN theme_lines tl ON tl.id = rp.theme_line_id
            JOIN lines l ON l.id = tl.line_id
            JOIN themes th ON th.id = tl.theme_id
            WHERE rp.next_review <= date('now')
            ORDER BY rp.next_review ASC
            """
            params = ()

        async with db.execute(query, params) as cur:
            rows = await cur.fetchall()

    return [
        ReviewItem(
            theme_line_id=r["theme_line_id"],
            line_id=r["line_id"],
            theme_id=r["theme_id"],
            theme_name=r["theme_name"],
            moves=r["moves"],
            start_fen=r["start_fen"],
            final_fen=r["final_fen"],
            note=r["note"],
            next_review=r["next_review"],
            interval_days=r["interval_days"],
            repetitions=r["repetitions"],
            ease_factor=r["ease_factor"],
        )
        for r in rows
    ]


@router.post("/report", response_model=ReviewReportResponse, status_code=200)
async def report_review(body: ReviewReport) -> ReviewReportResponse:
    """
    Record the result of a review session.

    Creates a review_progress row if it does not exist yet (first review).
    Applies SM-2 to compute the next interval and updates the row.
    """
    async with get_db() as db:
        # Verify theme_line exists
        async with db.execute(
            "SELECT id FROM theme_lines WHERE id = ?", (body.theme_line_id,)
        ) as cur:
            if await cur.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"theme_line {body.theme_line_id} not found",
                )

        # Fetch or initialise review_progress
        async with db.execute(
            "SELECT interval_days, repetitions, ease_factor "
            "FROM review_progress WHERE theme_line_id = ?",
            (body.theme_line_id,),
        ) as cur:
            row = await cur.fetchone()

        if row is None:
            current = SM2State(
                interval_days=0,
                repetitions=0,
                ease_factor=INITIAL_EASE_FACTOR,
            )
        else:
            current = SM2State(
                interval_days=row["interval_days"],
                repetitions=row["repetitions"],
                ease_factor=row["ease_factor"],
            )

        # Apply SM-2
        updated = apply_sm2(current, body.grade)
        next_review = (date.today() + timedelta(days=updated.interval_days)).isoformat()
        today = date.today().isoformat()

        # Upsert review_progress
        await db.execute(
            """
            INSERT INTO review_progress
                (theme_line_id, interval_days, repetitions, ease_factor,
                 next_review, last_reviewed)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(theme_line_id) DO UPDATE SET
                interval_days = excluded.interval_days,
                repetitions   = excluded.repetitions,
                ease_factor   = excluded.ease_factor,
                next_review   = excluded.next_review,
                last_reviewed = excluded.last_reviewed
            """,
            (
                body.theme_line_id,
                updated.interval_days,
                updated.repetitions,
                updated.ease_factor,
                next_review,
                today,
            ),
        )
        await db.commit()

        # Update skill_mastery for the skill block linked to this line (if any)
        async with db.execute(
            "SELECT tl.line_id FROM theme_lines tl WHERE tl.id = ?",
            (body.theme_line_id,),
        ) as cur:
            tl_row = await cur.fetchone()

        if tl_row is not None:
            async with db.execute(
                "SELECT id FROM skill_blocks WHERE line_id = ?",
                (tl_row["line_id"],),
            ) as cur:
                sb_row = await cur.fetchone()

            if sb_row is not None:
                if body.grade >= 3:
                    await record_review_success(db, sb_row["id"], body.grade)
                else:
                    await record_review_fail(db, sb_row["id"])

    return ReviewReportResponse(
        theme_line_id=body.theme_line_id,
        interval_days=updated.interval_days,
        repetitions=updated.repetitions,
        ease_factor=updated.ease_factor,
        next_review=next_review,
    )
