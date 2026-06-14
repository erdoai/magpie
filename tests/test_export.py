"""Export rendering + round-trip through the bundle scanner."""

import json

from magpie.bundle import load_manifest, scan_entries, scan_kv_stores
from magpie.export import (
    build_manifest,
    entry_path,
    render_entry,
    render_kv_store,
    slugify,
    write_bundle,
)
from magpie.frontmatter import parse


def test_slugify():
    assert slugify("Alertee Positioning!") == "alertee-positioning"
    assert slugify("  weird __ name  ") == "weird-name"
    assert slugify("") == "entry"


def test_entry_path_prefers_source_path():
    assert entry_path({"source_path": "sales/orders.md", "title": "Orders"}) == "sales/orders.md"
    assert entry_path({"title": "Brand Guide"}) == "brand-guide.md"


def test_render_entry_roundtrips_through_parser():
    entry = {
        "title": "Alertee positioning",
        "content": "# Heading\n\nThe wedge is simplicity.",
        "tags": ["reach", "positioning"],
        "source": "strategy",
    }
    meta, body = parse(render_entry(entry))
    assert meta.title == "Alertee positioning"
    assert meta.tags == ["reach", "positioning"]
    assert meta.source == "strategy"
    assert "The wedge is simplicity." in body


def test_render_entry_emits_archived_when_archived_at_set():
    out = render_entry({"title": "X", "content": "body", "archived_at": "2026-01-01T00:00:00Z"})
    assert "archived: true" in out
    meta, _ = parse(out)
    assert meta.archived is True


def test_render_entry_omits_archived_when_active():
    out = render_entry({"title": "X", "content": "body", "archived_at": None})
    assert "archived:" not in out
    meta, _ = parse(out)
    assert meta.archived is False


def test_build_manifest_sorts_and_includes_keys():
    manifest = build_manifest(
        [
            {"slug": "strategy", "title": "Strat", "keys": ["mrr", "wedge"]},
            {"slug": "brand", "title": "Brand", "keys": ["logo"]},
        ]
    )
    assert list(manifest["stores"]) == ["brand", "strategy"]
    assert manifest["stores"]["strategy"]["keys"] == ["mrr", "wedge"]


def test_full_bundle_roundtrips(tmp_path):
    entries = [
        {
            "title": "Orders",
            "content": "One row per order.",
            "tags": ["sales"],
            "source": None,
            "source_path": "sales/orders.md",
        },
    ]
    stores = [
        {
            "slug": "strategy",
            "title": "Strategy",
            "pairs": [
                {"key": "wedge", "value": "simplicity"},
                {"key": "mrr", "value": 4200},
            ],
        }
    ]
    write_bundle(tmp_path, entries, stores)

    # Entries scan back cleanly.
    scan = scan_entries(tmp_path)
    assert scan.ok
    assert scan.entries[0].path == "sales/orders.md"
    assert scan.entries[0].title == "Orders"

    # KV stores scan back with inferred types.
    kv = scan_kv_stores(tmp_path)
    assert kv.ok
    by_key = {d.key: d.value for d in kv.stores[0].pairs}
    assert by_key == {"wedge": "simplicity", "mrr": 4200}

    # Manifest is valid and declares the store.
    manifest, err = load_manifest(tmp_path)
    assert err is None
    assert "strategy" in manifest["stores"]


def test_collision_paths_disambiguated(tmp_path):
    entries = [
        {"title": "Same Name", "content": "a"},
        {"title": "Same Name", "content": "b"},
    ]
    write_bundle(tmp_path, entries, [])
    files = sorted(p.name for p in tmp_path.glob("*.md"))
    assert files == ["same-name-2.md", "same-name.md"]


def test_no_manifest_when_no_kv_stores(tmp_path):
    write_bundle(tmp_path, [{"title": "X", "content": "y"}], [])
    assert not (tmp_path / "kv" / "_manifest.json").exists()


def test_render_kv_store_is_sorted_json(tmp_path):
    out = render_kv_store([{"key": "b", "value": 2}, {"key": "a", "value": 1}])
    assert list(json.loads(out)) == ["a", "b"]  # sort_keys
