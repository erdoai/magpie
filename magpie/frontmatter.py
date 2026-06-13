"""Magpie's frontmatter spec for entry Markdown bundles.

This is a strict, versioned, **closed** contract — not a free-for-all bag of
keys. A bundle file is Markdown with a YAML-style frontmatter block fenced by
``---`` lines:

    ---
    magpie_version: 1
    category: resource
    title: Alertee positioning
    tags: [reach, positioning]
    source: strategy-doc
    ---

    # Alertee positioning

    Body markdown here...

Only the fields below are allowed. Unknown keys are rejected so the frontmatter
never drifts into a second, unvalidated key/value store — structured data
belongs in a collection, not here.

This spec is deliberately self-contained (no YAML dependency): the field set is
small and known, so we parse and validate it explicitly. That strictness is the
point — it is what lets us reject anything off-contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Bump when the field set or semantics change; the loader keys migrations off it.
FRONTMATTER_VERSION = "1"

# Entry categories (PARA). Mirrors the `entries.category` column.
CATEGORIES = ("project", "area", "resource", "archive")

# The closed field set. Anything outside this is rejected on parse.
ALLOWED_FIELDS = ("magpie_version", "category", "title", "tags", "source")
REQUIRED_FIELDS = ("magpie_version", "category")


class FrontmatterError(ValueError):
    """Raised when a frontmatter block is missing, malformed, or off-contract."""


@dataclass
class Frontmatter:
    """A validated frontmatter block."""

    category: str
    title: str | None = None
    tags: list[str] = field(default_factory=list)
    source: str | None = None
    magpie_version: str = FRONTMATTER_VERSION


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_tags(raw: str) -> list[str]:
    """Parse an inline tag list: ``[a, b, c]`` or a bare ``a, b, c``."""
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    if not raw.strip():
        return []
    return [_strip_quotes(part) for part in raw.split(",") if part.strip()]


def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Split a document into (frontmatter_block, body).

    Returns ``(None, text)`` when there is no frontmatter fence. The frontmatter
    block is the raw text between the opening and closing ``---`` lines.
    """
    if not text.startswith("---"):
        return None, text
    # The opening fence must be a line of its own.
    rest = text[3:]
    if rest[:1] not in ("\n", "\r"):
        return None, text
    lines = text.splitlines()
    # lines[0] == "---"; find the closing fence.
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            block = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1 :])
            return block, body.lstrip("\n")
    raise FrontmatterError("Unterminated frontmatter block (missing closing '---').")


def _parse_block(block: str) -> dict[str, str]:
    """Parse a frontmatter block into raw string values, keyed by field.

    Tags using YAML block syntax (``tags:`` followed by ``  - foo`` lines) are
    folded into a single inline ``[...]`` value so downstream parsing is uniform.
    """
    raw: dict[str, str] = {}
    current_list_key: str | None = None
    list_items: list[str] = []

    def flush_list() -> None:
        nonlocal current_list_key, list_items
        if current_list_key is not None:
            raw[current_list_key] = "[" + ", ".join(list_items) + "]"
            current_list_key = None
            list_items = []

    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        stripped = line.strip()
        # Continuation of a YAML block list (``  - item``).
        if current_list_key is not None and stripped.startswith("- "):
            list_items.append(_strip_quotes(stripped[2:]))
            continue
        flush_list()
        if ":" not in line:
            raise FrontmatterError(f"Malformed frontmatter line (no ':'): {line!r}")
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value == "":
            # Possibly the header of a YAML block list; collect following items.
            current_list_key = key
            list_items = []
            continue
        if key in raw:
            raise FrontmatterError(f"Duplicate frontmatter key: {key!r}")
        raw[key] = value
    flush_list()
    return raw


def validate(raw: dict[str, str]) -> Frontmatter:
    """Validate raw frontmatter fields against the closed spec."""
    unknown = [k for k in raw if k not in ALLOWED_FIELDS]
    if unknown:
        raise FrontmatterError(
            f"Unknown frontmatter field(s): {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(ALLOWED_FIELDS)}. "
            "Structured data belongs in a collection, not the frontmatter."
        )

    missing = [k for k in REQUIRED_FIELDS if k not in raw]
    if missing:
        raise FrontmatterError(f"Missing required frontmatter field(s): {', '.join(missing)}.")

    version = _strip_quotes(raw["magpie_version"])
    if version != FRONTMATTER_VERSION:
        raise FrontmatterError(
            f"Unsupported magpie_version {version!r}; this build speaks "
            f"version {FRONTMATTER_VERSION}."
        )

    category = _strip_quotes(raw["category"])
    if category not in CATEGORIES:
        raise FrontmatterError(
            f"Invalid category {category!r}. One of: {', '.join(CATEGORIES)}."
        )

    title = _strip_quotes(raw["title"]) if "title" in raw else None
    source = _strip_quotes(raw["source"]) if "source" in raw else None
    tags = _parse_tags(raw["tags"]) if "tags" in raw else []

    return Frontmatter(
        category=category,
        title=title or None,
        tags=tags,
        source=source or None,
        magpie_version=version,
    )


def parse(text: str) -> tuple[Frontmatter, str]:
    """Parse a Magpie bundle document into (frontmatter, body).

    Raises :class:`FrontmatterError` if the frontmatter is missing or off-spec.
    """
    block, body = split_frontmatter(text)
    if block is None:
        raise FrontmatterError(
            "Missing frontmatter block. A Magpie entry file must start with a "
            "'---' fenced frontmatter (magpie_version + category required)."
        )
    return validate(_parse_block(block)), body


def serialize(meta: Frontmatter, body: str) -> str:
    """Render a frontmatter + body document for export.

    Emits only populated fields, in a stable order, so exports diff cleanly.
    """
    lines = ["---", f"magpie_version: {meta.magpie_version}", f"category: {meta.category}"]
    if meta.title:
        lines.append(f"title: {meta.title}")
    if meta.tags:
        lines.append("tags: [" + ", ".join(meta.tags) + "]")
    if meta.source:
        lines.append(f"source: {meta.source}")
    lines.append("---")
    document = "\n".join(lines)
    body = body.strip("\n")
    if body:
        document += "\n\n" + body + "\n"
    else:
        document += "\n"
    return document
