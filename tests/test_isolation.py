"""Visibility, role, and cross-org isolation tests for the REST API.

Uses an in-memory fake Database against the real routers + auth middleware,
so the authorization logic (not Postgres) is what's under test.
"""

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from magpie.server.auth import AuthMiddleware
from magpie.server.context import AuthContext
from magpie.server.routes import attachments, entries, keys, kv, orgs


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class FakeSettings:
    api_key = ""
    resend_api_key = "configured"  # auth enforced
    oauth_issuer_url = ""
    asset_public_base_url = ""
    attachment_inline_limit = 16384


class FakeDatabase:
    def __init__(self):
        self.entries: dict[str, dict] = {}
        self.api_keys: dict[str, dict] = {}  # key_hash -> record
        self.org_roles: dict[tuple[str, str], str] = {}  # (org_id, user_id) -> role
        self.workspaces: dict[str, dict] = {}
        self.projects: dict[str, dict] = {}
        self.members_removed: list[tuple[str, str]] = []
        self.invited: list[tuple[str, str, str]] = []
        self.search_calls: list[dict] = []
        self.links: dict[str, list[dict]] = {}  # source_id -> outgoing links
        self.kv_stores: dict[str, dict] = {}
        self.kv_pairs: dict[tuple[str, str], dict] = {}  # (store_id, key)
        self.attachments: dict[str, dict] = {}
        self.sessions: dict[str, dict] = {}  # session_id -> {user_id}
        self.user_default_org: dict[str, str | None] = {}  # user_id -> org_id

    # -- keys --

    async def get_api_key_by_hash(self, key_hash):
        return self.api_keys.get(key_hash)

    async def touch_api_key(self, key_id):
        pass

    async def create_api_key(self, name, key_hash, key_prefix, user_id=None,
                             org_id=None, workspace=None, project=None, role="editor"):
        key_id = uuid4().hex
        self.api_keys[key_hash] = {
            "id": key_id, "name": name, "key_prefix": key_prefix,
            "user_id": user_id, "org_id": org_id, "workspace": workspace,
            "project": project, "role": role,
            "created_at": datetime.now(UTC), "last_used_at": None,
        }
        return key_id

    async def get_api_key(self, key_id):
        for rec in self.api_keys.values():
            if rec["id"] == key_id:
                return rec
        return None

    async def list_api_keys(self):
        return list(self.api_keys.values())

    async def list_api_keys_for_user(self, user_id):
        return [r for r in self.api_keys.values() if r["user_id"] == user_id]

    async def delete_api_key(self, key_id):
        for h, rec in list(self.api_keys.items()):
            if rec["id"] == key_id:
                del self.api_keys[h]
                return True
        return False

    # -- sessions / users / orgs --

    async def get_session(self, session_id):
        return self.sessions.get(session_id)

    async def get_user_default_org(self, user_id):
        return self.user_default_org.get(user_id)

    async def set_user_default_org(self, user_id, org_id):
        self.user_default_org[user_id] = org_id

    async def list_user_orgs(self, user_id):
        return [
            {"id": org_id, "name": org_id, "slug": org_id, "role": role}
            for (org_id, uid), role in self.org_roles.items()
            if uid == user_id
        ]

    async def get_org_role(self, org_id, user_id):
        return self.org_roles.get((org_id, user_id))

    async def get_or_create_user(self, email):
        return {"id": f"user-{email}", "email": email, "display_name": None}

    async def add_org_member(self, org_id, user_id, role="editor"):
        self.invited.append((org_id, user_id, role))
        self.org_roles[(org_id, user_id)] = role

    async def list_org_members(self, org_id):
        return [
            {"id": uid, "email": f"{uid}@x.com", "display_name": None,
             "role": role, "joined_at": datetime.now(UTC)}
            for (oid, uid), role in self.org_roles.items()
            if oid == org_id
        ]

    async def remove_org_member(self, org_id, user_id):
        if (org_id, user_id) in self.org_roles:
            del self.org_roles[(org_id, user_id)]
            self.members_removed.append((org_id, user_id))
            return True
        return False

    # -- workspaces --

    async def get_workspace(self, ws_id):
        return self.workspaces.get(ws_id)

    async def list_workspaces(self, org_id):
        return [w for w in self.workspaces.values() if w["org_id"] == org_id]

    async def create_workspace(self, org_id, name, slug):
        ws_id = uuid4().hex
        self.workspaces[ws_id] = {"id": ws_id, "org_id": org_id, "name": name, "slug": slug}
        return ws_id

    async def delete_workspace(self, ws_id):
        return self.workspaces.pop(ws_id, None) is not None

    # -- projects --

    async def get_project(self, proj_id):
        return self.projects.get(proj_id)

    async def list_projects(self, ws_id):
        return [p for p in self.projects.values() if p["workspace_id"] == ws_id]

    async def create_project(self, ws_id, name, slug):
        proj_id = uuid4().hex
        self.projects[proj_id] = {
            "id": proj_id, "workspace_id": ws_id, "name": name, "slug": slug,
        }
        return proj_id

    async def delete_project(self, proj_id):
        return self.projects.pop(proj_id, None) is not None

    # -- kv stores / pairs --

    async def create_kv_store(self, slug, title, description=None, visibility="org",
                              org_id=None, workspace=None, project=None,
                              created_by_user_id=None):
        store_id = uuid4().hex
        now = datetime.now(UTC)
        self.kv_stores[store_id] = {
            "id": store_id, "org_id": org_id, "workspace": workspace,
            "project": project, "slug": slug, "title": title,
            "description": description, "visibility": visibility,
            "created_by_user_id": created_by_user_id,
            "created_at": now, "updated_at": now,
        }
        return store_id

    async def get_kv_store(self, store_id, *, user_id=None, org_id=None, trusted=False):
        store = self.kv_stores.get(store_id)
        if store is None or trusted:
            return store
        if store.get("org_id") is None or store.get("org_id") == org_id:
            return store
        return None

    async def find_kv_store(self, slug, org_id=None, workspace=None, project=None):
        matches = [
            c for c in self.kv_stores.values()
            if c["slug"] == slug
            and (not org_id or c["org_id"] in (org_id, None))
            and (not workspace or c["workspace"] in (workspace, None))
            and (not project or c["project"] in (project, None))
        ]
        matches.sort(key=lambda c: (c["org_id"] is None, c["workspace"] is None,
                                    c["project"] is None))
        return matches[0] if matches else None

    async def list_kv_stores(self, org_id=None, workspace=None, project=None):
        result = []
        for c in self.kv_stores.values():
            if org_id and c["org_id"] not in (org_id, None):
                continue
            if workspace and c["workspace"] != workspace:
                continue
            if project and c["project"] != project:
                continue
            count = sum(1 for (sid, _k) in self.kv_pairs if sid == c["id"])
            result.append({**c, "key_count": count})
        return result

    async def delete_kv_store(self, store_id):
        if store_id not in self.kv_stores:
            return False
        del self.kv_stores[store_id]
        for key in [k for k in self.kv_pairs if k[0] == store_id]:
            del self.kv_pairs[key]
        return True

    async def set_kv_pair(self, store_id, key, value, value_type="json",
                          summary=None, org_id=None, created_by_user_id=None):
        now = datetime.now(UTC)
        existing = self.kv_pairs.get((store_id, key))
        pair_id = existing["id"] if existing else uuid4().hex
        self.kv_pairs[(store_id, key)] = {
            "id": pair_id, "org_id": org_id, "store_id": store_id,
            "key": key, "value": value, "value_type": value_type,
            "summary": summary or (existing or {}).get("summary"),
            "metadata_json": {}, "created_by_user_id": created_by_user_id,
            "created_at": (existing or {}).get("created_at", now), "updated_at": now,
        }
        return pair_id

    async def get_kv_pair(self, store_id, key, *, user_id=None, org_id=None, trusted=False):
        pair = self.kv_pairs.get((store_id, key))
        if pair is None or trusted:
            return pair
        store = self.kv_stores.get(store_id)
        store_org = store.get("org_id") if store else None
        if store_org is None or store_org == org_id:
            return pair
        return None

    async def list_kv_pairs(self, store_id):
        return [d for (sid, _k), d in sorted(self.kv_pairs.items())
                if sid == store_id]

    async def delete_kv_pair(self, store_id, key):
        return self.kv_pairs.pop((store_id, key), None) is not None

    # -- attachments --

    async def create_attachment(self, entry_id, kind, filename, media_type,
                                storage_key, byte_size, org_id=None, description=None,
                                role=None, public=False, created_by_user_id=None,
                                att_id=None):
        att_id = att_id or uuid4().hex
        self.attachments[att_id] = {
            "id": att_id, "org_id": org_id, "entry_id": entry_id, "kind": kind,
            "filename": filename, "media_type": media_type,
            "storage_key": storage_key, "byte_size": byte_size,
            "description": description, "role": role, "public": public,
            "metadata_json": {}, "created_by_user_id": created_by_user_id,
            "created_at": datetime.now(UTC),
        }
        return att_id

    async def get_attachment(self, att_id):
        return self.attachments.get(att_id)

    async def list_attachments(self, entry_id):
        return [a for a in self.attachments.values() if a["entry_id"] == entry_id]

    async def delete_attachment(self, att_id):
        return self.attachments.pop(att_id, None) is not None

    # -- entries --

    def add_entry(self, **fields):
        entry_id = uuid4().hex
        now = datetime.now(UTC)
        entry = {
            "id": entry_id, "title": "t", "content": "c", "category": "resource",
            "tags": [], "source": None, "user_id": None, "org_id": None,
            "workspace": None, "project": None,
            "created_at": now, "updated_at": now,
        }
        entry.update(fields)
        self.entries[entry_id] = entry
        return entry_id

    async def create_entry(self, title, content, category="resource", tags=None,
                           source=None, embedding=None, user_id=None, org_id=None,
                           workspace=None, project=None):
        return self.add_entry(
            title=title, content=content, category=category, tags=tags or [],
            source=source, user_id=user_id, org_id=org_id,
            workspace=workspace, project=project,
        )

    async def get_entry(self, entry_id, *, user_id=None, org_id=None, trusted=False):
        entry = self.entries.get(entry_id)
        if entry is None or trusted:
            return entry
        # Fail-closed: global, own, or same-org only (mirrors SQL in database.py).
        if entry.get("user_id") is None and entry.get("org_id") is None:
            return entry
        if entry.get("user_id") is not None and entry.get("user_id") == user_id:
            return entry
        if entry.get("org_id") is not None and entry.get("org_id") == org_id:
            return entry
        return None

    async def update_entry(self, entry_id, **fields):
        entry = self.entries.get(entry_id)
        if not entry:
            return False
        entry.update({k: v for k, v in fields.items() if v is not None})
        return True

    async def delete_entry(self, entry_id):
        return self.entries.pop(entry_id, None) is not None

    async def archive_entry(self, entry_id):
        entry = self.entries.get(entry_id)
        if not entry:
            return False
        entry["category"] = "archive"
        return True

    async def list_entries(self, **kwargs):
        return list(self.entries.values())

    async def search_keyword(self, query, **scope):
        self.search_calls.append({"query": query, **scope})
        return []

    # -- links --

    async def find_entries_by_titles(self, normalized_titles, user_id=None, org_id=None):
        ctx = AuthContext(user_id=user_id, org_id=org_id)
        result = {}
        for entry in self.entries.values():
            norm = " ".join(entry["title"].split()).lower()
            if norm in normalized_titles and ctx.can_access(entry):
                result[norm] = entry["id"]
        return result

    async def replace_entry_links(self, entry_id, org_id, links):
        self.links[entry_id] = [
            {**li, "id": uuid4().hex, "org_id": org_id, "source_id": entry_id,
             "created_at": datetime.now(UTC)}
            for li in links
        ]

    async def get_outgoing_links(self, entry_id):
        out = []
        for li in self.links.get(entry_id, []):
            target = self.entries.get(li.get("target_id") or "")
            out.append({
                **li,
                "target_title": target["title"] if target else None,
                "target_workspace": target.get("workspace") if target else None,
                "target_project": target.get("project") if target else None,
            })
        return out

    async def get_backlinks(self, entry_id, normalized_title, user_id=None, org_id=None):
        ctx = AuthContext(user_id=user_id, org_id=org_id)
        result = []
        for source_id, links in self.links.items():
            source = self.entries.get(source_id)
            if not source or not ctx.can_access(source):
                continue
            for li in links:
                hit = (
                    (li["target_type"] == "entry" and li.get("target_id") == entry_id)
                    or (li["target_type"] == "unresolved"
                        and li["normalized_target"] == normalized_title)
                )
                if hit:
                    result.append({
                        **li,
                        "source_title": source["title"],
                        "source_workspace": source.get("workspace"),
                        "source_project": source.get("project"),
                    })
        return result


