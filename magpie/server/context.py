"""Auth context — who is calling, what org/scope they belong to, what they may do.

Roles (ascending): viewer < editor < admin < owner.
- viewer: read/search only
- editor: read + write knowledge
- admin: editor + manage members, workspaces, org settings
- owner: admin + delete org

A context with no user and no org (static MAGPIE_API_KEY or auth disabled)
is unrestricted — single-tenant mode.
"""

from dataclasses import dataclass

from fastapi import Request

ROLE_LEVELS = {"viewer": 1, "editor": 2, "admin": 3, "owner": 4}


def cap_role(a: str | None, b: str | None) -> str | None:
    """Return the lesser of two roles. Used so switching a key's active org
    can never grant more than the key itself was issued with."""
    if a is None:
        return b
    if b is None:
        return a
    return a if ROLE_LEVELS.get(a, 0) <= ROLE_LEVELS.get(b, 0) else b


@dataclass
class AuthContext:
    user_id: str | None = None
    org_id: str | None = None
    role: str | None = None
    # API keys may be pinned to a workspace/project — all reads and writes
    # through such a key are clamped to that scope.
    workspace: str | None = None
    project: str | None = None

    @property
    def is_unrestricted(self) -> bool:
        """Static-key or no-auth mode: no tenant boundary applies."""
        return self.user_id is None and self.org_id is None

    def has_role(self, minimum: str) -> bool:
        if self.is_unrestricted:
            return True
        if self.role is None:
            # User with no org membership: can manage their own data only.
            # Personal-scope writes are checked via can_access, not role.
            return minimum in ("viewer", "editor")
        return ROLE_LEVELS.get(self.role, 0) >= ROLE_LEVELS[minimum]

    def can_access(self, entry: dict) -> bool:
        """Entry visibility: global entries, own entries, or same-org entries."""
        if self.is_unrestricted:
            return True
        if entry.get("user_id") is None and entry.get("org_id") is None:
            return True
        if entry.get("user_id") and entry["user_id"] == self.user_id:
            return True
        if entry.get("org_id") and entry["org_id"] == self.org_id:
            return True
        return False

    def clamp_scope(
        self, workspace: str | None, project: str | None
    ) -> tuple[str | None, str | None]:
        """Apply key scope: a workspace/project-pinned key overrides request values."""
        return (self.workspace or workspace, self.project or project)

    @property
    def view_filter(self) -> dict:
        """Visibility kwargs for fail-closed DB reads (get_entry/get_kv_store/
        get_kv_pair). Unrestricted contexts read everything; tenant contexts
        are clamped to their own + org + global rows in SQL. Spread into the
        call: ``await db.get_entry(id, **ctx.view_filter)``."""
        if self.is_unrestricted:
            return {"trusted": True}
        return {"user_id": self.user_id, "org_id": self.org_id}


def auth_context(request: Request) -> AuthContext:
    return AuthContext(
        user_id=getattr(request.state, "user_id", None),
        org_id=getattr(request.state, "org_id", None),
        role=getattr(request.state, "role", None),
        workspace=getattr(request.state, "auth_workspace", None),
        project=getattr(request.state, "auth_project", None),
    )


# Sentinel: the caller named an org they are not a member of. Distinct from
# "no active org" (None) so callers can reject a forged request with 403.
ORG_FORBIDDEN = object()


async def resolve_active_org(db, user_id: str, requested_org_id: str | None):
    """Pick a user's active org and role, mirroring alertee's resolution:
    explicit request (membership-validated) > saved default (validated,
    self-healing if stale) > first membership.

    Returns ``(org_id, role)``. If ``requested_org_id`` is given but the user
    is not a member, returns ``(ORG_FORBIDDEN, None)`` so the caller can 403
    rather than silently fall back to another org.
    """
    if requested_org_id:
        role = await db.get_org_role(requested_org_id, user_id)
        if role is None:
            return ORG_FORBIDDEN, None
        return requested_org_id, role

    default_org = await db.get_user_default_org(user_id)
    if default_org:
        role = await db.get_org_role(default_org, user_id)
        if role is not None:
            return default_org, role
        await db.set_user_default_org(user_id, None)  # self-heal stale default

    orgs = await db.list_user_orgs(user_id)
    if orgs:
        return orgs[0]["id"], orgs[0].get("role")
    return None, None
