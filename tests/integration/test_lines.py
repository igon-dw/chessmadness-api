"""Integration tests for the /lines endpoints."""

from __future__ import annotations

import pytest

STANDARD_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


async def _make_theme(client, name: str = "Test Theme") -> int:
    r = await client.post("/themes", json={"name": name})
    return r.json()["id"]


@pytest.mark.asyncio
async def test_create_line(client):
    theme_id = await _make_theme(client)
    r = await client.post(
        "/lines",
        json={"moves": "e4 e5 Nf3 Nc6", "theme_id": theme_id},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["moves"] == "e4 e5 Nf3 Nc6"
    assert data["move_count"] == 4
    assert data["start_fen"] == STANDARD_FEN
    assert data["final_fen"] != STANDARD_FEN


@pytest.mark.asyncio
async def test_create_line_invalid_moves(client):
    theme_id = await _make_theme(client)
    r = await client.post(
        "/lines",
        json={"moves": "e4 Nf6 INVALID", "theme_id": theme_id},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_create_line_unknown_theme(client):
    r = await client.post(
        "/lines",
        json={"moves": "e4 e5", "theme_id": 9999},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_duplicate_line_shared_across_themes(client):
    t1 = await _make_theme(client, "Theme A")
    t2 = await _make_theme(client, "Theme B")

    r1 = await client.post("/lines", json={"moves": "e4 e5", "theme_id": t1})
    r2 = await client.post("/lines", json={"moves": "e4 e5", "theme_id": t2})

    assert r1.status_code == 201
    assert r2.status_code == 201
    # Same line record should be returned
    assert r1.json()["id"] == r2.json()["id"]


@pytest.mark.asyncio
async def test_get_line(client):
    theme_id = await _make_theme(client)
    r = await client.post("/lines", json={"moves": "d4 d5", "theme_id": theme_id})
    line_id = r.json()["id"]

    r2 = await client.get(f"/lines/{line_id}")
    assert r2.status_code == 200
    assert r2.json()["moves"] == "d4 d5"


@pytest.mark.asyncio
async def test_delete_line(client):
    theme_id = await _make_theme(client)
    r = await client.post("/lines", json={"moves": "e4", "theme_id": theme_id})
    line_id = r.json()["id"]

    await client.delete(f"/lines/{line_id}")
    assert (await client.get(f"/lines/{line_id}")).status_code == 404


@pytest.mark.asyncio
async def test_list_lines_by_theme(client):
    theme_id = await _make_theme(client)
    await client.post("/lines", json={"moves": "e4 e5", "theme_id": theme_id})
    await client.post("/lines", json={"moves": "d4 d5", "theme_id": theme_id})

    r = await client.get(f"/lines/by-theme/{theme_id}")
    assert r.status_code == 200
    assert len(r.json()) == 2


@pytest.mark.asyncio
async def test_list_lines_by_theme_with_descendants(client):
    parent_id = await _make_theme(client, "Parent")
    r = await client.post("/themes", json={"name": "Child", "parent_id": parent_id})
    child_id = r.json()["id"]

    await client.post("/lines", json={"moves": "e4 e5", "theme_id": parent_id})
    await client.post("/lines", json={"moves": "d4 d5", "theme_id": child_id})

    # Without descendants
    r1 = await client.get(f"/lines/by-theme/{parent_id}")
    assert len(r1.json()) == 1

    # With descendants
    r2 = await client.get(f"/lines/by-theme/{parent_id}?include_descendants=true")
    assert len(r2.json()) == 2


@pytest.mark.asyncio
async def test_moves_from_fen(client):
    theme_id = await _make_theme(client)
    await client.post("/lines", json={"moves": "e4 e5", "theme_id": theme_id})
    await client.post("/lines", json={"moves": "e4 d5", "theme_id": theme_id})

    r = await client.get(f"/lines/by-fen/{STANDARD_FEN}")
    assert r.status_code == 200
    moves = {m["next_move"] for m in r.json()}
    assert "e4" in moves


# ---------------------------------------------------------------------------
# PATCH /lines/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_line_note(client):
    """PATCH /lines/{id} updates the note for a line in a theme."""
    theme_id = await _make_theme(client)
    r = await client.post("/lines", json={"moves": "e4 e5", "theme_id": theme_id})
    line_id = r.json()["id"]

    r = await client.patch(
        f"/lines/{line_id}",
        json={"theme_id": theme_id, "note": "My annotation"},
    )
    assert r.status_code == 200
    assert r.json()["note"] == "My annotation"


@pytest.mark.asyncio
async def test_patch_line_sort_order(client):
    """PATCH /lines/{id} updates sort_order for a line in a theme."""
    theme_id = await _make_theme(client)
    r = await client.post("/lines", json={"moves": "d4 d5", "theme_id": theme_id})
    line_id = r.json()["id"]

    r = await client.patch(
        f"/lines/{line_id}",
        json={"theme_id": theme_id, "sort_order": 42},
    )
    assert r.status_code == 200
    assert r.json()["sort_order"] == 42


@pytest.mark.asyncio
async def test_patch_line_not_found(client):
    """PATCH /lines/{id} returns 404 for unknown line."""
    theme_id = await _make_theme(client)
    r = await client.patch("/lines/9999", json={"theme_id": theme_id, "note": "x"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_line_unknown_theme(client):
    """PATCH /lines/{id} returns 404 if the line is not in the given theme."""
    theme_id = await _make_theme(client)
    r = await client.post("/lines", json={"moves": "e4", "theme_id": theme_id})
    line_id = r.json()["id"]

    r = await client.patch(f"/lines/{line_id}", json={"theme_id": 9999, "note": "x"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_patch_line_no_fields(client):
    """PATCH /lines/{id} returns 422 when no update fields are provided."""
    theme_id = await _make_theme(client)
    r = await client.post("/lines", json={"moves": "e4", "theme_id": theme_id})
    line_id = r.json()["id"]

    r = await client.patch(f"/lines/{line_id}", json={"theme_id": theme_id})
    assert r.status_code == 422