def make_client(db: FakeDatabase, storage=None) -> TestClient:
    app = FastAPI()
    app.include_router(entries.router)
    app.include_router(kv.router)
    app.include_router(attachments.router)
    app.include_router(keys.router)
    app.include_router(orgs.router)
    app.add_middleware(AuthMiddleware)
    app.state.settings = FakeSettings()
    app.state.db = db
    app.state.embedder = None
    app.state.storage = storage
    return TestClient(app)


def add_key(db: FakeDatabase, token: str, *, user_id=None, org_id=None,
            workspace=None, project=None, role="editor") -> None:
    db.api_keys[_hash(token)] = {
        "id": uuid4().hex, "name": token, "key_prefix": token[:12],
        "user_id": user_id, "org_id": org_id, "workspace": workspace,
        "project": project, "role": role,
        "created_at": datetime.now(UTC), "last_used_at": None,
    }


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# -- Cross-org entry isolation --


def test_cannot_read_other_orgs_entry():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    entry_id = db.add_entry(org_id="org-b", user_id="ub")
    client = make_client(db)

    assert client.get(f"/api/entries/{entry_id}", headers=auth("key-a")).status_code == 404


def test_cannot_update_or_delete_other_orgs_entry():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    entry_id = db.add_entry(org_id="org-b", user_id="ub", title="original")
    client = make_client(db)

    res = client.put(
        f"/api/entries/{entry_id}", headers=auth("key-a"), json={"title": "stolen"}
    )
    assert res.status_code == 404
    assert db.entries[entry_id]["title"] == "original"

    assert client.delete(f"/api/entries/{entry_id}", headers=auth("key-a")).status_code == 404
    assert entry_id in db.entries

    res = client.post(f"/api/entries/{entry_id}/archive", headers=auth("key-a"))
    assert res.status_code == 404
    assert db.entries[entry_id]["category"] != "archive"


