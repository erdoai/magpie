"""Activity log tests: write paths emit events, and /api/updates reads from the
durable log (surviving overwrites and deletes) with org-scoped visibility.

Uses the in-memory FakeDatabase from test_isolation against the real routers, so
the emission wiring (not Postgres) is what's under test.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magpie.db.database import changed_material_fields
from magpie.kv import kv_value_changed
from magpie.server.auth import AuthMiddleware
from magpie.server.routes import entries, kv, updates

from .test_isolation import FakeDatabase, FakeSettings, add_token, auth


def make_client(db: FakeDatabase) -> TestClient:
    app = FastAPI()
    app.include_router(entries.router)
    app.include_router(kv.router)
    app.include_router(updates.router)
    app.add_middleware(AuthMiddleware)
    app.state.settings = FakeSettings()
    app.state.db = db
    app.state.embedder = None
    app.state.storage = None
    return TestClient(app)


def _setup():
    db = FakeDatabase()
    db.org_roles[("org1", "user1")] = "editor"
    add_token(db, "tok-editor", user_id="user1", org_id="org1", role="editor")
    return db, make_client(db)


def test_create_archive_delete_emit_events():
    db, client = _setup()
    r = client.post(
        "/api/entries",
        json={"title": "First", "content": "body", "workspace": "ws"},
        headers=auth("tok-editor"),
    )
    eid = r.json()["id"]
    client.post(f"/api/entries/{eid}/archive", headers=auth("tok-editor"))
    client.delete(f"/api/entries/{eid}", headers=auth("tok-editor"))

    actions = [e["action"] for e in db.activity_events]
    assert actions == ["entry.created", "entry.archived", "entry.deleted"]
    # Actor is recorded from the token context.
    assert all(e["actor_type"] == "token" for e in db.activity_events)
    assert all(e["actor_user_id"] == "user1" for e in db.activity_events)


def test_repeated_updates_stay_distinct_and_feed_survives_delete():
    db, client = _setup()
    r = client.post(
        "/api/entries",
        json={"title": "Note", "content": "v1", "workspace": "ws"},
        headers=auth("tok-editor"),
    )
    eid = r.json()["id"]
    client.put(f"/api/entries/{eid}", json={"content": "v2"}, headers=auth("tok-editor"))
    client.put(f"/api/entries/{eid}", json={"content": "v3"}, headers=auth("tok-editor"))
    client.delete(f"/api/entries/{eid}", headers=auth("tok-editor"))

    feed = client.get("/api/updates", headers=auth("tok-editor")).json()
    actions = [item["action"] for item in feed]
    # Newest first: two updates do NOT collapse, and the delete still shows
    # even though the row is gone.
    assert actions == ["deleted", "updated", "updated", "created"]
    upd = next(i for i in feed if i["action"] == "updated")
    assert upd["metadata"]["changed"] == ["content"]
    assert upd["kind"] == "entry"


def test_kv_set_records_created_then_updated():
    db, client = _setup()
    client.post(
        "/api/kv",
        json={"slug": "cfg", "title": "Config", "workspace": "ws"},
        headers=auth("tok-editor"),
    )
    client.put("/api/kv/cfg/keys/trial_days", json={"value": 14, "value_type": "integer"},
               headers=auth("tok-editor"))
    client.put("/api/kv/cfg/keys/trial_days", json={"value": 30, "value_type": "integer"},
               headers=auth("tok-editor"))

    sets = [e for e in db.activity_events if e["action"] == "kv_pair.set"]
    assert [e["metadata_json"]["created"] for e in sets] == [True, False]
    assert sets[0]["subject_title"] == "cfg/trial_days"


def test_update_snapshots_previous_content_newest_first():
    db, client = _setup()
    eid = client.post(
        "/api/entries",
        json={"title": "Doc", "content": "v1", "workspace": "ws"},
        headers=auth("tok-editor"),
    ).json()["id"]
    client.put(f"/api/entries/{eid}", json={"content": "v2"}, headers=auth("tok-editor"))
    client.put(f"/api/entries/{eid}", json={"content": "v3"}, headers=auth("tok-editor"))

    history = client.get(f"/api/entries/{eid}/history", headers=auth("tok-editor")).json()
    # Two edits → two revisions, newest first; each holds the PRE-edit content.
    assert [r["previous_content"] for r in history] == ["v2", "v1"]
    assert all(r["actor_type"] == "token" for r in history)


def test_scope_or_noop_change_creates_no_revision():
    db, client = _setup()
    eid = client.post(
        "/api/entries",
        json={"title": "Doc", "content": "body", "workspace": "ws"},
        headers=auth("tok-editor"),
    ).json()["id"]
    # Scope-only move — no material field changes.
    client.put(f"/api/entries/{eid}", json={"workspace": "ws2"}, headers=auth("tok-editor"))
    # Re-set identical content — not a change.
    client.put(f"/api/entries/{eid}", json={"content": "body"}, headers=auth("tok-editor"))

    assert db.entry_revisions == []


def test_history_endpoint_gated_across_orgs():
    db, client = _setup()
    db.org_roles[("org2", "user2")] = "editor"
    add_token(db, "tok-other", user_id="user2", org_id="org2", role="editor")
    eid = client.post(
        "/api/entries",
        json={"title": "Mine", "content": "x", "workspace": "ws"},
        headers=auth("tok-editor"),
    ).json()["id"]

    r = client.get(f"/api/entries/{eid}/history", headers=auth("tok-other"))
    assert r.status_code == 404


def test_kv_set_snapshots_previous_value_on_change():
    db, client = _setup()
    client.post(
        "/api/kv",
        json={"slug": "cfg", "title": "Config", "workspace": "ws"},
        headers=auth("tok-editor"),
    )
    client.put("/api/kv/cfg/keys/trial", json={"value": 14, "value_type": "integer"},
               headers=auth("tok-editor"))
    # First set is a create — no revision.
    assert db.kv_revisions == []
    client.put("/api/kv/cfg/keys/trial", json={"value": 30, "value_type": "integer"},
               headers=auth("tok-editor"))
    # Re-set identical value — not a change, no new revision.
    client.put("/api/kv/cfg/keys/trial", json={"value": 30, "value_type": "integer"},
               headers=auth("tok-editor"))

    history = client.get("/api/kv/cfg/keys/trial/history", headers=auth("tok-editor")).json()
    assert [r["previous_value"] for r in history] == [14]
    assert history[0]["actor_type"] == "token"


def test_changed_material_fields_helper():
    prev = {"title": "T", "content": "C", "tags": ["a"], "source": "s", "workspace": "w"}
    # Only material fields present in `new` and actually different count.
    assert changed_material_fields(prev, {"content": "C2"}) == ["content"]
    assert changed_material_fields(prev, {"content": "C"}) == []
    assert changed_material_fields(prev, {"workspace": "w2"}) == []  # scope not material
    assert changed_material_fields(prev, {"tags": ["a", "b"]}) == ["tags"]


def test_kv_value_changed_helper():
    prev = {"value": 1, "value_type": "integer", "summary": "old"}
    assert kv_value_changed(None, 1, "integer", None) is False          # new key
    assert kv_value_changed(prev, 1, "integer", None) is False          # unchanged
    assert kv_value_changed(prev, 2, "integer", None) is True           # value
    assert kv_value_changed(prev, 1, "string", None) is True            # type
    assert kv_value_changed(prev, 1, "integer", "new") is True          # summary
    assert kv_value_changed(prev, 1, "integer", "old") is False         # same summary


def test_updates_visibility_hides_other_orgs():
    db, client = _setup()
    # A second org with its own editor.
    db.org_roles[("org2", "user2")] = "editor"
    add_token(db, "tok-other", user_id="user2", org_id="org2", role="editor")

    client.post("/api/entries", json={"title": "Mine", "content": "x", "workspace": "ws"},
                headers=auth("tok-editor"))
    client.post("/api/entries", json={"title": "Theirs", "content": "y", "workspace": "ws"},
                headers=auth("tok-other"))

    mine = client.get("/api/updates", headers=auth("tok-editor")).json()
    titles = {i["title"] for i in mine}
    assert "Mine" in titles
    assert "Theirs" not in titles
