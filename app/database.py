from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import aiosqlite

from app.core.config import settings

logger = logging.getLogger(__name__)

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS themes (
    id          INTEGER PRIMARY KEY,
    parent_id   INTEGER REFERENCES themes(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_themes_parent ON themes(parent_id);

CREATE TABLE IF NOT EXISTS lines (
    id          INTEGER PRIMARY KEY,
    moves       TEXT NOT NULL,
    move_count  INTEGER NOT NULL,
    start_fen   TEXT NOT NULL DEFAULT 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1',
    final_fen   TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(start_fen, moves)
);

CREATE INDEX IF NOT EXISTS idx_lines_start_fen ON lines(start_fen);
CREATE INDEX IF NOT EXISTS idx_lines_final_fen ON lines(final_fen);

CREATE TABLE IF NOT EXISTS theme_lines (
    id          INTEGER PRIMARY KEY,
    theme_id    INTEGER NOT NULL REFERENCES themes(id) ON DELETE CASCADE,
    line_id     INTEGER NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    sort_order  INTEGER NOT NULL DEFAULT 0,
    note        TEXT,
    UNIQUE(theme_id, line_id)
);

CREATE INDEX IF NOT EXISTS idx_theme_lines_theme ON theme_lines(theme_id);
CREATE INDEX IF NOT EXISTS idx_theme_lines_line ON theme_lines(line_id);

CREATE TABLE IF NOT EXISTS fen_index (
    id          INTEGER PRIMARY KEY,
    line_id     INTEGER NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    ply         INTEGER NOT NULL,
    fen         TEXT NOT NULL,
    next_move   TEXT,
    UNIQUE(line_id, ply)
);

CREATE INDEX IF NOT EXISTS idx_fen_lookup ON fen_index(fen);
CREATE INDEX IF NOT EXISTS idx_fen_next ON fen_index(fen, next_move);

CREATE TABLE IF NOT EXISTS review_progress (
    id              INTEGER PRIMARY KEY,
    theme_line_id   INTEGER NOT NULL REFERENCES theme_lines(id) ON DELETE CASCADE,
    interval_days   INTEGER NOT NULL DEFAULT 0,
    repetitions     INTEGER NOT NULL DEFAULT 0,
    ease_factor     REAL    NOT NULL DEFAULT 2.5,
    next_review     TEXT,
    last_reviewed   TEXT,
    UNIQUE(theme_line_id)
);

CREATE TABLE IF NOT EXISTS import_history (
    id          INTEGER PRIMARY KEY,
    line_id     INTEGER NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    origin_type TEXT NOT NULL CHECK(origin_type IN ('pgn_file', 'llm_extraction', 'manual')),
    origin_ref  TEXT,
    imported_at TEXT DEFAULT (datetime('now'))
);
"""


async def init_db() -> None:
    """Create all tables if they do not exist yet. Called at app startup."""
    async with aiosqlite.connect(settings.database_url) as db:
        await db.executescript(_SCHEMA_SQL)
        await db.commit()
    logger.info("Database initialised at %s", settings.database_url)


@asynccontextmanager
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Async context manager that yields a configured DB connection."""
    async with aiosqlite.connect(settings.database_url) as db:
        db.row_factory = aiosqlite.Row
        # Enforce foreign key constraints (SQLite disables them by default)
        await db.execute("PRAGMA foreign_keys = ON")
        yield db
