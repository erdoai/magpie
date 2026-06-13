"""Wikilink parsing and link-edge syncing.

Entries may reference other knowledge in Markdown via ``[[...]]``:

- ``[[Alertee positioning]]`` — link to another entry by title.
- ``[[Alertee positioning|the positioning doc]]`` — with display text.
- ``[[https://example.com/docs]]`` — external URL.
- ``[[alertee:check:42]]`` — product resource reference (app:type:id).

On every entry save the Markdown is reparsed and the entry's outgoing
link edges are replaced. Title links that match an accessible entry are
stored resolved (``target_type='entry'``); the rest stay ``unresolved``
and still match backlinks by normalized title once the target exists.
"""

import re
from dataclasses import dataclass

WIKILINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
URL_RE = re.compile(r"^https?://", re.IGNORECASE)
# app:type:id product references, e.g. alertee:check:42, reach:run:abc
RESOURCE_RE = re.compile(r"^[a-z][a-z0-9_-]*:[a-z][a-z0-9_-]*:\S+$", re.IGNORECASE)
FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")


def normalize_target(target: str) -> str:
    return " ".join(target.split()).lower()


@dataclass
class ParsedLink:
    target: str  # as written (left of |)
    display: str  # display text (right of |, or target)
    kind: str  # title, url, resource
    normalized: str


def parse_wikilinks(markdown: str) -> list[ParsedLink]:
    """Extract [[wikilinks]] from Markdown, skipping code blocks.

    Deduped by normalized target, first occurrence wins.
    """
    text = FENCED_CODE_RE.sub("", markdown)
    text = INLINE_CODE_RE.sub("", text)

    links: list[ParsedLink] = []
    seen: set[str] = set()
    for match in WIKILINK_RE.finditer(text):
        raw = match.group(1).strip()
        if not raw:
            continue
        target, _, display = raw.partition("|")
        target = target.strip()
        display = display.strip() or target
        if not target:
            continue

        if URL_RE.match(target):
            kind = "url"
        elif RESOURCE_RE.match(target):
            kind = "resource"
        else:
            kind = "title"

        normalized = normalize_target(target)
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append(ParsedLink(target=target, display=display, kind=kind,
                                normalized=normalized))
    return links


async def sync_entry_links(db, entry_id: str) -> None:
    """Reparse an entry's Markdown and replace its outgoing link edges."""
    # Server-internal link maintenance for an already-authorized entry.
    entry = await db.get_entry(entry_id, trusted=True)
    if not entry:
        return

    parsed = parse_wikilinks(entry.get("content") or "")

    title_targets = [p.normalized for p in parsed if p.kind == "title"]
    resolved: dict[str, str] = {}
    if title_targets:
        resolved = await db.find_entries_by_titles(
            title_targets,
            user_id=entry.get("user_id"),
            org_id=entry.get("org_id"),
        )

    links = []
    for p in parsed:
        if p.kind == "url":
            link = {"target_type": "url", "target_id": None, "target_ref": p.target}
        elif p.kind == "resource":
            link = {"target_type": "resource", "target_id": None, "target_ref": p.target}
        else:
            target_id = resolved.get(p.normalized)
            if target_id == entry_id:
                continue  # self-link
            if target_id:
                link = {"target_type": "entry", "target_id": target_id, "target_ref": None}
            else:
                link = {"target_type": "unresolved", "target_id": None, "target_ref": None}
        link["link_text"] = p.display
        link["normalized_target"] = p.normalized
        links.append(link)

    await db.replace_entry_links(entry_id, entry.get("org_id"), links)
