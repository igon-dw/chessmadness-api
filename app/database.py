from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import aiosqlite

from app.core.config import settings
from app.services.fen_normalize import normalize_fen

logger = logging.getLogger(__name__)


def _sqlite_normalize_fen_4(fen: str) -> str:
    """SQLite scalar function: return the 4-field normalized FEN."""
    try:
        return normalize_fen(fen)
    except ValueError:
        return fen


async def _configure_connection(db: aiosqlite.Connection) -> None:
    """Apply PRAGMA settings and register custom functions on a connection."""
    await db.execute("PRAGMA foreign_keys = ON")
    await db.create_function("normalize_fen_4", 1, _sqlite_normalize_fen_4)


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

-- ================================================================
-- Skill Block System
-- ================================================================

CREATE TABLE IF NOT EXISTS skill_blocks (
    id              INTEGER PRIMARY KEY,
    line_id         INTEGER NOT NULL REFERENCES lines(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    description     TEXT,
    tags            TEXT,
    source_type     TEXT NOT NULL DEFAULT 'original'
                    CHECK(source_type IN ('original', 'imported', 'forked')),
    share_code      TEXT UNIQUE,
    forked_from_id  INTEGER REFERENCES skill_blocks(id) ON DELETE SET NULL,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(line_id)
);

CREATE INDEX IF NOT EXISTS idx_skill_blocks_line  ON skill_blocks(line_id);
CREATE INDEX IF NOT EXISTS idx_skill_blocks_share ON skill_blocks(share_code);

CREATE TABLE IF NOT EXISTS skill_links (
    id              INTEGER PRIMARY KEY,
    parent_block_id INTEGER NOT NULL REFERENCES skill_blocks(id) ON DELETE CASCADE,
    child_block_id  INTEGER NOT NULL REFERENCES skill_blocks(id) ON DELETE CASCADE,
    link_fen        TEXT NOT NULL,
    link_type       TEXT NOT NULL DEFAULT 'auto'
                    CHECK(link_type IN ('auto', 'manual')),
    UNIQUE(parent_block_id, child_block_id)
);

CREATE INDEX IF NOT EXISTS idx_skill_links_parent ON skill_links(parent_block_id);
CREATE INDEX IF NOT EXISTS idx_skill_links_child  ON skill_links(child_block_id);
CREATE INDEX IF NOT EXISTS idx_skill_links_fen    ON skill_links(link_fen);

CREATE TABLE IF NOT EXISTS skill_mastery (
    id                INTEGER PRIMARY KEY,
    skill_block_id    INTEGER NOT NULL REFERENCES skill_blocks(id) ON DELETE CASCADE,
    xp                INTEGER NOT NULL DEFAULT 0,
    level             INTEGER NOT NULL DEFAULT 1,
    streak            INTEGER NOT NULL DEFAULT 0,
    max_streak        INTEGER NOT NULL DEFAULT 0,
    perfect_runs      INTEGER NOT NULL DEFAULT 0,
    last_success_at   TEXT,
    last_game_miss_at TEXT,
    game_matches      INTEGER NOT NULL DEFAULT 0,
    game_misses       INTEGER NOT NULL DEFAULT 0,
    weapon_score      REAL    NOT NULL DEFAULT 0.0,
    is_signature      INTEGER NOT NULL DEFAULT 0,
    signature_title   TEXT,
    UNIQUE(skill_block_id)
);

CREATE INDEX IF NOT EXISTS idx_skill_mastery_block     ON skill_mastery(skill_block_id);
CREATE INDEX IF NOT EXISTS idx_skill_mastery_signature ON skill_mastery(is_signature);
CREATE INDEX IF NOT EXISTS idx_skill_mastery_weapon    ON skill_mastery(weapon_score DESC);

-- ================================================================
-- Real-game Analysis
-- ================================================================

CREATE TABLE IF NOT EXISTS games (
    id            INTEGER PRIMARY KEY,
    player_color  TEXT NOT NULL CHECK(player_color IN ('white', 'black')),
    pgn           TEXT NOT NULL,
    opponent_name TEXT,
    played_at     TEXT,
    analyzed_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS game_skill_events (
    id              INTEGER PRIMARY KEY,
    game_id         INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
    skill_block_id  INTEGER NOT NULL REFERENCES skill_blocks(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL CHECK(event_type IN ('match', 'miss')),
    fen             TEXT NOT NULL,
    expected_move   TEXT NOT NULL,
    actual_move     TEXT,
    ply             INTEGER NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_game_events_game  ON game_skill_events(game_id);
CREATE INDEX IF NOT EXISTS idx_game_events_block ON game_skill_events(skill_block_id);
CREATE INDEX IF NOT EXISTS idx_game_events_type  ON game_skill_events(event_type);
"""


async def init_db() -> None:
    """Create all tables if they do not exist yet. Called at app startup."""
    async with aiosqlite.connect(settings.database_url) as db:
        await _configure_connection(db)
        await db.executescript(_SCHEMA_SQL)
        await db.commit()
    logger.info("Database initialised at %s", settings.database_url)


@asynccontextmanager
async def get_db() -> AsyncGenerator[aiosqlite.Connection, None]:
    """Async context manager that yields a configured DB connection."""
    async with aiosqlite.connect(settings.database_url) as db:
        db.row_factory = aiosqlite.Row
        await _configure_connection(db)
        yield db
