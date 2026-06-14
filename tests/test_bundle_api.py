"""REST bundle endpoint tests (POST /api/bundle/push, GET /api/bundle/export).

Uses a minimal in-memory DB against the real router + auth middleware, so the
endpoint wiring, parsing, drift rejection, conflict handling, and export
rendering are what's under test.
"""

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magpie.server.auth import AuthMiddleware
from magpie.server.routes import bundle


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class FakeSettings:
    api_key = ""
    resend_api_key = "configured"  # auth enforced
    oauth_issuer_url = ""
    asset_public_base_url = ""


class FakeDB:
    def __init__(self):
        self.api_keys = {}
        self.entries = {}  # path -> record
        self.kv_stores = {}  # slug -> record
        self.kv_pairs = {}  # (store_id, key) -> value

    # auth / roles
    async def get_api_key_by_hash(self, h):
        return self.api_keys.get(h)

    async def touch_api_key(self, kid):
        pass

    async def get_org_role(self, org_id, user_id):
        return self.api_keys and "editor"

    # entries
    async def upsert_entry_by_path(self, source_path, title, content, category="resource",  # noqa: E501
                                   tags=None, source=None, embedding=None, org_id=None,
                                   workspace=None, project=None):
        was = source_path in self.entries
        self.entries[source_path] = {
            "id": self.entries.get(source_path, {}).get("id", uuid4().hex),
            "title": title, "content": content, "category": category,
            "tags": tags or [], "source": source, "source_path": source_path,
            "org_id": org_id, "workspace": workspace, "project": project,
        }
        return self.entries[source_path]["id"], was

    async def get_entry(self, entry_id, *, user_id=None, org_id=None, trusted=False):
        return next((e for e in self.entries.values() if e["id"] == entry_id), None)

    async def find_entries_by_titles(self, titles, user_id=None, org_id=None):
        return {}

    async def replace_entry_links(self, entry_id, org_id, links):
        pass

    async def list_entries(self, org_id=None, workspace=None, project=None,  # noqa: E501
                           offset=0, limit=200, **kw):
        rows = list(self.entries.values())
        return rows[offset:offset + limit]

    # kv stores
    async def find_kv_store(self, slug, org_id=None, workspace=None, project=None):
        return self.kv_stores.get(slug)

    async def create_kv_store(self, slug, title, description=None, visibility="org",
                              org_id=None, workspace=None, project=None,
                              created_by_user_id=None, source="server"):
        cid = uuid4().hex
        self.kv_stores[slug] = {
            "id": cid, "slug": slug, "title": title, "org_id": org_id,
            "workspace": workspace, "project": project, "source": source,
        }
        return cid

    async def list_kv_stores(self, org_id=None, workspace=None, project=None):
        return [{**c, "key_count": 0} for c in self.kv_stores.values()]

    async def set_kv_pair(self, store_id, key, value, value_type="json",
                          summary=None, org_id=None, created_by_user_id=None):
        self.kv_pairs[(store_id, key)] = {
            "key": key, "value": value, "value_type": value_type,
        }
        return uuid4().hex

    async def list_kv_pairs(self, store_id):
        return [v for (sid, _), v in self.kv_pairs.items() if sid == store_id]


def make_client(db):
    app = FastAPI()
    app.include_router(bundle.router)
    app.add_middleware(AuthMiddleware)
    app.state.settings = FakeSettings()
    app.state.db = db
    app.state.embedder = None
    return TestClient(app)


def add_key(db, token, *, role="editor", org_id="org-a", user_id="ua"):
    db.api_keys[_hash(token)] = {
        "id": uuid4().hex, "name": token, "key_prefix": token[:12],
        "user_id": user_id, "org_id": org_id, "workspace": None,
        "project": None, "role": role,
        "created_at": datetime.now(UTC), "last_used_at": None,
    }


def auth(token):
    return {"Authorization": f"Bearer {token}"}


ENTRY = {
    "path": "orders.md",
    "text": "---\nmagpie_version: 1\ncategory: resource\ntitle: Orders\n---\n\nOne row per order.",
}


def test_push_creates_entries_and_repo_store():
    db = FakeDB()
    add_key(db, "k")
    client = make_client(db)
    res = client.post("/api/bundle/push", headers=auth("k"), json={
        "entries": [ENTRY],
        "kv": [{"slug": "strategy", "text": '{"mrr": 4200}'}],
    })
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["created"] == 1 and body["stores"] == 1 and body["pairs"] == 1
    assert db.kv_stores["strategy"]["source"] == "repo"


def test_push_is_idempotent():
    db = FakeDB()
    add_key(db, "k")
    client = make_client(db)
    client.post("/api/bundle/push", headers=auth("k"), json={"entries": [ENTRY]})
    res = client.post("/api/bundle/push", headers=auth("k"), json={"entries": [ENTRY]})
    assert res.json()["updated"] == 1
    assert res.json()["created"] == 0


def test_push_rejects_off_spec_file():
    db = FakeDB()
    add_key(db, "k")
    client = make_client(db)
    res = client.post("/api/bundle/push", headers=auth("k"), json={
        "entries": [{"path": "bad.md", "text": "no frontmatter here"}],
    })
    assert res.status_code == 422
    assert res.json()["files"][0]["path"] == "bad.md"


def test_push_rejects_undeclared_store_with_manifest():
    db = FakeDB()
    add_key(db, "k")
    client = make_client(db)
    res = client.post("/api/bundle/push", headers=auth("k"), json={
        "kv": [{"slug": "stratagy", "text": "{}"}],
        "manifest": {"stores": {"strategy": {"title": "S"}}},
    })
    assert res.status_code == 422
    assert "drift" in res.json()["error"]


def test_push_conflict_on_server_canonical_store():
    db = FakeDB()
    add_key(db, "k")
    # Pre-existing live store with the same slug.
    db.kv_stores["strategy"] = {
        "id": "c1", "slug": "strategy", "org_id": "org-a", "source": "server",
        "workspace": None, "project": None,
    }
    client = make_client(db)
    res = client.post("/api/bundle/push", headers=auth("k"), json={
        "kv": [{"slug": "strategy", "text": '{"x": 1}'}],
    })
    assert res.status_code == 409
    assert "strategy" in res.json()["conflicts"]


def test_push_requires_editor_role():
    db = FakeDB()
    add_key(db, "v", role="viewer")
    client = make_client(db)
    res = client.post("/api/bundle/push", headers=auth("v"), json={"entries": [ENTRY]})
    assert res.status_code == 403


def test_export_returns_rendered_files():
    db = FakeDB()
    add_key(db, "k")
    client = make_client(db)
    client.post("/api/bundle/push", headers=auth("k"), json={
        "entries": [ENTRY],
        "kv": [{"slug": "strategy", "text": '{"mrr": 4200}'}],
    })
    res = client.get("/api/bundle/export", headers=auth("k"))
    assert res.status_code == 200
    paths = {f["path"] for f in res.json()["files"]}
    assert "orders.md" in paths
    assert "kv/strategy.json" in paths
    assert "index.html" in paths
