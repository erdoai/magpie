"""Tests for the bundle scanner (pure, no DB)."""

from pathlib import Path

from magpie.bundle import parse_collection_items, parse_entry_items, scan_entries


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


VALID = "---\nmagpie_version: 1\ncategory: resource\ntitle: Orders\n---\n\nOne row per order.\n"


def test_scans_valid_entries(tmp_path):
    write(tmp_path, "orders.md", VALID)
    write(tmp_path, "sales/customers.md", VALID.replace("Orders", "Customers"))
    result = scan_entries(tmp_path)
    assert result.ok
    assert {e.path for e in result.entries} == {"orders.md", "sales/customers.md"}
    assert {e.title for e in result.entries} == {"Orders", "Customers"}


def test_path_is_relative_posix(tmp_path):
    write(tmp_path, "deep/nested/thing.md", VALID)
    result = scan_entries(tmp_path)
    assert result.entries[0].path == "deep/nested/thing.md"


def test_skips_reserved_dirs(tmp_path):
    write(tmp_path, "real.md", VALID)
    write(tmp_path, "collections/strategy.md", VALID)  # not an entry
    write(tmp_path, "attachments/notes.md", VALID)
    result = scan_entries(tmp_path)
    assert [e.path for e in result.entries] == ["real.md"]


def test_reports_missing_frontmatter_as_error(tmp_path):
    write(tmp_path, "good.md", VALID)
    write(tmp_path, "bad.md", "# No frontmatter\n\njust prose")
    result = scan_entries(tmp_path)
    assert not result.ok
    assert [e.path for e in result.entries] == ["good.md"]
    assert any(err.path == "bad.md" for err in result.errors)


def test_reports_unknown_field_as_error(tmp_path):
    write(
        tmp_path,
        "drift.md",
        "---\nmagpie_version: 1\ncategory: resource\nmrr: 4200\n---\n\nbody\n",
    )
    result = scan_entries(tmp_path)
    assert not result.ok
    assert "Unknown frontmatter field" in result.errors[0].message


def test_reports_empty_and_bodyless_files(tmp_path):
    write(tmp_path, "empty.md", "   \n")
    write(tmp_path, "nobody.md", "---\nmagpie_version: 1\ncategory: resource\n---\n\n")
    result = scan_entries(tmp_path)
    paths = {e.path for e in result.errors}
    assert paths == {"empty.md", "nobody.md"}


def test_title_falls_back_to_filename(tmp_path):
    write(
        tmp_path,
        "weekly-active-users.md",
        "---\nmagpie_version: 1\ncategory: resource\n---\n\nbody\n",
    )
    result = scan_entries(tmp_path)
    assert result.entries[0].title == "weekly active users"


def test_missing_directory_is_an_error(tmp_path):
    result = scan_entries(tmp_path / "does-not-exist")
    assert not result.ok
    assert "not found" in result.errors[0].message


# In-memory entry points (shared with the REST push endpoint) --------------


def test_parse_entry_items_from_memory():
    result = parse_entry_items([("a.md", VALID), ("bad.md", "no frontmatter")])
    assert [e.path for e in result.entries] == ["a.md"]
    assert result.errors[0].path == "bad.md"


def test_parse_collection_items_from_memory():
    result = parse_collection_items([("strategy", '{"mrr": 4200}'), ("bad", "{nope")])
    assert result.collections[0].slug == "strategy"
    assert result.collections[0].documents[0].value_type == "integer"
    assert result.errors[0].path == "collections/bad.json"
