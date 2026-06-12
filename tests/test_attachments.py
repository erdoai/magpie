"""Attachment storage, upload/read/delete, and public asset gating tests."""

import pytest

from magpie.attachments import infer_kind, is_browser_safe
from magpie.storage.local import LocalStorage

from .test_isolation import FakeDatabase, add_key, auth, make_client

# -- Helpers --


def test_infer_kind():
    assert infer_kind("logo.png", "image/png") == "image"
    assert infer_kind("revenue.sql", "application/octet-stream") == "sql"
    assert infer_kind("brief.md", "text/markdown") == "text"
    assert infer_kind("data.json", "application/json") == "text"
    assert infer_kind("deck.pdf", "application/pdf") == "pdf"
    assert infer_kind("blob.bin", "application/octet-stream") == "file"


def test_is_browser_safe():
    assert is_browser_safe("image/png")
    assert is_browser_safe("image/svg+xml")
    assert is_browser_safe("IMAGE/PNG; charset=binary")
    assert not is_browser_safe("application/pdf")
    assert not is_browser_safe("text/html")
    assert not is_browser_safe("application/sql")


# -- Local storage --


async def test_local_storage_roundtrip(tmp_path):
    storage = LocalStorage(str(tmp_path))
    await storage.put("org/e1/a1/logo.png", b"png-bytes", "image/png")
    assert await storage.get("org/e1/a1/logo.png") == b"png-bytes"
    assert await storage.signed_url("org/e1/a1/logo.png") is None
    await storage.delete("org/e1/a1/logo.png")
    assert await storage.get("org/e1/a1/logo.png") is None


async def test_local_storage_rejects_traversal(tmp_path):
    storage = LocalStorage(str(tmp_path))
    with pytest.raises(ValueError):
        await storage.put("../escape.txt", b"x", "text/plain")


# -- Upload / read / delete through the API --


def _setup(tmp_path):
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    storage = LocalStorage(str(tmp_path))
    client = make_client(db, storage=storage)
    entry_id = db.add_entry(org_id="org-a", title="Brand style")
    return db, client, entry_id


def test_upload_and_read_attachment(tmp_path):
    db, client, entry_id = _setup(tmp_path)

    res = client.post(
        f"/api/entries/{entry_id}/attachments",
        headers=auth("key-a"),
        files={"file": ("logo-primary.png", b"png-bytes", "image/png")},
        data={"role": "logo-primary", "description": "Primary logo"},
    )
    assert res.status_code == 200, res.text
    att = res.json()
    assert att["kind"] == "image"
    assert att["role"] == "logo-primary"
    assert att["handle"].startswith("magpie:")
    assert att["byte_size"] == 9
    assert att["content_text"] is None

    att_id = att["id"]
    res = client.get(f"/api/attachments/{att_id}", headers=auth("key-a"))
    assert res.status_code == 200

    res = client.get(f"/api/attachments/{att_id}/download", headers=auth("key-a"))
    assert res.status_code == 200
    assert res.content == b"png-bytes"
    assert res.headers["content-type"].startswith("image/png")

    listed = client.get(
        f"/api/entries/{entry_id}/attachments", headers=auth("key-a")
    ).json()
    assert len(listed) == 1


def test_small_sql_attachment_inlined(tmp_path):
    db, client, entry_id = _setup(tmp_path)

    sql = "SELECT * FROM revenue WHERE month = $1;"
    res = client.post(
        f"/api/entries/{entry_id}/attachments",
        headers=auth("key-a"),
        files={"file": ("query-revenue.sql", sql.encode(), "application/sql")},
        data={"role": "query-revenue"},
    )
    att = res.json()
    assert att["kind"] == "sql"

    res = client.get(f"/api/attachments/{att['id']}", headers=auth("key-a"))
    assert res.json()["content_text"] == sql


def test_delete_attachment_removes_blob(tmp_path):
    db, client, entry_id = _setup(tmp_path)

    res = client.post(
        f"/api/entries/{entry_id}/attachments",
        headers=auth("key-a"),
        files={"file": ("brief.txt", b"the brief", "text/plain")},
    )
    att = res.json()

    res = client.delete(f"/api/attachments/{att['id']}", headers=auth("key-a"))
    assert res.json() == {"ok": True}
    assert (
        client.get(f"/api/attachments/{att['id']}", headers=auth("key-a")).status_code
        == 404
    )
    # Blob gone too
    assert not list(tmp_path.rglob("brief.txt"))


def test_viewer_cannot_upload_or_delete(tmp_path):
    db, client, entry_id = _setup(tmp_path)
    add_key(db, "viewer-key", user_id="uv", org_id="org-a", role="viewer")

    res = client.post(
        f"/api/entries/{entry_id}/attachments",
        headers=auth("viewer-key"),
        files={"file": ("x.txt", b"x", "text/plain")},
    )
    assert res.status_code == 403


def test_attachments_isolated_across_orgs(tmp_path):
    db, client, entry_id = _setup(tmp_path)
    add_key(db, "key-b", user_id="ub", org_id="org-b")

    res = client.post(
        f"/api/entries/{entry_id}/attachments",
        headers=auth("key-a"),
        files={"file": ("secret.txt", b"secret", "text/plain")},
    )
    att_id = res.json()["id"]

    assert client.get(f"/api/attachments/{att_id}", headers=auth("key-b")).status_code == 404
    assert client.get(
        f"/api/attachments/{att_id}/download", headers=auth("key-b")
    ).status_code == 404
    assert client.delete(f"/api/attachments/{att_id}", headers=auth("key-b")).status_code == 404


# -- Public assets --


def test_public_asset_route_gating(tmp_path):
    db, client, entry_id = _setup(tmp_path)

    # Private image: not served publicly
    res = client.post(
        f"/api/entries/{entry_id}/attachments",
        headers=auth("key-a"),
        files={"file": ("logo.png", b"png", "image/png")},
    )
    private_id = res.json()["id"]
    assert client.get(f"/public/assets/{private_id}").status_code == 404

    # Public image: served without auth, with public_url populated
    res = client.post(
        f"/api/entries/{entry_id}/attachments",
        headers=auth("key-a"),
        files={"file": ("logo-public.png", b"public-png", "image/png")},
        data={"public": "true"},
    )
    public_att = res.json()
    assert public_att["public_url"] == f"/public/assets/{public_att['id']}"
    res = client.get(f"/public/assets/{public_att['id']}")
    assert res.status_code == 200
    assert res.content == b"public-png"


def test_non_image_cannot_be_public(tmp_path):
    db, client, entry_id = _setup(tmp_path)

    res = client.post(
        f"/api/entries/{entry_id}/attachments",
        headers=auth("key-a"),
        files={"file": ("query.sql", b"SELECT 1;", "application/sql")},
        data={"public": "true"},
    )
    assert res.status_code == 400
