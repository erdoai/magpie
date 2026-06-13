"""Reading a Magpie knowledge bundle from disk.

A bundle is a folder a developer authors and commits to git, then syncs to the
server with ``magpie push``. Layout:

    knowledge/
    ├── <entry>.md                 # markdown + frontmatter (entries)
    ├── collections/
    │   ├── _manifest.json          # canonical store/key registry (anti-drift)
    │   └── <slug>.json             # repo-canonical collection: { key: value }
    └── attachments/
        ├── <file>                  # binary
        └── <file>.json             # sidecar metadata

The entry's identity is its **relative path** within the bundle. Re-pushing the
same path updates the same entry rather than creating a duplicate — the repo is
the source of truth, and path-as-identity is how we keep sync deterministic
instead of guessing by content similarity.

This module is pure (filesystem in, dataclasses out, no DB) so the scan and its
error reporting can be tested without a database.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from magpie.collections import infer_value_type
from magpie.frontmatter import Frontmatter, FrontmatterError, parse

# Subdirectories under a bundle root that are not entry Markdown.
RESERVED_DIRS = ("collections", "attachments")

# Files in collections/ that are not collection stores.
COLLECTIONS_DIR = "collections"
MANIFEST_FILE = "_manifest.json"


@dataclass
class BundleEntry:
    """A single entry parsed from a bundle, keyed by its relative path."""

    path: str  # POSIX relative path from the bundle root, e.g. "sales/orders.md"
    frontmatter: Frontmatter
    body: str

    @property
    def title(self) -> str:
        """Frontmatter title, falling back to a humanized filename."""
        if self.frontmatter.title:
            return self.frontmatter.title
        stem = Path(self.path).stem
        return stem.replace("_", " ").replace("-", " ").strip() or stem


@dataclass
class BundleError:
    """A problem with one file, collected rather than raised, so push can report
    every bad file at once instead of failing on the first."""

    path: str
    message: str


@dataclass
class ScanResult:
    entries: list[BundleEntry]
    errors: list[BundleError]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass
class BundleDocument:
    """One typed key/value in a repo-canonical collection."""

    key: str
    value: object
    value_type: str


@dataclass
class BundleCollection:
    """A repo-canonical collection parsed from ``collections/<slug>.json``."""

    slug: str
    documents: list[BundleDocument] = field(default_factory=list)


@dataclass
class CollectionScanResult:
    collections: list[BundleCollection]
    errors: list[BundleError]

    @property
    def ok(self) -> bool:
        return not self.errors


# Reuse the slug grammar the server enforces (lowercase, dots, dashes, scores).
def _valid_slug(slug: str) -> bool:
    if not slug or not (slug[0].islower() or slug[0].isdigit()):
        return False
    return all(c.islower() or c.isdigit() or c in "._-" for c in slug)


def load_manifest(root: str | Path) -> tuple[dict | None, BundleError | None]:
    """Load ``collections/_manifest.json`` if present.

    Returns (manifest, error). Both None means there is no manifest (allowed —
    drift checks then fall back to near-duplicate detection only).
    """
    path = Path(root) / COLLECTIONS_DIR / MANIFEST_FILE
    if not path.is_file():
        return None, None
    rel = path.relative_to(root).as_posix()
    try:
        return json.loads(path.read_text()), None
    except json.JSONDecodeError as exc:
        return None, BundleError(rel, f"Invalid JSON: {exc}")


def parse_collection_items(items: list[tuple[str, str]]) -> CollectionScanResult:
    """Parse ``(slug, json_text)`` pairs into repo-canonical collections.

    The in-memory core shared by the disk scanner and the REST push endpoint, so
    validation and type inference live in exactly one place.
    """
    collections: list[BundleCollection] = []
    errors: list[BundleError] = []
    for slug, text in items:
        rel = f"{COLLECTIONS_DIR}/{slug}.json"
        if not _valid_slug(slug):
            errors.append(BundleError(rel, f"Invalid collection slug {slug!r}"))
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(BundleError(rel, f"Invalid JSON: {exc}"))
            continue
        if not isinstance(data, dict):
            errors.append(BundleError(rel, "Collection file must be a JSON object of key/value"))
            continue
        docs = [
            BundleDocument(key=key, value=value, value_type=infer_value_type(value))
            for key, value in data.items()
        ]
        collections.append(BundleCollection(slug=slug, documents=docs))
    return CollectionScanResult(collections=collections, errors=errors)


def scan_collections(root: str | Path) -> CollectionScanResult:
    """Scan ``collections/*.json`` for repo-canonical stores.

    Each file is a flat ``{ key: value }`` map of native JSON values; the slug
    is the filename stem and value types are inferred. ``_manifest.json`` is not
    a store and is skipped here (it drives anti-drift checks separately).
    """
    col_dir = Path(root) / COLLECTIONS_DIR
    if not col_dir.is_dir():
        return CollectionScanResult([], [])
    items = [
        (path.stem, path.read_text())
        for path in sorted(col_dir.glob("*.json"))
        if path.name != MANIFEST_FILE
    ]
    return parse_collection_items(items)


def _iter_markdown(root: Path):
    """Yield ``*.md`` files under root, skipping reserved subdirectories."""
    for path in sorted(root.rglob("*.md")):
        rel_parts = path.relative_to(root).parts
        if rel_parts and rel_parts[0] in RESERVED_DIRS:
            continue
        yield path


def parse_entry_items(items: list[tuple[str, str]]) -> ScanResult:
    """Parse ``(relpath, text)`` pairs into entries.

    The in-memory core shared by the disk scanner and the REST push endpoint —
    frontmatter validation lives in exactly one place.
    """
    entries: list[BundleEntry] = []
    errors: list[BundleError] = []
    for rel, text in items:
        if not text.strip():
            errors.append(BundleError(rel, "Empty file"))
            continue
        try:
            meta, body = parse(text)
        except FrontmatterError as exc:
            errors.append(BundleError(rel, str(exc)))
            continue
        if not body.strip():
            errors.append(BundleError(rel, "Entry has frontmatter but no body content"))
            continue
        entries.append(BundleEntry(path=rel, frontmatter=meta, body=body))
    return ScanResult(entries=entries, errors=errors)


def scan_entries(root: str | Path) -> ScanResult:
    """Scan a bundle directory for entry Markdown files.

    Every ``*.md`` file (outside reserved dirs) must carry valid Magpie
    frontmatter; files that don't are reported as errors, not silently skipped.
    """
    root = Path(root)
    if not root.is_dir():
        return ScanResult([], [BundleError(str(root), "Bundle directory not found")])
    items = [(p.relative_to(root).as_posix(), p.read_text()) for p in _iter_markdown(root)]
    return parse_entry_items(items)