def test_can_read_own_org_and_global_entries():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    own = db.add_entry(org_id="org-a", user_id="other-user-same-org")
    global_entry = db.add_entry()  # no user, no org
    client = make_client(db)

    assert client.get(f"/api/entries/{own}", headers=auth("key-a")).status_code == 200
    assert client.get(f"/api/entries/{global_entry}", headers=auth("key-a")).status_code == 200


def test_cannot_merge_entries_from_other_org():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    mine = db.add_entry(org_id="org-a")
    theirs = db.add_entry(org_id="org-b")
    client = make_client(db)

    res = client.post(
        "/api/entries/merge",
        headers=auth("key-a"),
        json={"source_ids": [mine, theirs], "title": "m", "content": "c"},
    )
    assert res.status_code == 404


# -- Roles --


def test_viewer_key_cannot_write():
    db = FakeDatabase()
    add_key(db, "viewer-key", user_id="ua", org_id="org-a", role="viewer")
    entry_id = db.add_entry(org_id="org-a")
    client = make_client(db)

    res = client.post(
        "/api/entries", headers=auth("viewer-key"), json={"title": "t", "content": "c"}
    )
    assert res.status_code == 403

    res = client.put(
        f"/api/entries/{entry_id}", headers=auth("viewer-key"), json={"title": "x"}
    )
    assert res.status_code == 403

    assert client.delete(
        f"/api/entries/{entry_id}", headers=auth("viewer-key")
    ).status_code == 403


