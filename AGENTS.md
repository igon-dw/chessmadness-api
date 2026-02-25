# AGENTS.md - Agentic Coding Guidelines

This document provides guidelines for agentic coding agents operating in the `chessmadness-api` repository. This project is the FastAPI backend for the Chess Repertoire Trainer — a local, spaced-repetition-based chess learning application.

**Last Updated**: 2026-02-26 (enforced work log / learning notes in todo planning)  
**Maintained by**: Agentic auto-update

---

## Project Overview

Chess Repertoire Trainer (`chess-app`) is a locally self-contained application consisting of three sub-projects:

| Sub-project        | Role                                                              |
| ------------------ | ----------------------------------------------------------------- |
| `chess-ui`         | React + TypeScript frontend (board UI, learning interface)        |
| `chess-api`        | FastAPI backend (this repo) — data management and business logic  |
| `chess-llm-bridge` | Ollama integration — image-to-PGN/FEN extraction (Python package) |

This repository (`chessmadness-api`) corresponds to `chess-api`.

**Spec document:** `chessApp-specs.md` in this repository root.

---

## Build, Lint & Test Commands

### Setup (uv)

```bash
uv sync                  # Install dependencies from pyproject.toml
uv run fastapi dev       # Start dev server (http://localhost:8000)
```

### Development

```bash
uv run fastapi dev app/main.py   # Start with auto-reload
```

### Production

```bash
uv run fastapi run app/main.py   # Production mode
```

### Linting & Formatting

```bash
uv run ruff check .          # Run linter
uv run ruff check . --fix    # Auto-fix linting issues
uv run ruff format .         # Format code
```

### Type Checking

```bash
uv run mypy app/             # Run type checker
```

### Testing

```bash
uv run pytest                # Run all tests
uv run pytest -v             # Verbose output
uv run pytest tests/unit/    # Unit tests only
uv run pytest tests/integration/  # Integration tests only
```

---

## Test Policy

### Coverage requirements

Every service module in `app/services/` **must** have a corresponding unit test
file in `tests/unit/`. As of 2026-02-25 the mapping is:

| Service module                  | Unit test file                     |
| ------------------------------- | ---------------------------------- |
| `app/services/fen_index.py`     | `tests/unit/test_fen_index.py`     |
| `app/services/sm2.py`           | `tests/unit/test_sm2.py`           |
| `app/services/pgn_importer.py`  | `tests/unit/test_pgn_importer.py`  |
| `app/services/line_service.py`  | `tests/unit/test_line_service.py`  |
| `app/services/fen_normalize.py` | `tests/unit/test_fen_normalize.py` |
| `app/services/skill_service.py` | `tests/unit/test_skill_service.py` |
| `app/services/skill_share.py`   | `tests/unit/test_skill_share.py`   |
| `app/services/skill_mastery.py` | `tests/unit/test_skill_mastery.py` |
| `app/services/game_analyzer.py` | `tests/unit/test_game_analyzer.py` |

### Unit test guidelines

- **Pure functions** (e.g. `sm2.apply_sm2`, `pgn_importer.expand_pgn_variations`,
  `fen_index.build_fen_index`): use plain `pytest` functions, no fixtures.
- **Service functions with DB access** (e.g. `line_service.register_line`):
  use a real in-memory SQLite (`tmp_path` + `monkeypatch`) rather than mocks.
  This keeps tests realistic without the overhead of a full HTTP client.
- **Never delete test files** — if behaviour changes, update the assertions.
  If a feature is removed, mark the test with `@pytest.mark.skip` and a reason.

### Integration test guidelines

- Each router module in `app/routers/` has a corresponding file in
  `tests/integration/`.
- Use the shared `client` fixture from `tests/conftest.py` (async HTTPX client
  against a fresh in-memory DB per test).
- Integration tests exercise the full HTTP → service → DB round-trip.
- Prefer `@pytest.mark.asyncio` with the `client` fixture over the sync
  `TestClient` (exception: `test_import.py` uses the sync client due to
  background task handling — keep that pattern if it works).

### Isolation

- Every test gets a **fresh database** via `use_temp_db` (autouse) in conftest.
- Never share state between tests; never rely on test execution order.

---

## Code Style Guidelines

### 1. Python Version & Type Hints

- **Python 3.12+** (as specified in `pyproject.toml`)
- Always annotate function parameters and return types
- Use `from __future__ import annotations` for forward references
- Prefer `X | Y` union syntax over `Optional[X]` or `Union[X, Y]`

```python
# Correct
def get_line(line_id: int) -> Line | None:
    ...

# Incorrect
def get_line(line_id):
    ...
```

### 2. Pydantic Models

- Use Pydantic v2 (`model_config`, `model_validator`, etc.)
- Separate request/response schemas from DB models
- Place schemas in `app/schemas/`

