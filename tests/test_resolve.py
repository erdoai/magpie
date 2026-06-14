"""Reference resolution tests — {{...}} values, attachments, wikilinks."""

from magpie.resolve import resolve_entry
from magpie.server.context import AuthContext

from .test_isolation import FakeDatabase, FakeSettings, add_token, auth, make_client


def _ctx():
    return AuthContext(user_id="ua", org_id="org-a", role="editor")


async def _make_kv_store(db, slug, pairs, org_id="org-a"):
    store_id = await db.create_kv_store(slug=slug, title=slug, org_id=org_id)
    for key, value in pairs.items():
        await db.set_kv_pair(store_id, key, value, org_id=org_id)
    return store_id


async def test_shorthand_kv_reference():
    db = FakeDatabase()
    await _make_kv_store(db, "reach.strategy", {
        "alertee": {"positioning": {"wedge": "fast alerts"}},
    })
    entry_id = db.add_entry(
        org_id="org-a",
        content="Our wedge: {{reach.strategy.alertee.positioning.wedge}}",
    )

    result = await resolve_entry(db, db.entries[entry_id], _ctx(), FakeSettings())
    assert result["markdown"] == "Our wedge: fast alerts"
    (dep,) = result["dependencies"]
    assert dep["status"] == "resolved"
    assert dep["kind"] == "kv"


async def test_explicit_kv_reference_and_scalars():
    db = FakeDatabase()
    await _make_kv_store(db, "metrics", {"mrr": 4200.5, "config": {"a": [1, 2, 3]}})
    entry_id = db.add_entry(
        org_id="org-a",
        content="MRR is {{kv:metrics/mrr}} and a[1] is {{metrics.config.a.1}}",
    )

    result = await resolve_entry(db, db.entries[entry_id], _ctx(), FakeSettings())
    assert result["markdown"] == "MRR is 4200.5 and a[1] is 2"


async def test_object_values_render_as_json_blocks():
    db = FakeDatabase()
    await _make_kv_store(db, "brand", {"tokens": {"primary": "#fff"}})
    entry_id = db.add_entry(org_id="org-a", content="Tokens: {{brand.tokens}}")

    result = await resolve_entry(db, db.entries[entry_id], _ctx(), FakeSettings())
    assert "```json" in result["markdown"]
    assert '"primary": "#fff"' in result["markdown"]


async def test_unresolved_and_unauthorized_references():
    db = FakeDatabase()
    await _make_kv_store(db, "b.secrets", {"k": "hidden"}, org_id="org-b")
    entry_id = db.add_entry(
        org_id="org-a",
        content="Missing {{nope.key}} and foreign {{b.secrets.k}}",
    )

    result = await resolve_entry(db, db.entries[entry_id], _ctx(), FakeSettings())
    assert "⟦unresolved: nope.key⟧" in result["markdown"]
    assert "⟦unresolved: b.secrets.k⟧" in result["markdown"]
    assert "hidden" not in result["markdown"]
    statuses = {d["ref"]: d["status"] for d in result["dependencies"]}
    assert statuses["nope.key"] == "not_found"
    assert statuses["b.secrets.k"] == "not_found"


async def test_attachment_reference():
    db = FakeDatabase()
    entry_id = db.add_entry(org_id="org-a", content="Logo: {{attachment:logo-primary}}")
    await db.create_attachment(
        entry_id=entry_id, kind="image", filename="logo.png",
        media_type="image/png", storage_key="k", byte_size=3,
        org_id="org-a", role="logo-primary", public=True,
    )

    result = await resolve_entry(db, db.entries[entry_id], _ctx(), FakeSettings())
    att_id = next(iter(db.attachments))
    assert f"![logo.png](/public/assets/{att_id})" in result["markdown"]


async def test_wikilinks_resolve_to_markdown_links():
    db = FakeDatabase()
    target = db.add_entry(org_id="org-a", title="Positioning")
    entry_id = db.add_entry(org_id="org-a", content="See [[Positioning|the doc]].")
    await db.replace_entry_links(entry_id, "org-a", [{
        "target_type": "entry", "target_id": target, "target_ref": None,
        "link_text": "the doc", "normalized_target": "positioning",
    }])

    result = await resolve_entry(db, db.entries[entry_id], _ctx(), FakeSettings())
    assert result["markdown"] == f"See [the doc](/entries/{target})."


async def test_code_blocks_are_not_resolved():
    db = FakeDatabase()
    await _make_kv_store(db, "metrics", {"mrr": 1})
    entry_id = db.add_entry(
        org_id="org-a",
        content="Real: {{metrics.mrr}}\n```\nNot real: {{metrics.mrr}}\n```",
    )

    result = await resolve_entry(db, db.entries[entry_id], _ctx(), FakeSettings())
    assert "Real: 1" in result["markdown"]
    assert "Not real: {{metrics.mrr}}" in result["markdown"]


# -- REST endpoint --


def test_resolve_endpoint():
    db = FakeDatabase()
    add_token(db, "key-a", user_id="ua", org_id="org-a")
    client = make_client(db)

    client.post(
        "/api/kv", headers=auth("key-a"),
        json={"slug": "metrics", "title": "Metrics"},
    )
    client.put(
        "/api/kv/metrics/keys/mrr",
        headers=auth("key-a"), json={"value": 42, "value_type": "integer"},
    )
    res = client.post(
        "/api/entries", headers=auth("key-a"),
        json={"title": "Report", "content": "MRR: {{metrics.mrr}}"},
    )
    entry_id = res.json()["id"]

    res = client.post(f"/api/entries/{entry_id}/resolve", headers=auth("key-a"))
    assert res.status_code == 200
    body = res.json()
    assert body["markdown"] == "MRR: 42"
    assert body["dependencies"][0]["status"] == "resolved"


def test_resolve_endpoint_visibility():
    db = FakeDatabase()
    add_token(db, "key-a", user_id="ua", org_id="org-a")
    other = db.add_entry(org_id="org-b", content="x")
    client = make_client(db)

    assert client.post(
        f"/api/entries/{other}/resolve", headers=auth("key-a")
    ).status_code == 404
