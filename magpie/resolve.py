"""Read-time reference resolution for entry Markdown.

Entries can embed value references that resolve when read — the stored
Markdown is never mutated:

- ``{{reach.strategy.alertee.positioning.wedge}}`` — short form: longest
  matching collection slug, then document key, then JSON path into the value.
- ``{{collection:reach.strategy/alertee#positioning.wedge}}`` — explicit
  long form: ``collection:<slug>/<key>[#<json.path>]``.
- ``{{attachment:logo-primary}}`` — attachment on the current entry by
  role or filename.
- ``[[wikilinks]]`` resolve to Markdown links (handled via stored link edges).

Permission checks apply to every target. Unresolved or unauthorized
references render as ``⟦unresolved: <ref>⟧`` placeholders and appear in
the dependency list with a status, so agents can see exactly what's
missing and the UI can show an unresolved state.
"""

import json
import re
from dataclasses import asdict, dataclass

from magpie.attachments import public_url_for
from magpie.links import FENCED_CODE_RE, INLINE_CODE_RE, WIKILINK_RE
from magpie.server.context import AuthContext

REF_RE = re.compile(r"\{\{([^{}\n]+)\}\}")


@dataclass
class Dependency:
    ref: str
    kind: str  # collection, attachment, entry
    status: str  # resolved, not_found, unauthorized, invalid
    target_id: str | None = None
    detail: str | None = None


def _placeholder(ref: str) -> str:
    return f"⟦unresolved: {ref}⟧"


def _json_path(value, path: list[str]):
    """Walk dict keys / list indices. Raises KeyError/IndexError on miss."""
    for part in path:
        if isinstance(value, dict):
            value = value[part]
        elif isinstance(value, list):
            value = value[int(part)]
        else:
            raise KeyError(part)
    return value


