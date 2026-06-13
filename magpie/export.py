"""Writing a Magpie knowledge bundle to disk (`magpie export`).

The inverse of :mod:`magpie.bundle`: take entries and repo-canonical
collections from the server and render a folder a developer can read, diff,
and re-``push``. Only repo-canonical collections are exported — live
(server-canonical) stores are deliberately left out, so an export never drags
runtime data into git.

The rendering functions here are pure (data in, strings/paths out) so they can
be round-tripped against the parser in tests without a database.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from magpie.frontmatter import CATEGORIES, Frontmatter, serialize

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(title: str) -> str:
    """A filesystem-safe stem from a title (lowercase, dash-separated)."""
    slug = _SLUG_STRIP.sub("-", title.lower()).strip("-")
    return slug or "entry"


def entry_path(entry: dict) -> str:
    """Where an entry's Markdown file lives in the bundle.

    Re-uses the original ``source_path`` when the entry came from a bundle, so
    export→push round-trips to the same file; otherwise derives one from title.
    """
    src = entry.get("source_path")
    if src:
        return src
    return f"{slugify(entry.get('title') or 'entry')}.md"


def render_entry(entry: dict) -> str:
    """Render an entry dict as frontmatter + body Markdown."""
    category = entry.get("category") or "resource"
    if category not in CATEGORIES:
        category = "resource"
    meta = Frontmatter(
        category=category,
        title=entry.get("title") or None,
        tags=list(entry.get("tags") or []),
        source=entry.get("source") or None,
    )
    return serialize(meta, entry.get("content") or "")


def render_collection(documents: list[dict]) -> str:
    """Render a repo collection's documents as a flat ``{key: value}`` JSON file."""
    data = {doc["key"]: doc["value"] for doc in documents}
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def build_manifest(collections: list[dict]) -> dict:
    """Build a manifest registry from exported repo collections.

    ``collections`` is a list of ``{"slug", "title", "keys"}`` dicts.
    """
    stores = {}
    for col in sorted(collections, key=lambda c: c["slug"]):
        stores[col["slug"]] = {
            "title": col.get("title") or col["slug"],
            "keys": sorted(col.get("keys") or []),
        }
    return {"stores": stores}


def _unique_path(rel: str, used: set[str]) -> str:
    """Disambiguate a colliding relative path with a numeric suffix."""
    if rel not in used:
        used.add(rel)
        return rel
    stem, _, ext = rel.rpartition(".")
    n = 2
    while True:
        candidate = f"{stem}-{n}.{ext}" if ext else f"{rel}-{n}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        n += 1


def write_bundle(root: str | Path, entries: list[dict], collections: list[dict]) -> dict:
    """Write a bundle to ``root``.

    ``collections`` is a list of ``{"slug", "title", "documents"}`` dicts (only
    repo-canonical stores). Returns a summary dict of what was written.
    """
    root = Path(root)
    (root / "collections").mkdir(parents=True, exist_ok=True)

    used: set[str] = set()
    for entry in entries:
        rel = _unique_path(entry_path(entry), used)
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_entry(entry))

    manifest_cols = []
    for col in collections:
        docs = col["documents"]
        (root / "collections" / f"{col['slug']}.json").write_text(render_collection(docs))
        manifest_cols.append(
            {"slug": col["slug"], "title": col.get("title"), "keys": [d["key"] for d in docs]}
        )

    if manifest_cols:
        manifest = build_manifest(manifest_cols)
        (root / "collections" / "_manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        )

    return {"entries": len(entries), "collections": len(collections)}
