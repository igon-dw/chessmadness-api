"""Integration tests for the /skills endpoints."""

from __future__ import annotations

from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_theme(client: Any, name: str = "Test Theme") -> int:
    r = await client.post("/themes", json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]  # type: ignore[no-any-return]


async def _make_line(
    client: Any,
    theme_id: int,
    moves: str = "e4 e5",
    start_fen: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"moves": moves, "theme_id": theme_id}
    if start_fen is not None:
        payload["start_fen"] = start_fen
    r = await client.post("/lines", json=payload)
    assert r.status_code == 201
    return r.json()  # type: ignore[no-any-return]


async def _make_skill_block(
    client: Any,
    line_id: int,
    name: str = "Test Block",
    tags: list[str] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"line_id": line_id, "name": name, "tags": tags or []}
    if description is not None:
        payload["description"] = description
    r = await client.post("/skills", json=payload)
    assert r.status_code == 201
    return r.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# POST /skills
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_skill_block(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    block = await _make_skill_block(client, line["id"], name="My Opening")

    assert block["id"] is not None
    assert block["name"] == "My Opening"
    assert block["line_id"] == line["id"]
    assert block["source_type"] == "original"
    assert block["mastery"] is not None
    assert block["mastery"]["xp"] == 0


@pytest.mark.asyncio
async def test_create_skill_block_unknown_line(client):
    r = await client.post("/skills", json={"line_id": 9999, "name": "Ghost"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_create_skill_block_duplicate_line_id_returns_409(client):
    """Creating a second skill block for the same line returns 409."""
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    await _make_skill_block(client, line["id"], name="First")

    r = await client.post("/skills", json={"line_id": line["id"], "name": "Duplicate"})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_create_skill_block_with_tags(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    r = await client.post(
        "/skills",
        json={"line_id": line["id"], "name": "Tagged", "tags": ["e4", "open"]},
    )
    assert r.status_code == 201
    assert "e4" in r.json()["tags"]


# ---------------------------------------------------------------------------
# GET /skills/{block_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_skill_block(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    created = await _make_skill_block(client, line["id"], name="Fetch me")

    r = await client.get(f"/skills/{created['id']}")
    assert r.status_code == 200
    assert r.json()["name"] == "Fetch me"


@pytest.mark.asyncio
async def test_get_skill_block_not_found(client):
    r = await client.get("/skills/99999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /skills/{block_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_skill_block_name(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    block = await _make_skill_block(client, line["id"], name="Old")

    r = await client.patch(f"/skills/{block['id']}", json={"name": "New"})
    assert r.status_code == 200
    assert r.json()["name"] == "New"


@pytest.mark.asyncio
async def test_patch_skill_block_tags(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    block = await _make_skill_block(client, line["id"])

    r = await client.patch(
        f"/skills/{block['id']}", json={"tags": ["sicilian", "sharp"]}
    )
    assert r.status_code == 200
    assert "sicilian" in r.json()["tags"]


@pytest.mark.asyncio
async def test_patch_skill_block_signature_title(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    block = await _make_skill_block(client, line["id"])

    r = await client.patch(
        f"/skills/{block['id']}", json={"signature_title": "The Immortal"}
    )
    assert r.status_code == 200
    assert r.json()["mastery"]["signature_title"] == "The Immortal"


@pytest.mark.asyncio
async def test_patch_skill_block_not_found(client):
    r = await client.patch("/skills/99999", json={"name": "Ghost"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /skills/{block_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_skill_block(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    block = await _make_skill_block(client, line["id"])

    r = await client.delete(f"/skills/{block['id']}")
    assert r.status_code == 204

    r = await client.get(f"/skills/{block['id']}")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_skill_block_not_found(client):
    r = await client.delete("/skills/99999")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# GET /skills/tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tree_empty(client):
    r = await client.get("/skills/tree")
    assert r.status_code == 200
    data = r.json()
    assert data["nodes"] == []
    assert data["edges"] == []


@pytest.mark.asyncio
async def test_get_tree_with_blocks(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    await _make_skill_block(client, line["id"], name="Alpha")

    r = await client.get("/skills/tree")
    assert r.status_code == 200
    data = r.json()
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["name"] == "Alpha"


# ---------------------------------------------------------------------------
# Auto-link: two chained blocks → edge appears in tree
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_link_appears_in_tree(client):
    """Creating two chained blocks creates an edge in /skills/tree."""
    theme_id = await _make_theme(client)

    # Parent: e2e4 (standard start)
    parent_line = await _make_line(client, theme_id, moves="e4")
    parent_block = await _make_skill_block(client, parent_line["id"], name="Parent")

    # Get the final_fen of the parent line (after e4)
    # Fetch the line's final_fen from /lines
    lines_r = await client.get(f"/lines/{parent_line['id']}")
    parent_final_fen = lines_r.json()["final_fen"]

    # Child: starts from parent's final_fen, plays e7e5
    child_line = await _make_line(
        client, theme_id, moves="e5", start_fen=parent_final_fen
    )
    child_block = await _make_skill_block(client, child_line["id"], name="Child")

    tree = (await client.get("/skills/tree")).json()
    assert len(tree["nodes"]) == 2
    assert len(tree["edges"]) == 1
    edge = tree["edges"][0]
    assert edge["parent_block_id"] == parent_block["id"]
    assert edge["child_block_id"] == child_block["id"]


# ---------------------------------------------------------------------------
# GET /skills/{block_id}/children and /ancestors
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_children_empty(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    block = await _make_skill_block(client, line["id"])

    r = await client.get(f"/skills/{block['id']}/children")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_ancestors_empty(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    block = await _make_skill_block(client, line["id"])

    r = await client.get(f"/skills/{block['id']}/ancestors")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_get_children_returns_linked_child(client):
    theme_id = await _make_theme(client)

    parent_line = await _make_line(client, theme_id, moves="e4")
    parent_block = await _make_skill_block(client, parent_line["id"], name="Parent")

    lines_r = await client.get(f"/lines/{parent_line['id']}")
    parent_final_fen = lines_r.json()["final_fen"]

    child_line = await _make_line(
        client, theme_id, moves="e5", start_fen=parent_final_fen
    )
    child_block = await _make_skill_block(client, child_line["id"], name="Child")

    r = await client.get(f"/skills/{parent_block['id']}/children")
    assert r.status_code == 200
    ids = [b["id"] for b in r.json()]
    assert child_block["id"] in ids


@pytest.mark.asyncio
async def test_get_ancestors_returns_parent(client):
    theme_id = await _make_theme(client)

    parent_line = await _make_line(client, theme_id, moves="e4")
    parent_block = await _make_skill_block(client, parent_line["id"], name="Parent")

    lines_r = await client.get(f"/lines/{parent_line['id']}")
    parent_final_fen = lines_r.json()["final_fen"]

    child_line = await _make_line(
        client, theme_id, moves="e5", start_fen=parent_final_fen
    )
    child_block = await _make_skill_block(client, child_line["id"], name="Child")

    r = await client.get(f"/skills/{child_block['id']}/ancestors")
    assert r.status_code == 200
    ids = [b["id"] for b in r.json()]
    assert parent_block["id"] in ids


# ---------------------------------------------------------------------------
# GET /skills/rusty and /skills/critical
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rusty_includes_new_block(client):
    """A newly created block (never practiced) appears in /skills/rusty."""
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    block = await _make_skill_block(client, line["id"])

    r = await client.get("/skills/rusty")
    assert r.status_code == 200
    ids = [b["id"] for b in r.json()]
    assert block["id"] in ids


@pytest.mark.asyncio
async def test_critical_empty_initially(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    await _make_skill_block(client, line["id"])

    r = await client.get("/skills/critical")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# GET /skills/signatures
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_signatures_empty_initially(client):
    r = await client.get("/skills/signatures")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# GET /skills/search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_by_name(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    await _make_skill_block(client, line["id"], name="Sicilian Dragon")

    r = await client.get("/skills/search?name=Dragon")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["name"] == "Sicilian Dragon"


@pytest.mark.asyncio
async def test_search_by_tag(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    await _make_skill_block(client, line["id"], name="Tagged", tags=["dragon"])

    r = await client.get("/skills/search?tag=dragon")
    assert r.status_code == 200
    assert len(r.json()) == 1


@pytest.mark.asyncio
async def test_search_no_results(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    await _make_skill_block(client, line["id"], name="Something")

    r = await client.get("/skills/search?name=nonexistent_xyz")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_search_by_fen(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="e4")
    await _make_skill_block(client, line["id"], name="After e4")

    # The standard starting FEN should match this block (it starts there)
    start_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
    r = await client.get(f"/skills/search?fen={start_fen}")
    assert r.status_code == 200
    assert len(r.json()) >= 1


# ---------------------------------------------------------------------------
# GET /skills/mastery/dashboard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mastery_dashboard_empty(client):
    """Dashboard returns zeroes when no skill blocks exist."""
    r = await client.get("/skills/mastery/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert data["total_blocks"] == 0
    assert data["total_xp"] == 0
    assert data["signature_count"] == 0
    assert data["top_signatures"] == []
    rust = data["rust_distribution"]
    assert rust["fresh"] == 0
    assert rust["rusty"] == 0


@pytest.mark.asyncio
async def test_mastery_dashboard_with_blocks(client):
    """Dashboard aggregates stats across all skill blocks."""
    theme_id = await _make_theme(client)
    line1 = await _make_line(client, theme_id, moves="e4 e5")
    line2 = await _make_line(client, theme_id, moves="d4 d5")
    await _make_skill_block(client, line1["id"], name="Block A")
    await _make_skill_block(client, line2["id"], name="Block B")

    r = await client.get("/skills/mastery/dashboard")
    assert r.status_code == 200
    data = r.json()
    assert data["total_blocks"] == 2
    assert data["total_xp"] == 0  # no reviews yet
    assert isinstance(data["level_distribution"], dict)
    rust = data["rust_distribution"]
    assert rust["fresh"] + rust["aging"] + rust["rusty"] + rust["critical"] == 2
