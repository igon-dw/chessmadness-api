"""
Integration tests for the /games endpoints.

Tests exercise the full HTTP → service → DB round-trip using the shared
async HTTPX client fixture from conftest.py.
"""

from __future__ import annotations

from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Minimal PGN helpers
# ---------------------------------------------------------------------------

PGN_E4_E5 = """\
[Event "Test"]
[White "Player"]
[Black "Opponent"]
[Result "*"]

1. e4 e5 *
"""

PGN_E4_E5_D4_D5 = """\
[Event "Test"]
[White "Player"]
[Black "Opponent"]
[Result "*"]

1. e4 e5 2. d4 d5 *
"""

PGN_INVALID = "not a pgn $$$"


# ---------------------------------------------------------------------------
# Test helpers — reuse pattern from test_skills.py
# ---------------------------------------------------------------------------


async def _make_theme(client: Any, name: str = "Test Theme") -> int:
    r = await client.post("/themes", json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


async def _make_line(
    client: Any,
    theme_id: int,
    moves: str = "e4 e5",
) -> dict[str, Any]:
    r = await client.post("/lines", json={"moves": moves, "theme_id": theme_id})
    assert r.status_code == 201
    return r.json()


async def _make_skill_block(
    client: Any,
    line_id: int,
    name: str = "Test Block",
) -> dict[str, Any]:
    r = await client.post("/skills", json={"line_id": line_id, "name": name})
    assert r.status_code == 201
    return r.json()


# ---------------------------------------------------------------------------
# POST /games/analyze
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_returns_201(client):
    r = await client.post(
        "/games/analyze",
        json={"pgn": PGN_E4_E5, "player_color": "white"},
    )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_analyze_response_fields(client):
    r = await client.post(
        "/games/analyze",
        json={
            "pgn": PGN_E4_E5,
            "player_color": "white",
            "opponent_name": "Magnus",
            "played_at": "2026-01-01",
        },
    )
    assert r.status_code == 201
    data = r.json()
    assert data["id"] is not None
    assert data["player_color"] == "white"
    assert data["opponent_name"] == "Magnus"
    assert data["played_at"] == "2026-01-01"
    assert "analyzed_at" in data
    assert "match_count" in data
    assert "miss_count" in data


@pytest.mark.asyncio
async def test_analyze_invalid_player_color_422(client):
    r = await client.post(
        "/games/analyze",
        json={"pgn": PGN_E4_E5, "player_color": "red"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_analyze_malformed_pgn_returns_game(client):
    """
    python-chess parses most garbage as an empty game (no moves).
    Rather than 422, we expect a 201 with zero events.
    A truly empty/None result would raise PgnParseError, but garbage
    input is treated as a zero-move game.
    """
    r = await client.post(
        "/games/analyze",
        json={"pgn": PGN_INVALID, "player_color": "white"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["match_count"] == 0
    assert data["miss_count"] == 0


@pytest.mark.asyncio
async def test_analyze_no_blocks_zero_counts(client):
    r = await client.post(
        "/games/analyze",
        json={"pgn": PGN_E4_E5, "player_color": "white"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["match_count"] == 0
    assert data["miss_count"] == 0


@pytest.mark.asyncio
async def test_analyze_match_detected(client):
    """Block covers e4 (SAN); white plays e4 → should record 1 match."""
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="e4")
    await _make_skill_block(client, line["id"], name="e4 opening")

    r = await client.post(
        "/games/analyze",
        json={"pgn": PGN_E4_E5, "player_color": "white"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["match_count"] == 1
    assert data["miss_count"] == 0


@pytest.mark.asyncio
async def test_analyze_miss_detected(client):
    """Block expects d4 (SAN); white plays e4 → should record 1 miss."""
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="d4")
    await _make_skill_block(client, line["id"], name="d4 opening")

    r = await client.post(
        "/games/analyze",
        json={"pgn": PGN_E4_E5, "player_color": "white"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["match_count"] == 0
    assert data["miss_count"] == 1


@pytest.mark.asyncio
async def test_analyze_pgn_persisted(client):
    r = await client.post(
        "/games/analyze",
        json={"pgn": PGN_E4_E5, "player_color": "black"},
    )
    assert r.status_code == 201
    game_id = r.json()["id"]

    # Verify it appears in GET /games
    r2 = await client.get("/games")
    assert r2.status_code == 200
    games = r2.json()
    ids = [g["id"] for g in games]
    assert game_id in ids


# ---------------------------------------------------------------------------
# GET /games
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_games_empty(client):
    r = await client.get("/games")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_games_returns_list(client):
    await client.post(
        "/games/analyze", json={"pgn": PGN_E4_E5, "player_color": "white"}
    )
    await client.post(
        "/games/analyze", json={"pgn": PGN_E4_E5, "player_color": "black"}
    )

    r = await client.get("/games")
    assert r.status_code == 200
    assert len(r.json()) == 2


@pytest.mark.asyncio
async def test_get_games_response_fields(client):
    await client.post(
        "/games/analyze",
        json={"pgn": PGN_E4_E5, "player_color": "white", "opponent_name": "Bot"},
    )
    r = await client.get("/games")
    assert r.status_code == 200
    g = r.json()[0]
    for field in [
        "id",
        "player_color",
        "pgn",
        "opponent_name",
        "played_at",
        "analyzed_at",
        "match_count",
        "miss_count",
    ]:
        assert field in g, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_get_games_newest_first(client):
    r1 = await client.post(
        "/games/analyze", json={"pgn": PGN_E4_E5, "player_color": "white"}
    )
    r2 = await client.post(
        "/games/analyze", json={"pgn": PGN_E4_E5, "player_color": "black"}
    )
    id1 = r1.json()["id"]
    id2 = r2.json()["id"]

    r = await client.get("/games")
    ids = [g["id"] for g in r.json()]
    assert ids.index(id2) < ids.index(id1)


@pytest.mark.asyncio
async def test_get_games_counts_match_summary(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="e4")
    await _make_skill_block(client, line["id"])

    await client.post(
        "/games/analyze", json={"pgn": PGN_E4_E5, "player_color": "white"}
    )

    r = await client.get("/games")
    g = r.json()[0]
    assert g["match_count"] == 1
    assert g["miss_count"] == 0


# ---------------------------------------------------------------------------
# GET /games/{game_id}/events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_events_404_unknown_game(client):
    r = await client.get("/games/9999/events")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_get_events_empty_when_no_blocks(client):
    r = await client.post(
        "/games/analyze", json={"pgn": PGN_E4_E5, "player_color": "white"}
    )
    game_id = r.json()["id"]

    r2 = await client.get(f"/games/{game_id}/events")
    assert r2.status_code == 200
    assert r2.json() == []


@pytest.mark.asyncio
async def test_get_events_returns_match_event(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="e4")
    await _make_skill_block(client, line["id"], name="e4")

    r = await client.post(
        "/games/analyze", json={"pgn": PGN_E4_E5, "player_color": "white"}
    )
    game_id = r.json()["id"]

    r2 = await client.get(f"/games/{game_id}/events")
    assert r2.status_code == 200
    events = r2.json()
    assert len(events) == 1
    e = events[0]
    assert e["event_type"] == "match"
    assert e["expected_move"] == "e4"
    assert e["actual_move"] == "e4"
    assert e["game_id"] == game_id


@pytest.mark.asyncio
async def test_get_events_returns_miss_event(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="d4")
    await _make_skill_block(client, line["id"], name="d4")

    r = await client.post(
        "/games/analyze", json={"pgn": PGN_E4_E5, "player_color": "white"}
    )
    game_id = r.json()["id"]

    r2 = await client.get(f"/games/{game_id}/events")
    assert r2.status_code == 200
    events = r2.json()
    assert len(events) == 1
    assert events[0]["event_type"] == "miss"
    assert events[0]["expected_move"] == "d4"
    assert events[0]["actual_move"] == "e4"


@pytest.mark.asyncio
async def test_get_events_fields(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="e4")
    await _make_skill_block(client, line["id"])

    r = await client.post(
        "/games/analyze", json={"pgn": PGN_E4_E5, "player_color": "white"}
    )
    game_id = r.json()["id"]

    r2 = await client.get(f"/games/{game_id}/events")
    e = r2.json()[0]
    for field in [
        "id",
        "game_id",
        "skill_block_id",
        "event_type",
        "fen",
        "expected_move",
        "actual_move",
        "ply",
        "created_at",
    ]:
        assert field in e, f"Missing field: {field}"


@pytest.mark.asyncio
async def test_get_events_ordered_by_ply(client):
    """Events for a multi-ply game should come back in ascending ply order."""
    theme_id = await _make_theme(client)
    line_a = await _make_line(client, theme_id, moves="e4")
    line_b = await _make_line(client, theme_id, moves="e4 e5 d4")
    await _make_skill_block(client, line_a["id"], name="A")
    await _make_skill_block(client, line_b["id"], name="B")

    r = await client.post(
        "/games/analyze",
        json={"pgn": PGN_E4_E5_D4_D5, "player_color": "white"},
    )
    game_id = r.json()["id"]

    r2 = await client.get(f"/games/{game_id}/events")
    plies = [e["ply"] for e in r2.json()]
    assert plies == sorted(plies)


# ---------------------------------------------------------------------------
# Mastery updated after analysis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mastery_game_match_incremented(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="e4")
    block = await _make_skill_block(client, line["id"])
    block_id = block["id"]

    await client.post(
        "/games/analyze", json={"pgn": PGN_E4_E5, "player_color": "white"}
    )

    r = await client.get(f"/skills/{block_id}")
    mastery = r.json()["mastery"]
    assert mastery["game_matches"] == 1
    assert mastery["game_misses"] == 0


@pytest.mark.asyncio
async def test_mastery_game_miss_incremented(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="d4")
    block = await _make_skill_block(client, line["id"])
    block_id = block["id"]

    await client.post(
        "/games/analyze", json={"pgn": PGN_E4_E5, "player_color": "white"}
    )

    r = await client.get(f"/skills/{block_id}")
    mastery = r.json()["mastery"]
    assert mastery["game_misses"] == 1
    assert mastery["game_matches"] == 0


# ---------------------------------------------------------------------------
# GET /games/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_single_game(client):
    """GET /games/{id} returns the game record with summary counts."""
    r = await client.post(
        "/games/analyze", json={"pgn": PGN_E4_E5, "player_color": "white"}
    )
    assert r.status_code == 201
    game_id = r.json()["id"]

    r = await client.get(f"/games/{game_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == game_id
    assert data["player_color"] == "white"
    assert "match_count" in data
    assert "miss_count" in data


@pytest.mark.asyncio
async def test_get_single_game_not_found(client):
    """GET /games/{id} returns 404 for unknown id."""
    r = await client.get("/games/9999")
    assert r.status_code == 404
