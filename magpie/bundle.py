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

from dataclasses import dataclass
from pathlib import Path

from magpie.frontmatter import Frontmatter, FrontmatterError, parse

# Subdirectories under a bundle root that are not entry Markdown.
RESERVED_DIRS = ("collections", "attachments")


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


def _iter_markdown(root: Path):
    """Yield ``*.md`` files under root, skipping reserved subdirectories."""
    for path in sorted(root.rglob("*.md")):
        rel_parts = path.relative_to(root).parts
        if rel_parts and rel_parts[0] in RESERVED_DIRS:
            continue
        yield path


def scan_entries(root: str | Path) -> ScanResult:
    """Scan a bundle directory for entry Markdown files.

    Every ``*.md`` file (outside reserved dirs) must carry valid Magpie
    frontmatter; files that don't are reported as errors, not silently skipped.
    """
    root = Path(root)
    if not root.is_dir():
        return ScanResult([], [BundleError(str(root), "Bundle directory not found")])

    entries: list[BundleEntry] = []
    errors: list[BundleError] = []

    for path in _iter_markdown(root):
        rel = path.relative_to(root).as_posix()
        text = path.read_text()
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