```python
from pydantic import BaseModel, ConfigDict

class LineCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    moves: str
    start_fen: str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
```

### 3. FastAPI Route Organization

- Group routes by resource in `app/routers/`
- Use `APIRouter` with prefix and tags
- Return typed response models explicitly

```python
from fastapi import APIRouter

router = APIRouter(prefix="/lines", tags=["lines"])

@router.get("/{line_id}", response_model=LineResponse)
async def get_line(line_id: int) -> LineResponse:
    ...
```

### 4. Database Access (SQLite / aiosqlite)

- All DB access is async
- Use context managers for connections
- Never construct SQL with f-strings — always use parameterized queries

```python
# Correct
await conn.execute(
    "SELECT * FROM lines WHERE id = ?",
    (line_id,)
)

# NEVER do this
await conn.execute(f"SELECT * FROM lines WHERE id = {line_id}")
```

### 5. Error Handling

- Raise `HTTPException` with appropriate status codes in route handlers
- Use custom exception classes for domain errors (e.g., `InvalidMoveError`)
- Log errors with context using the `logging` module

```python
from fastapi import HTTPException

if not line:
    raise HTTPException(status_code=404, detail=f"Line {line_id} not found")
```

### 6. chess-llm-bridge Import

`chess-llm-bridge` is a Python package imported directly into `chess-api`. No IPC is involved.

```python
from chess_llm_bridge import extract_pgn_from_image
```

### 7. Naming Conventions

- **Files/modules**: `snake_case` (`pgn_importer.py`, `fen_index.py`)
- **Classes**: `PascalCase` (`LineRepository`, `PgnImporter`)
- **Functions/variables**: `snake_case`
- **Constants**: `UPPER_SNAKE_CASE`
- **Pydantic schemas**: suffix with `Create`, `Update`, `Response` (`LineCreate`, `LineResponse`)

---

## Project Structure

```
chessmadness-api/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── database.py          # DB connection and initialization
│   ├── routers/             # Route handlers grouped by resource
│   │   ├── lines.py
│   │   ├── themes.py
│   │   ├── import_.py
│   │   ├── review.py
│   │   ├── skills.py        # Skill block CRUD + graph + sharing + fork
│   │   └── games.py         # Game analysis (real-game PGN matching)
│   ├── schemas/             # Pydantic request/response models
│   │   ├── lines.py
│   │   ├── themes.py
│   │   ├── review.py
│   │   ├── skills.py        # SkillBlock, SkillLink, SkillMastery schemas
│   │   └── games.py         # Game, GameSkillEvent schemas
│   ├── models/              # DB row dataclasses / typed dicts
│   ├── services/            # Business logic
│   │   ├── pgn_importer.py
│   │   ├── fen_index.py
│   │   ├── fen_normalize.py # FEN normalization (4-field only)
│   │   ├── line_service.py
│   │   ├── sm2.py           # SM-2 + apply_game_miss_decay
│   │   ├── skill_service.py # SkillBlock CRUD + auto-link engine
│   │   ├── skill_share.py   # Share code encode/decode (JSON→zlib→Base64)
│   │   ├── skill_mastery.py # XP/level/rust/weapon score calculation
│   │   └── game_analyzer.py # Real-game PGN vs fen_index matching
│   └── core/
│       └── config.py        # Settings (Pydantic BaseSettings)
├── tests/
│   ├── conftest.py          # Shared fixtures (async client, temp DB)
│   ├── unit/
│   │   ├── test_fen_index.py
│   │   ├── test_sm2.py
│   │   ├── test_pgn_importer.py
│   │   ├── test_line_service.py
│   │   ├── test_fen_normalize.py
│   │   ├── test_skill_service.py
│   │   ├── test_skill_share.py
│   │   ├── test_skill_mastery.py
│   │   └── test_game_analyzer.py
│   └── integration/
│       ├── test_themes.py
│       ├── test_lines.py
│       ├── test_import.py
│       ├── test_review.py
│       ├── test_skills.py
│       └── test_games.py
├── pyproject.toml
├── chessApp-specs.md        # Full project specification
└── AGENTS.md                # This file
```

---

## Database

- **Engine**: SQLite with FTS5, accessed via `aiosqlite`
- **Schema**: defined in `chessApp-specs.md` § 7.2 and § 7.2.1
- **Migration**: managed manually or via a lightweight migration script (no Alembic by default)
- **File location**: configurable via `DATABASE_URL` env var, defaults to `./chess.db`

Key tables:

