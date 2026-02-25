"""
Integration tests for the skill share, import, preview, and fork endpoints.

Endpoints tested:
  POST /skills/share?block_id={id}
  POST /skills/import-code
  GET  /skills/preview/{code}
  POST /skills/{id}/fork
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.skill_share import encode_share_payload

STANDARD_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_theme(client: Any, name: str = "Theme") -> int:
    r = await client.post("/themes", json={"name": name})
    assert r.status_code == 201
    return r.json()["id"]


async def _make_line(
    client: Any, theme_id: int, moves: str = "e2e4 e7e5"
) -> dict[str, Any]:
    r = await client.post("/lines", json={"moves": moves, "theme_id": theme_id})
    assert r.status_code == 201
    return r.json()


async def _make_block(
    client: Any, line_id: int, name: str = "Test Block"
) -> dict[str, Any]:
    r = await client.post("/skills", json={"line_id": line_id, "name": name})
    assert r.status_code == 201
    return r.json()


# ---------------------------------------------------------------------------
# POST /skills/share
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_share_returns_code(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    block = await _make_block(client, line["id"])

    r = await client.post(f"/skills/share?block_id={block['id']}")
    assert r.status_code == 200
    data = r.json()
    assert "share_code" in data
    assert data["share_code"].startswith("chessmadness:")


@pytest.mark.asyncio
async def test_share_unknown_block_404(client):
    r = await client.post("/skills/share?block_id=9999")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_share_persists_code_on_block(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id)
    block = await _make_block(client, line["id"])
    block_id = block["id"]

    r = await client.post(f"/skills/share?block_id={block_id}")
    code = r.json()["share_code"]

    r2 = await client.get(f"/skills/{block_id}")
    assert r2.json()["share_code"] == code


@pytest.mark.asyncio
async def test_share_code_encodes_moves(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="d4 d5")
    block = await _make_block(client, line["id"])

    r = await client.post(f"/skills/share?block_id={block['id']}")
    from app.services.skill_share import decode_share_code

    payload = decode_share_code(r.json()["share_code"])
    assert payload["moves"] == "d4 d5"


# ---------------------------------------------------------------------------
# GET /skills/preview/{code}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_returns_fields(client):
    code = encode_share_payload(
        name="Preview Block",
        start_fen=STANDARD_FEN,
        moves="e2e4",
        tags=["test"],
        description="A preview",
    )
    r = await client.get(f"/skills/preview/{code}")
    assert r.status_code == 200
    data = r.json()
    assert data["name"] == "Preview Block"
    assert data["moves"] == "e2e4"
    assert data["tags"] == ["test"]
    assert data["description"] == "A preview"


@pytest.mark.asyncio
async def test_preview_no_db_change(client):
    """Preview should not create any blocks or lines."""
    code = encode_share_payload(
        name="No Persist",
        start_fen=STANDARD_FEN,
        moves="e2e4",
        tags=[],
        description=None,
    )
    r = await client.get(f"/skills/preview/{code}")
    assert r.status_code == 200

    # No blocks should exist
    r2 = await client.get("/skills/tree")
    assert r2.json()["nodes"] == []


@pytest.mark.asyncio
async def test_preview_invalid_code_422(client):
    r = await client.get("/skills/preview/notvalid:xxxx")
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# POST /skills/import-code
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_creates_block(client):
    code = encode_share_payload(
        name="Imported",
        start_fen=STANDARD_FEN,
        moves="e2e4 e7e5",
        tags=["import"],
        description="desc",
    )
    r = await client.post("/skills/import-code", json={"share_code": code})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Imported"
    assert data["source_type"] == "imported"
    assert data["share_code"] == code


@pytest.mark.asyncio
async def test_import_with_name_override(client):
    code = encode_share_payload(
        name="Original",
        start_fen=STANDARD_FEN,
        moves="d2d4",
        tags=[],
        description=None,
    )
    r = await client.post(
        "/skills/import-code", json={"share_code": code, "name": "Custom Name"}
    )
    assert r.status_code == 201
    assert r.json()["name"] == "Custom Name"


@pytest.mark.asyncio
async def test_import_invalid_code_422(client):
    r = await client.post("/skills/import-code", json={"share_code": "notvalid:xxx"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_import_illegal_moves_422(client):
    code = encode_share_payload(
        name="Bad",
        start_fen=STANDARD_FEN,
        moves="e7e5",  # illegal from white's starting position
        tags=[],
        description=None,
    )
    r = await client.post("/skills/import-code", json={"share_code": code})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_import_block_visible_in_tree(client):
    code = encode_share_payload(
        name="Tree Block",
        start_fen=STANDARD_FEN,
        moves="e2e4",
        tags=[],
        description=None,
    )
    r = await client.post("/skills/import-code", json={"share_code": code})
    block_id = r.json()["id"]

    r2 = await client.get("/skills/tree")
    node_ids = [n["id"] for n in r2.json()["nodes"]]
    assert block_id in node_ids


@pytest.mark.asyncio
async def test_import_mastery_initialised(client):
    code = encode_share_payload(
        name="Mastery Init",
        start_fen=STANDARD_FEN,
        moves="e2e4",
        tags=[],
        description=None,
    )
    r = await client.post("/skills/import-code", json={"share_code": code})
    mastery = r.json()["mastery"]
    assert mastery is not None
    assert mastery["xp"] == 0


# ---------------------------------------------------------------------------
# POST /skills/{id}/fork
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fork_returns_201(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="e2e4")
    block = await _make_block(client, line["id"])

    r = await client.post(
        f"/skills/{block['id']}/fork",
        json={"additional_moves": "e7e5", "name": "Fork"},
    )
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_fork_response_fields(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="e2e4")
    block = await _make_block(client, line["id"])
    parent_id = block["id"]

    r = await client.post(
        f"/skills/{parent_id}/fork",
        json={"additional_moves": "e7e5", "name": "My Fork"},
    )
    data = r.json()
    assert data["name"] == "My Fork"
    assert data["source_type"] == "forked"
    assert data["forked_from_id"] == parent_id


@pytest.mark.asyncio
async def test_fork_unknown_parent_404(client):
    r = await client.post(
        "/skills/9999/fork",
        json={"additional_moves": "e7e5", "name": "Fork"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_fork_illegal_moves_422(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="e2e4")
    block = await _make_block(client, line["id"])

    r = await client.post(
        f"/skills/{block['id']}/fork",
        json={"additional_moves": "e2e4", "name": "Fork"},  # illegal after 1.e4
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_fork_appears_as_child(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="e2e4")
    block = await _make_block(client, line["id"])
    parent_id = block["id"]

    r = await client.post(
        f"/skills/{parent_id}/fork",
        json={"additional_moves": "e7e5", "name": "Fork"},
    )
    fork_id = r.json()["id"]

    r2 = await client.get(f"/skills/{parent_id}/children")
    child_ids = [c["id"] for c in r2.json()]
    assert fork_id in child_ids


@pytest.mark.asyncio
async def test_fork_link_is_manual(client):
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="e2e4")
    block = await _make_block(client, line["id"])
    parent_id = block["id"]

    fork_r = await client.post(
        f"/skills/{parent_id}/fork",
        json={"additional_moves": "e7e5", "name": "Fork"},
    )
    fork_id = fork_r.json()["id"]

    r = await client.get("/skills/tree")
    edges = r.json()["edges"]
    matching = [
        e
        for e in edges
        if e["parent_block_id"] == parent_id and e["child_block_id"] == fork_id
    ]
    assert len(matching) == 1
    assert matching[0]["link_type"] == "manual"


@pytest.mark.asyncio
async def test_fork_chain(client):
    """Fork can be forked again to build a chain."""
    theme_id = await _make_theme(client)
    line = await _make_line(client, theme_id, moves="e2e4")
    block = await _make_block(client, line["id"])

    r1 = await client.post(
        f"/skills/{block['id']}/fork",
        json={"additional_moves": "e7e5", "name": "Fork 1"},
    )
    fork1_id = r1.json()["id"]

    r2 = await client.post(
        f"/skills/{fork1_id}/fork",
        json={"additional_moves": "g1f3", "name": "Fork 2"},
    )
    assert r2.status_code == 201
    fork2 = r2.json()
    assert fork2["forked_from_id"] == fork1_id