def _render_value(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return f"\n```json\n{json.dumps(value, indent=2, default=str)}\n```\n"
    return json.dumps(value, default=str)


def _split_ref(ref: str) -> tuple[str, str]:
    """Split into (scheme, rest). Bare dotted refs are collection shorthand."""
    if ref.startswith("collection:"):
        return "collection", ref[len("collection:"):]
    if ref.startswith("attachment:"):
        return "attachment", ref[len("attachment:"):]
    return "shorthand", ref


class Resolver:
    """Resolves references for one entry read, within the caller's scope."""

    def __init__(self, db, entry: dict, ctx: AuthContext, settings):
        self._db = db
        self._entry = entry
        self._ctx = ctx
        self._settings = settings
        self.dependencies: list[Dependency] = []

    async def resolve(self) -> str:
        """Render the entry's Markdown with references resolved."""
        markdown = self._entry.get("content") or ""

        # Protect code blocks from substitution
        protected: list[str] = []

        def _protect(match: re.Match) -> str:
            protected.append(match.group(0))
            return f"\x00{len(protected) - 1}\x00"

        text = FENCED_CODE_RE.sub(_protect, markdown)
        text = INLINE_CODE_RE.sub(_protect, text)

        out = []
        pos = 0
        for match in REF_RE.finditer(text):
            out.append(text[pos:match.start()])
            out.append(await self._resolve_ref(match.group(1).strip()))
            pos = match.end()
        out.append(text[pos:])
        text = "".join(out)

        text = await self._resolve_wikilinks(text)

        return re.sub(r"\x00(\d+)\x00", lambda m: protected[int(m.group(1))], text)

    async def _resolve_wikilinks(self, text: str) -> str:
        """Rewrite [[Title]] to Markdown links using the stored link edges."""
        links = await self._db.get_outgoing_links(self._entry["id"])
        by_norm = {li["normalized_target"]: li for li in links}

        def _replace(match: re.Match) -> str:
            raw = match.group(1).strip()
            target, _, display = raw.partition("|")
            target = target.strip()
            display = display.strip() or target
            norm = " ".join(target.split()).lower()
            link = by_norm.get(norm)
            if link and link["target_type"] == "entry" and link.get("target_id"):
                self.dependencies.append(Dependency(
                    ref=f"[[{target}]]", kind="entry", status="resolved",
                    target_id=link["target_id"],
                ))
                return f"[{display}](/entries/{link['target_id']})"
            if link and link["target_type"] == "url":
                return f"[{display}]({link['target_ref']})"
            if link and link["target_type"] == "resource":
                return f"`{link['target_ref']}`"
            self.dependencies.append(Dependency(
                ref=f"[[{target}]]", kind="entry", status="not_found",
            ))
            return _placeholder(f"[[{target}]]")

        return WIKILINK_RE.sub(_replace, text)

    async def _resolve_ref(self, ref: str) -> str:
        scheme, rest = _split_ref(ref)
        if scheme == "attachment":
            return await self._resolve_attachment(ref, rest)
        if scheme == "collection":
            return await self._resolve_collection_explicit(ref, rest)
        return await self._resolve_collection_shorthand(ref)

    async def _resolve_attachment(self, ref: str, name: str) -> str:
        attachments = await self._db.list_attachments(self._entry["id"])
        match = next(
            (a for a in attachments if a.get("role") == name or a["filename"] == name),
            None,
        )
        if not match:
            self.dependencies.append(Dependency(
                ref=ref, kind="attachment", status="not_found",
                detail=f"no attachment with role or filename '{name}'",
            ))
            return _placeholder(ref)

        self.dependencies.append(Dependency(
            ref=ref, kind="attachment", status="resolved", target_id=match["id"],
        ))
        url = public_url_for(match, self._settings) or (
            f"/api/attachments/{match['id']}/download"
        )
        if match["kind"] == "image":
            return f"![{match.get('description') or match['filename']}]({url})"
        return f"[{match['filename']}]({url})"

    async def _resolve_collection_explicit(self, ref: str, rest: str) -> str:
        # collection:<slug>/<key>[#<json.path>]
        slug, sep, key_part = rest.partition("/")
        if not sep or not key_part:
            self.dependencies.append(Dependency(
                ref=ref, kind="collection", status="invalid",
                detail="expected collection:<slug>/<key>[#path]",
            ))
            return _placeholder(ref)
        key, _, path = key_part.partition("#")
        path_parts = [p for p in path.split(".") if p] if path else []
        return await self._lookup_document(ref, slug, key, path_parts)

    async def _resolve_collection_shorthand(self, ref: str) -> str:
        # Longest collection-slug prefix wins; next segment is the key,
        # the rest is a JSON path into the value.
        segments = ref.split(".")
        if len(segments) < 2:
            self.dependencies.append(Dependency(
                ref=ref, kind="collection", status="invalid",
                detail="expected at least <collection>.<key>",
            ))
            return _placeholder(ref)

        for split in range(len(segments) - 1, 0, -1):
            slug = ".".join(segments[:split])
            col = await self._find_collection(slug)
            if col:
                key = segments[split]
                path_parts = segments[split + 1:]
                return await self._lookup_document(ref, slug, key, path_parts, col=col)

        self.dependencies.append(Dependency(
            ref=ref, kind="collection", status="not_found",
            detail="no matching collection slug prefix",
        ))
        return _placeholder(ref)

    async def _find_collection(self, slug: str) -> dict | None:
        col = await self._db.find_collection(
            slug,
            org_id=self._ctx.org_id or self._entry.get("org_id"),
            workspace=self._entry.get("workspace"),
            project=self._entry.get("project"),
        )
        if col and not self._ctx.can_access({"user_id": None, "org_id": col.get("org_id")}):
            return None
        return col

    async def _lookup_document(
        self, ref: str, slug: str, key: str, path: list[str], col: dict | None = None
    ) -> str:
        col = col or await self._find_collection(slug)
        if not col:
            self.dependencies.append(Dependency(
                ref=ref, kind="collection", status="not_found",
                detail=f"collection '{slug}' not found or not authorized",
            ))
            return _placeholder(ref)

        doc = await self._db.get_document(col["id"], key)
        if not doc:
            self.dependencies.append(Dependency(
                ref=ref, kind="collection", status="not_found",
                detail=f"document '{key}' not found in '{slug}'",
            ))
            return _placeholder(ref)

        value = doc["value"]
        if path:
            try:
                value = _json_path(value, path)
            except (KeyError, IndexError, ValueError, TypeError):
                self.dependencies.append(Dependency(
                    ref=ref, kind="collection", status="not_found",
                    target_id=doc["id"],
                    detail=f"path '{'.'.join(path)}' not found in value",
                ))
                return _placeholder(ref)

        self.dependencies.append(Dependency(
            ref=ref, kind="collection", status="resolved", target_id=doc["id"],
        ))
        return _render_value(value)


async def resolve_entry(db, entry: dict, ctx: AuthContext, settings) -> dict:
    """Resolve an entry's references. Returns {markdown, dependencies}."""
    resolver = Resolver(db, entry, ctx, settings)
    markdown = await resolver.resolve()
    return {
        "markdown": markdown,
        "dependencies": [asdict(d) for d in resolver.dependencies],
    }