- `themes` — recursive self-referential hierarchy (adjacency list)
- `lines` — linear move sequences (no branches), unique on `(start_fen, moves)`
- `theme_lines` — many-to-many join between themes and lines
- `fen_index` — pre-computed FEN for every ply in every line
- `review_progress` — SRS state per `(theme × line)`, includes `ease_factor` (SM-2)
- `import_history` — provenance tracking for imported lines
- `skill_blocks` — user-named skill blocks wrapping lines (1:1 with lines)
- `skill_links` — directed graph edges between skill blocks (FEN-based auto-linking)
- `skill_mastery` — XP/level/rust inputs/weapon score per skill block
- `games` — manually submitted real-game PGNs for analysis
- `game_skill_events` — match/miss events from real-game vs skill block comparison

---

## Core Design Constraints

These constraints come directly from the spec and must be respected at all times:

1. **Lines are linear**: No branches. PGN variations must be exploded into separate lines at import time.
2. **Lines are unique**: `UNIQUE(start_fen, moves)` — duplicate lines across themes share a single DB record.
3. **FEN is pre-computed**: `fen_index` is populated at line insertion time using `python-chess`. Never compute FEN on-the-fly for queries.
4. **Review progress is per theme × line**: The same line can have different progress in different themes.
5. **Local-only**: No external network calls. LLM inference runs through Ollama locally.
6. **Non-standard start positions are supported**: `start_fen` is always explicit; do not assume standard initial position.
7. **Themes and skill blocks are independent**: Themes = human-defined folders. Skill blocks = FEN-causality graph. Never conflate the two.
8. **Rust level is never stored**: `rust_level` is computed on-read from stored inputs (`last_success_at`, `interval_days`, `last_game_miss_at`). Do not save it.
9. **Game matching requires no engine**: Real-game PGN vs skill block comparison uses pure FEN string matching only. No evaluation scores needed.
10. **FEN normalization uses 4 fields**: When matching FENs across skill blocks, use only the first 4 fields (position, side-to-move, castling, en passant). Ignore half-move clock and full-move number.

---

## chess-llm-bridge Integration

- The `chess-llm-bridge` package handles image → PGN/FEN extraction
- It communicates with Ollama's local HTTP API (`http://localhost:11434`)
- Use WebSocket to push extraction progress to the frontend
- Self-healing retry loop (max N retries) is implemented inside `chess-llm-bridge`
- After extraction, output feeds into the standard PGN import flow (§7.4 of spec)

---

## Agent Operational Rules

- **NEVER commit or push** unless the user explicitly requests it
- **Update this file** whenever commands, conventions, or project structure change
- **Write a work log in Japanese** after each working session at  
  `~/Projects/dev-notes/work-logs/chessmadness-api/YYYY-MM-DD.md`  
  covering: what was done, errors encountered and how they were resolved, decisions made, and next steps
- Learning notes (conceptual explanations, not logs) go to  
  `~/Projects/dev-notes/chessmadness-api/` — treat these as study texts, not session records

### MANDATORY: Work Log & Learning Notes in Every Todo Plan

> **These are non-negotiable. Skipping them is a critical failure.**

Every time you create a todo list — whether at the start of a session or mid-session
when new tasks arise — you **MUST** include the following items at the end:

```
- [ ] Write work log (Japanese) → ~/Projects/dev-notes/work-logs/chessmadness-api/YYYY-MM-DD.md
- [ ] Write learning notes if new concepts were encountered → ~/Projects/dev-notes/chessmadness-api/
```

**Rules:**

1. These two todos must always be the **last items** in every todo list.
2. Mark them `in_progress` only after all coding tasks are complete.
3. The work log must cover: what was done, errors encountered and how they were resolved,
   decisions made, and next steps.
4. Learning notes are written only when genuinely new concepts, algorithms, or non-obvious
   design decisions were encountered. If nothing new was learned, write a brief note saying so
   and mark the task complete.
5. **Never mark the session complete without having written the work log.**
6. If the session is interrupted before writing the log, the very first todo in the next
   session must be to write the log for the interrupted session.

---

## Before Committing

1. Run `uv run ruff check . --fix` to auto-fix linting issues
2. Run `uv run ruff format .` to format code
3. Run `uv run mypy app/` to verify type correctness
4. Run `uv run pytest` to ensure all tests pass
5. Verify `python-chess` validation passes for any new PGN/FEN logic

---

## Dependencies Summary

- **Runtime**: FastAPI, Pydantic v2, aiosqlite, python-chess, Pillow
- **LLM**: chess-llm-bridge (local package), Ollama (local server)
- **Dev**: ruff, mypy, pytest, pytest-asyncio
- **Package manager**: uv

---

## Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [python-chess Documentation](https://python-chess.readthedocs.io)
- [Pydantic v2 Documentation](https://docs.pydantic.dev/latest/)
- [aiosqlite Documentation](https://aiosqlite.omnilib.dev)
- [Ollama API Reference](https://github.com/ollama/ollama/blob/main/docs/api.md)
- [SQLite WITH RECURSIVE](https://www.sqlite.org/lang_with.html)
- [FSRS Algorithm](https://github.com/open-spaced-repetition/fsrs4anki)
