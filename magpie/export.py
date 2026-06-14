"""Writing a Magpie knowledge bundle to disk (`magpie export`).

The inverse of :mod:`magpie.bundle`: take entries and repo-canonical
kv stores from the server and render a folder a developer can read, diff,
and re-``push``. Only repo-canonical kv stores are exported — live
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
from magpie.viewer import render_viewer

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


def render_kv_store(pairs: list[dict]) -> str:
    """Render a repo kv store's pairs as a flat ``{key: value}`` JSON file."""
    data = {pair["key"]: pair["value"] for pair in pairs}
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def build_manifest(stores: list[dict]) -> dict:
    """Build a manifest registry from exported repo kv stores.

    ``stores`` is a list of ``{"slug", "title", "keys"}`` dicts.
    """
    out = {}
    for store in sorted(stores, key=lambda s: s["slug"]):
        out[store["slug"]] = {
            "title": store.get("title") or store["slug"],
            "keys": sorted(store.get("keys") or []),
        }
    return {"stores": out}


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


def render_bundle(
    entries: list[dict],
    stores: list[dict],
    viewer: bool = True,
) -> dict[str, str]:
    """Render a whole bundle in memory as ``{relative_path: file_content}``.

    The single source of bundle rendering, shared by the local writer
    (``write_bundle``) and the REST export endpoint (which returns these files
    for a thin client to write). ``stores`` is a list of
    ``{"slug", "title", "pairs"}`` dicts (repo-canonical only).
    """
    files: dict[str, str] = {}

    used: set[str] = set()
    for entry in entries:
        rel = _unique_path(entry_path(entry), used)
        files[rel] = render_entry(entry)

    manifest_stores = []
    for store in stores:
        pairs = store["pairs"]
        files[f"kv/{store['slug']}.json"] = render_kv_store(pairs)
        manifest_stores.append(
            {"slug": store["slug"], "title": store.get("title"), "keys": [p["key"] for p in pairs]}
        )

    if manifest_stores:
        manifest = build_manifest(manifest_stores)
        files["kv/_manifest.json"] = (
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
        )

    if viewer:
        files["index.html"] = render_viewer(entries, stores)

    return files


def write_bundle(
    root: str | Path,
    entries: list[dict],
    stores: list[dict],
    viewer: bool = True,
) -> dict:
    """Write a bundle to ``root`` on disk. Returns a summary of what was written."""
    root = Path(root)
    for rel, content in render_bundle(entries, stores, viewer=viewer).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return {"entries": len(entries), "stores": len(stores)}
