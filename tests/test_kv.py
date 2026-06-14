"""KV store/pair CRUD, typed value validation, and isolation tests."""

from magpie.kv import validate_value

from .test_isolation import FakeDatabase, add_key, auth, make_client

# -- Typed value validation --


def test_validate_value_accepts_matching_types():
    assert validate_value({"a": 1}, "json") is None
    assert validate_value([1, 2], "json") is None
    assert validate_value("hi", "string") is None
    assert validate_value(42, "integer") is None
    assert validate_value(4.2, "float") is None
    assert validate_value(42, "float") is None  # ints are valid floats
    assert validate_value(True, "boolean") is None
    assert validate_value("2026-06-12T10:00:00Z", "datetime") is None
    assert validate_value("2026-06-12", "datetime") is None


def test_validate_value_rejects_mismatches():
    assert validate_value(42, "string") is not None
    assert validate_value("42", "integer") is not None
    assert validate_value(True, "integer") is not None  # bool is not an int here
    assert validate_value(True, "float") is not None
    assert validate_value("yes", "boolean") is not None
    assert validate_value("not a date", "datetime") is not None
    assert validate_value(1718000000, "datetime") is not None
    assert validate_value({}, "nope") is not None


# -- REST CRUD --


def _setup():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    return db, make_client(db)


def test_store_and_pair_roundtrip():
    db, client = _setup()

    res = client.post(
        "/api/kv",
        headers=auth("key-a"),
        json={"slug": "reach.strategy", "title": "Reach strategy",
              "workspace": "reach", "project": "alertee"},
    )
    assert res.status_code == 200
    assert res.json()["org_id"] == "org-a"

    res = client.put(
        "/api/kv/reach.strategy/keys/current",
        headers=auth("key-a"),
        json={"value": {"wedge": "fast alerts"}, "value_type": "json",
              "summary": "current strategy"},
    )
    assert res.status_code == 200
    pair = res.json()
    assert pair["value"] == {"wedge": "fast alerts"}
    assert pair["value_type"] == "json"

    res = client.get(
        "/api/kv/reach.strategy/keys/current", headers=auth("key-a")
    )
    assert res.json()["value"] == {"wedge": "fast alerts"}

    res = client.get(
        "/api/kv/reach.strategy/keys", headers=auth("key-a")
    )
    assert len(res.json()["pairs"]) == 1

    res = client.delete(
        "/api/kv/reach.strategy/keys/current", headers=auth("key-a")
    )
    assert res.json() == {"ok": True}


def test_typed_scalar_pairs():
    db, client = _setup()
    client.post(
        "/api/kv", headers=auth("key-a"),
        json={"slug": "metrics", "title": "Metrics"},
    )

    for key, value, value_type in [
        ("mrr", 4200.5, "float"),
        ("customers", 17, "integer"),
        ("active", True, "boolean"),
        ("name", "alertee", "string"),
        ("launched_at", "2026-01-15T09:00:00Z", "datetime"),
    ]:
        res = client.put(
            f"/api/kv/metrics/keys/{key}",
            headers=auth("key-a"),
            json={"value": value, "value_type": value_type},
        )
        assert res.status_code == 200, res.text
        pair = res.json()
        assert pair["value"] == value
        assert pair["value_type"] == value_type


def test_type_mismatch_rejected():
    db, client = _setup()
    client.post(
        "/api/kv", headers=auth("key-a"),
        json={"slug": "metrics", "title": "Metrics"},
    )

    res = client.put(
        "/api/kv/metrics/keys/mrr",
        headers=auth("key-a"),
        json={"value": "lots", "value_type": "float"},
    )
    assert res.status_code == 400
    assert "float" in res.json()["error"]

    res = client.put(
        "/api/kv/metrics/keys/x",
        headers=auth("key-a"),
        json={"value": 1, "value_type": "money"},
    )
    assert res.status_code == 400


def test_invalid_slug_rejected():
    db, client = _setup()
    res = client.post(
        "/api/kv", headers=auth("key-a"),
        json={"slug": "Bad Slug!", "title": "x"},
    )
    assert res.status_code == 400


def test_duplicate_slug_rejected():
    db, client = _setup()
    body = {"slug": "reach.strategy", "title": "x"}
    assert client.post("/api/kv", headers=auth("key-a"), json=body).status_code == 200
    assert client.post("/api/kv", headers=auth("key-a"), json=body).status_code == 409


# -- Roles and isolation --


def test_viewer_cannot_write_pairs():
    db = FakeDatabase()
    add_key(db, "viewer-key", user_id="ua", org_id="org-a", role="viewer")
    add_key(db, "editor-key", user_id="ub", org_id="org-a", role="editor")
    client = make_client(db)

    client.post(
        "/api/kv", headers=auth("editor-key"),
        json={"slug": "c", "title": "C"},
    )

    res = client.post(
        "/api/kv", headers=auth("viewer-key"), json={"slug": "v", "title": "V"}
    )
    assert res.status_code == 403

    res = client.put(
        "/api/kv/c/keys/k", headers=auth("viewer-key"),
        json={"value": 1, "value_type": "integer"},
    )
    assert res.status_code == 403

    # but viewer can read
    client.put(
        "/api/kv/c/keys/k", headers=auth("editor-key"),
        json={"value": 1, "value_type": "integer"},
    )
    res = client.get("/api/kv/c/keys/k", headers=auth("viewer-key"))
    assert res.status_code == 200


def test_kv_stores_isolated_across_orgs():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    add_key(db, "key-b", user_id="ub", org_id="org-b")
    client = make_client(db)

    client.post(
        "/api/kv", headers=auth("key-b"),
        json={"slug": "b.secrets", "title": "B"},
    )
    client.put(
        "/api/kv/b.secrets/keys/k", headers=auth("key-b"),
        json={"value": "hidden", "value_type": "string"},
    )

    assert client.get(
        "/api/kv/b.secrets/keys/k", headers=auth("key-a")
    ).status_code == 404
    assert client.get(
        "/api/kv/b.secrets/keys", headers=auth("key-a")
    ).status_code == 404
    listed = client.get("/api/kv", headers=auth("key-a")).json()
    assert listed == []


def test_workspace_scoped_key_clamps_store_creation():
    db = FakeDatabase()
    add_key(db, "scoped-key", user_id="ua", org_id="org-a",
            workspace="reach", project="alertee")
    client = make_client(db)

    res = client.post(
        "/api/kv", headers=auth("scoped-key"),
        json={"slug": "s", "title": "S", "workspace": "other", "project": "x"},
    )
    body = res.json()
    assert body["workspace"] == "reach"
    assert body["project"] == "alertee"
