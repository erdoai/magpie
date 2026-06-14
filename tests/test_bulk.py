"""Bulk rescope/retag endpoint tests (POST /api/entries/bulk).

Reuses the in-memory FakeDatabase + auth harness from test_isolation, so the
route's dry-run default, role gate (editor previews, admin applies), match
validation, scope clamp, and cross-org isolation are what's under test. The
Postgres tag-array SQL itself is exercised by the shared apply_bulk_changes
semantics, mirrored in the fake.
"""

from tests.test_isolation import FakeDatabase, add_token, auth, make_client


def _seed(db: FakeDatabase, **over) -> str:
    base = {"org_id": "org-a", "user_id": "ua", "workspace": "reach",
            "project": "alertee", "tags": ["a", "b"]}
    base.update(over)
    return db.add_entry(**base)


# -- dry-run safety --


def test_dry_run_is_default_and_mutates_nothing():
    db = FakeDatabase()
    add_token(db, "editor-key", user_id="ua", org_id="org-a", role="editor")
    eid = _seed(db, workspace="reach")
    client = make_client(db)

    res = client.post(
        "/api/entries/bulk",
        headers=auth("editor-key"),
        json={"match": {"workspace": "reach"}, "changes": {"workspace": "erdo"}},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["matched"] == 1
    assert body["applied"] is False
    assert body["updated"] == 0
    # nothing written
    assert db.entries[eid]["workspace"] == "reach"
    # sample shows the would-be change
    assert body["sample"][0]["before"]["workspace"] == "reach"
    assert body["sample"][0]["after"]["workspace"] == "erdo"


# -- role gate --


def test_editor_cannot_apply():
    db = FakeDatabase()
    add_token(db, "editor-key", user_id="ua", org_id="org-a", role="editor")
    eid = _seed(db, workspace="reach")
    client = make_client(db)

    res = client.post(
        "/api/entries/bulk",
        headers=auth("editor-key"),
        json={"match": {"workspace": "reach"}, "changes": {"workspace": "erdo"},
              "dry_run": False},
    )
    assert res.status_code == 403
    assert db.entries[eid]["workspace"] == "reach"


def test_viewer_cannot_even_preview():
    db = FakeDatabase()
    add_token(db, "viewer-key", user_id="ua", org_id="org-a", role="viewer")
    _seed(db)
    client = make_client(db)

    res = client.post(
        "/api/entries/bulk",
        headers=auth("viewer-key"),
        json={"match": {"workspace": "reach"}, "changes": {"workspace": "erdo"}},
    )
    assert res.status_code == 403


# -- apply (admin) --


def test_admin_apply_rescope_preserves_id():
    db = FakeDatabase()
    add_token(db, "admin-key", user_id="ua", org_id="org-a", role="admin")
    eid = _seed(db, workspace="reach", project="alertee")
    client = make_client(db)

    res = client.post(
        "/api/entries/bulk",
        headers=auth("admin-key"),
        json={"match": {"workspace": "reach"},
              "changes": {"workspace": "erdo", "project": "core"},
              "dry_run": False},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["applied"] is True
    assert body["updated"] == 1
    # same id, new scope — an in-place move, not a recreate
    assert eid in db.entries
    assert db.entries[eid]["workspace"] == "erdo"
    assert db.entries[eid]["project"] == "core"


def test_admin_apply_retag_add_remove_rename():
    db = FakeDatabase()
    add_token(db, "admin-key", user_id="ua", org_id="org-a", role="admin")
    eid = _seed(db, tags=["old", "keep"])
    client = make_client(db)

    res = client.post(
        "/api/entries/bulk",
        headers=auth("admin-key"),
        json={"match": {"workspace": "reach"},
              "changes": {"rename_from": "old", "rename_to": "new",
                          "remove_tags": ["keep"], "add_tags": ["fresh"]},
              "dry_run": False},
    )
    assert res.status_code == 200
    assert sorted(db.entries[eid]["tags"]) == ["fresh", "new"]


def test_retag_dedupes():
    db = FakeDatabase()
    add_token(db, "admin-key", user_id="ua", org_id="org-a", role="admin")
    eid = _seed(db, tags=["a", "b"])
    client = make_client(db)

    client.post(
        "/api/entries/bulk",
        headers=auth("admin-key"),
        json={"match": {"workspace": "reach"},
              "changes": {"add_tags": ["a", "c"]}, "dry_run": False},
    )
    assert db.entries[eid]["tags"] == ["a", "b", "c"]


def test_clear_project_nulls_it():
    db = FakeDatabase()
    add_token(db, "admin-key", user_id="ua", org_id="org-a", role="admin")
    eid = _seed(db, project="alertee")
    client = make_client(db)

    res = client.post(
        "/api/entries/bulk",
        headers=auth("admin-key"),
        json={"match": {"project": "alertee"}, "changes": {"clear": ["project"]},
              "dry_run": False},
    )
    assert res.status_code == 200
    assert db.entries[eid]["project"] is None


def test_clear_rejects_non_scope_fields():
    db = FakeDatabase()
    add_token(db, "admin-key", user_id="ua", org_id="org-a", role="admin")
    _seed(db)
    client = make_client(db)

    # clearing a non-scope field leaves changes empty → 400
    res = client.post(
        "/api/entries/bulk",
        headers=auth("admin-key"),
        json={"match": {"workspace": "reach"}, "changes": {"clear": ["content"]},
              "dry_run": False},
    )
    assert res.status_code == 400


# -- match selection --


def test_match_by_tag_selects_only_tagged():
    db = FakeDatabase()
    add_token(db, "admin-key", user_id="ua", org_id="org-a", role="admin")
    hit = _seed(db, tags=["target"])
    miss = _seed(db, tags=["other"])
    client = make_client(db)

    res = client.post(
        "/api/entries/bulk",
        headers=auth("admin-key"),
        json={"match": {"tags": ["target"]}, "changes": {"add_tags": ["done"]},
              "dry_run": False},
    )
    assert res.json()["updated"] == 1
    assert "done" in db.entries[hit]["tags"]
    assert "done" not in db.entries[miss]["tags"]


# -- validation --


def test_empty_match_rejected():
    db = FakeDatabase()
    add_token(db, "admin-key", user_id="ua", org_id="org-a", role="admin")
    client = make_client(db)
    res = client.post(
        "/api/entries/bulk",
        headers=auth("admin-key"),
        json={"match": {}, "changes": {"workspace": "erdo"}},
    )
    assert res.status_code == 400


def test_empty_changes_rejected():
    db = FakeDatabase()
    add_token(db, "admin-key", user_id="ua", org_id="org-a", role="admin")
    client = make_client(db)
    res = client.post(
        "/api/entries/bulk",
        headers=auth("admin-key"),
        json={"match": {"workspace": "reach"}, "changes": {}},
    )
    assert res.status_code == 400


# -- cross-org / global isolation --


def test_bulk_never_touches_other_org_or_global():
    db = FakeDatabase()
    add_token(db, "admin-a", user_id="ua", org_id="org-a", role="admin")
    mine = _seed(db, org_id="org-a", user_id="ua", workspace="shared")
    other = _seed(db, org_id="org-b", user_id="ub", workspace="shared")
    glob = db.add_entry(org_id=None, user_id=None, workspace="shared", tags=[])
    client = make_client(db)

    res = client.post(
        "/api/entries/bulk",
        headers=auth("admin-a"),
        json={"match": {"workspace": "shared"}, "changes": {"workspace": "moved"},
              "dry_run": False},
    )
    assert res.json()["updated"] == 1
    assert db.entries[mine]["workspace"] == "moved"
    assert db.entries[other]["workspace"] == "shared"  # other org untouched
    assert db.entries[glob]["workspace"] == "shared"  # global untouched


def test_workspace_pinned_token_clamps_match():
    db = FakeDatabase()
    add_token(db, "pinned", user_id="ua", org_id="org-a", role="admin",
              workspace="reach")
    inside = _seed(db, workspace="reach")
    outside = _seed(db, workspace="erdo")
    client = make_client(db)

    # Asks to match erdo, but the key is pinned to reach → only reach matches.
    res = client.post(
        "/api/entries/bulk",
        headers=auth("pinned"),
        json={"match": {"workspace": "erdo"}, "changes": {"add_tags": ["x"]},
              "dry_run": False},
    )
    assert res.json()["updated"] == 1
    assert "x" in db.entries[inside]["tags"]
    assert "x" not in db.entries[outside]["tags"]
