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
from magpie.server.routes import entries, keys, orgs


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class FakeSettings:
    api_key = ""
    resend_api_key = "configured"  # auth enforced
    oauth_issuer_url = ""


class FakeDatabase:
    def __init__(self):
        self.entries: dict[str, dict] = {}
        self.api_keys: dict[str, dict] = {}  # key_hash -> record
        self.org_roles: dict[tuple[str, str], str] = {}  # (org_id, user_id) -> role
        self.workspaces: dict[str, dict] = {}
        self.members_removed: list[tuple[str, str]] = []
        self.invited: list[tuple[str, str, str]] = []
        self.search_calls: list[dict] = []
        self.links: dict[str, list[dict]] = {}  # source_id -> outgoing links

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
        return None

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

    async def get_entry(self, entry_id):
        return self.entries.get(entry_id)

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


def make_client(db: FakeDatabase) -> TestClient:
    app = FastAPI()
    app.include_router(entries.router)
    app.include_router(keys.router)
    app.include_router(orgs.router)
    app.add_middleware(AuthMiddleware)
    app.state.settings = FakeSettings()
    app.state.db = db
    app.state.embedder = None
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
