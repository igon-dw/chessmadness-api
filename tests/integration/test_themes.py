"""Integration tests for the /themes endpoints."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_create_and_get_theme(client):
    # Create a root theme
    r = await client.post("/themes", json={"name": "Openings"})
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == "Openings"
    assert data["parent_id"] is None
    theme_id = data["id"]

    # Fetch it back
    r2 = await client.get(f"/themes/{theme_id}")
    assert r2.status_code == 200
    assert r2.json()["name"] == "Openings"


@pytest.mark.asyncio
async def test_list_themes_tree(client):
    # Build a small hierarchy
    r1 = await client.post("/themes", json={"name": "Openings"})
    root_id = r1.json()["id"]
    await client.post("/themes", json={"name": "King's Pawn", "parent_id": root_id})
    await client.post("/themes", json={"name": "Queen's Pawn", "parent_id": root_id})

    r = await client.get("/themes")
    assert r.status_code == 200
    tree = r.json()
    assert len(tree) == 1  # one root
    assert tree[0]["name"] == "Openings"
    assert len(tree[0]["children"]) == 2


@pytest.mark.asyncio
async def test_create_theme_invalid_parent(client):
    r = await client.post("/themes", json={"name": "Orphan", "parent_id": 9999})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_update_theme(client):
    r = await client.post("/themes", json={"name": "Old Name"})
    tid = r.json()["id"]

    r2 = await client.patch(f"/themes/{tid}", json={"name": "New Name"})
    assert r2.status_code == 200
    assert r2.json()["name"] == "New Name"


@pytest.mark.asyncio
async def test_delete_theme_cascades(client):
    r1 = await client.post("/themes", json={"name": "Parent"})
    pid = r1.json()["id"]
    r2 = await client.post("/themes", json={"name": "Child", "parent_id": pid})
    cid = r2.json()["id"]

    await client.delete(f"/themes/{pid}")

    # Both parent and child should be gone
    assert (await client.get(f"/themes/{pid}")).status_code == 404
    assert (await client.get(f"/themes/{cid}")).status_code == 404


@pytest.mark.asyncio
async def test_get_subtree(client):
    r = await client.post("/themes", json={"name": "Root"})
    root_id = r.json()["id"]
    r2 = await client.post("/themes", json={"name": "Child", "parent_id": root_id})
    child_id = r2.json()["id"]
    await client.post("/themes", json={"name": "Grandchild", "parent_id": child_id})

    r3 = await client.get(f"/themes/{root_id}/subtree")
    assert r3.status_code == 200
    subtree = r3.json()
    # Root node at top level
    assert subtree[0]["name"] == "Root"
    assert subtree[0]["children"][0]["name"] == "Child"
    assert subtree[0]["children"][0]["children"][0]["name"] == "Grandchild"