def test_editor_key_can_write():
    db = FakeDatabase()
    add_key(db, "editor-key", user_id="ua", org_id="org-a", role="editor")
    client = make_client(db)

    res = client.post(
        "/api/entries", headers=auth("editor-key"), json={"title": "t", "content": "c"}
    )
    assert res.status_code == 200
    assert res.json()["org_id"] == "org-a"


# -- Scoped keys --


def test_workspace_scoped_key_clamps_writes_and_reads():
    db = FakeDatabase()
    add_key(db, "scoped-key", user_id="ua", org_id="org-a",
            workspace="reach", project="alertee")
    client = make_client(db)

    res = client.post(
        "/api/entries",
        headers=auth("scoped-key"),
        json={"title": "t", "content": "c", "workspace": "other", "project": "elsewhere"},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["workspace"] == "reach"
    assert body["project"] == "alertee"


def test_search_passes_workspace_and_project_to_db():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    client = make_client(db)

    res = client.post(
        "/api/search",
        headers=auth("key-a"),
        json={"query": "q", "workspace": "reach", "project": "alertee"},
    )
    assert res.status_code == 200
    assert db.search_calls, "keyword search was not invoked"
    call = db.search_calls[0]
    assert call["workspace"] == "reach"
    assert call["project"] == "alertee"
    assert call["org_id"] == "org-a"


# -- API key management --


def test_keys_are_bound_to_caller_and_listed_per_user():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    add_key(db, "key-b", user_id="ub", org_id="org-b")
    client = make_client(db)

    res = client.post("/api/keys", headers=auth("key-a"), json={"name": "new"})
    assert res.status_code == 200
    assert res.json()["user_id"] == "ua"
    assert res.json()["org_id"] == "org-a"

    listed = client.get("/api/keys", headers=auth("key-a")).json()
    assert {k["user_id"] for k in listed} == {"ua"}


def test_key_cannot_escalate_role():
    db = FakeDatabase()
    add_key(db, "editor-key", user_id="ua", org_id="org-a", role="editor")
    client = make_client(db)

    res = client.post(
        "/api/keys", headers=auth("editor-key"), json={"name": "boss", "role": "owner"}
    )
    assert res.status_code == 403


def test_cannot_delete_other_users_key():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    add_key(db, "key-b", user_id="ub", org_id="org-b")
    target_id = db.api_keys[_hash("key-b")]["id"]
    client = make_client(db)

    assert client.delete(f"/api/keys/{target_id}", headers=auth("key-a")).status_code == 404
    assert _hash("key-b") in db.api_keys


# -- Org management --


def test_non_member_cannot_list_members():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    db.org_roles[("org-b", "ub")] = "owner"
    client = make_client(db)

    assert client.get("/api/orgs/org-b/members", headers=auth("key-a")).status_code == 404


def test_editor_cannot_invite_admin_can():
    db = FakeDatabase()
    add_key(db, "editor-key", user_id="ua", org_id="org-a", role="editor")
    add_key(db, "admin-key", user_id="ub", org_id="org-a", role="admin")
    db.org_roles[("org-a", "ua")] = "editor"
    db.org_roles[("org-a", "ub")] = "admin"
    client = make_client(db)

    res = client.post(
        "/api/orgs/org-a/members", headers=auth("editor-key"), json={"email": "x@y.com"}
    )
    assert res.status_code == 403

    res = client.post(
        "/api/orgs/org-a/members", headers=auth("admin-key"), json={"email": "x@y.com"}
    )
    assert res.status_code == 200
    assert db.invited


def test_member_can_remove_self_but_not_others():
    db = FakeDatabase()
    add_key(db, "editor-key", user_id="ua", org_id="org-a", role="editor")
    db.org_roles[("org-a", "ua")] = "editor"
    db.org_roles[("org-a", "ub")] = "editor"
    client = make_client(db)

    res = client.delete("/api/orgs/org-a/members/ub", headers=auth("editor-key"))
    assert res.status_code == 403

    res = client.delete("/api/orgs/org-a/members/ua", headers=auth("editor-key"))
    assert res.status_code == 200
    assert ("org-a", "ua") in db.members_removed


def test_workspace_delete_requires_admin():
    db = FakeDatabase()
    add_key(db, "editor-key", user_id="ua", org_id="org-a", role="editor")
    add_key(db, "admin-key", user_id="ub", org_id="org-a", role="admin")
    db.org_roles[("org-a", "ua")] = "editor"
    db.org_roles[("org-a", "ub")] = "admin"
    ws_id = uuid4().hex
    db.workspaces[ws_id] = {"id": ws_id, "org_id": "org-a", "name": "W", "slug": "w"}
    client = make_client(db)

    assert client.delete(f"/api/workspaces/{ws_id}", headers=auth("editor-key")).status_code == 403
    assert client.delete(f"/api/workspaces/{ws_id}", headers=auth("admin-key")).status_code == 200


def test_project_create_list_delete_roles():
    db = FakeDatabase()
    add_key(db, "viewer-key", user_id="uv", org_id="org-a", role="viewer")
    add_key(db, "editor-key", user_id="ue", org_id="org-a", role="editor")
    add_key(db, "admin-key", user_id="ua", org_id="org-a", role="admin")
    db.org_roles[("org-a", "uv")] = "viewer"
    db.org_roles[("org-a", "ue")] = "editor"
    db.org_roles[("org-a", "ua")] = "admin"
    ws_id = uuid4().hex
    db.workspaces[ws_id] = {"id": ws_id, "org_id": "org-a", "name": "W", "slug": "w"}
    client = make_client(db)

    # create requires editor+
    assert client.post(
        f"/api/workspaces/{ws_id}/projects", json={"name": "Billing"},
        headers=auth("viewer-key"),
    ).status_code == 403
    res = client.post(
        f"/api/workspaces/{ws_id}/projects", json={"name": "Billing"},
        headers=auth("editor-key"),
    )
    assert res.status_code == 200
    proj = res.json()
    assert proj["slug"] == "billing" and proj["workspace_id"] == ws_id

    # list is viewer+ and scoped to the workspace
    listed = client.get(f"/api/workspaces/{ws_id}/projects", headers=auth("viewer-key"))
    assert listed.status_code == 200
    assert [p["slug"] for p in listed.json()] == ["billing"]

    # delete requires admin+
    assert client.delete(
        f"/api/projects/{proj['id']}", headers=auth("editor-key"),
    ).status_code == 403
    assert client.delete(
        f"/api/projects/{proj['id']}", headers=auth("admin-key"),
    ).status_code == 200


def test_project_endpoints_404_on_unknown_workspace():
    db = FakeDatabase()
    add_key(db, "admin-key", user_id="ua", org_id="org-a", role="admin")
    db.org_roles[("org-a", "ua")] = "admin"
    client = make_client(db)
    assert client.get(
        "/api/workspaces/nope/projects", headers=auth("admin-key"),
    ).status_code == 404


# -- Session org switching (X-Organization-ID + default org) --


def _session(db: FakeDatabase, user_id: str, *orgs: tuple[str, str]) -> dict:
    """Register a session for user_id with the given (org_id, role) memberships
    (in order — first listed becomes the bootstrap default). Returns request
    cookies for the session."""
    for org_id, role in orgs:
        db.org_roles[(org_id, user_id)] = role
    db.sessions["sess-1"] = {"user_id": user_id, "expires_at": None}
    return {"magpie_session": "sess-1"}


def test_session_falls_back_to_first_org():
    db = FakeDatabase()
    cookies = _session(db, "ua", ("org-a", "editor"), ("org-b", "admin"))
    in_b = db.add_entry(org_id="org-b", user_id="ub")
    client = make_client(db)

    # No header, no saved default -> first membership (org-a); org-b is hidden.
    assert client.get(f"/api/entries/{in_b}", cookies=cookies).status_code == 404


def test_org_header_switches_active_org():
    db = FakeDatabase()
    cookies = _session(db, "ua", ("org-a", "editor"), ("org-b", "admin"))
    in_b = db.add_entry(org_id="org-b", user_id="ub")
    client = make_client(db)

    res = client.get(
        f"/api/entries/{in_b}", cookies=cookies, headers={"X-Organization-ID": "org-b"}
    )
    assert res.status_code == 200


def test_org_header_rejected_when_not_a_member():
    db = FakeDatabase()
    cookies = _session(db, "ua", ("org-a", "editor"))
    client = make_client(db)

    res = client.get(
        "/api/orgs", cookies=cookies, headers={"X-Organization-ID": "org-x"}
    )
    assert res.status_code == 403


def test_select_org_persists_default_and_is_membership_checked():
    db = FakeDatabase()
    cookies = _session(db, "ua", ("org-a", "editor"), ("org-b", "admin"))
    in_b = db.add_entry(org_id="org-b", user_id="ub")
    client = make_client(db)

    # Cannot select an org you're not in.
    assert client.post("/api/orgs/org-x/select", cookies=cookies).status_code == 404

    # Select org-b -> persisted as default; subsequent header-less requests use it.
    res = client.post("/api/orgs/org-b/select", cookies=cookies)
    assert res.status_code == 200
    assert db.user_default_org["ua"] == "org-b"
    assert client.get(f"/api/entries/{in_b}", cookies=cookies).status_code == 200


def test_stale_default_org_self_heals():
    db = FakeDatabase()
    cookies = _session(db, "ua", ("org-a", "editor"))
    db.user_default_org["ua"] = "org-gone"  # membership no longer exists
    client = make_client(db)

    # Resolves without error (falls back to org-a) and clears the stale default.
    assert client.get("/api/orgs", cookies=cookies).status_code == 200
    assert db.user_default_org["ua"] is None


# -- API key org switching (X-Organization-ID on a user key) --


def test_key_can_switch_org_via_header():
    db = FakeDatabase()
    # Key pinned to org-a, but the user is also a member of org-b.
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    db.org_roles[("org-a", "ua")] = "editor"
    db.org_roles[("org-b", "ua")] = "admin"
    in_b = db.add_entry(org_id="org-b", user_id="ub")
    client = make_client(db)

    # Without the header the key stays on org-a -> org-b hidden.
    assert client.get(f"/api/entries/{in_b}", headers=auth("key-a")).status_code == 404
    # With the header it switches to org-b.
    res = client.get(
        f"/api/entries/{in_b}",
        headers={**auth("key-a"), "X-Organization-ID": "org-b"},
    )
    assert res.status_code == 200


def test_key_org_switch_is_role_capped():
    db = FakeDatabase()
    # Viewer key; user is admin in org-b. Switching must not escalate to admin.
    add_key(db, "key-a", user_id="ua", org_id="org-a", role="viewer")
    db.org_roles[("org-b", "ua")] = "admin"
    client = make_client(db)

    res = client.post(
        "/api/entries",
        headers={**auth("key-a"), "X-Organization-ID": "org-b"},
        json={"title": "t", "content": "c"},
    )
    assert res.status_code == 403  # still a viewer despite org-b admin membership


def test_key_org_switch_rejected_when_not_member():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    client = make_client(db)

    res = client.get(
        "/api/entries", headers={**auth("key-a"), "X-Organization-ID": "org-x"}
    )
    assert res.status_code == 403


# -- AuthContext unit tests --


def test_auth_context_visibility_rules():
    unrestricted = AuthContext()
    assert unrestricted.can_access({"user_id": "u", "org_id": "o"})
    assert unrestricted.has_role("owner")

    ctx = AuthContext(user_id="ua", org_id="org-a", role="editor")
    assert ctx.can_access({"user_id": None, "org_id": None})  # global
    assert ctx.can_access({"user_id": "ua", "org_id": None})  # own
    assert ctx.can_access({"user_id": "ub", "org_id": "org-a"})  # same org
    assert not ctx.can_access({"user_id": "ub", "org_id": "org-b"})
    assert ctx.has_role("editor")
    assert not ctx.has_role("admin")


def test_auth_context_scope_clamping():
    ctx = AuthContext(user_id="u", org_id="o", workspace="reach", project="alertee")
    assert ctx.clamp_scope("other", None) == ("reach", "alertee")
    open_ctx = AuthContext(user_id="u", org_id="o")
    assert open_ctx.clamp_scope("reach", "alertee") == ("reach", "alertee")


def test_view_filter_maps_context_to_db_kwargs():
    assert AuthContext().view_filter == {"trusted": True}  # unrestricted reads all
    scoped = AuthContext(user_id="ua", org_id="org-a", role="viewer")
    assert scoped.view_filter == {"user_id": "ua", "org_id": "org-a"}


async def test_db_get_entry_is_fail_closed_by_default():
    """The DB layer itself denies cross-tenant reads — not just the routes.

    Mirrors database.py: with neither trusted nor matching scope, only global
    (untenanted) rows come back; a foreign org/user yields None.
    """
    db = FakeDatabase()
    glob = db.add_entry()  # no user, no org
    org_a = db.add_entry(org_id="org-a", user_id="ua")

    # No scope, not trusted: only the global entry is visible.
    assert await db.get_entry(glob) is not None
    assert await db.get_entry(org_a) is None

    # Foreign viewer: still denied.
    assert await db.get_entry(org_a, user_id="ub", org_id="org-b") is None

    # Same-org viewer and trusted reads both succeed.
    assert await db.get_entry(org_a, user_id="ub", org_id="org-a") is not None
    assert await db.get_entry(org_a, trusted=True) is not None
