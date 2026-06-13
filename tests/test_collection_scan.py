"""Tests for repo-canonical collection scanning and type inference."""

import json
from pathlib import Path

from magpie.bundle import scan_collections
from magpie.collections import infer_value_type


def write_collection(root: Path, slug: str, data: dict) -> None:
    col_dir = root / "collections"
    col_dir.mkdir(parents=True, exist_ok=True)
    (col_dir / f"{slug}.json").write_text(json.dumps(data))


def test_infer_value_type_covers_natives():
    assert infer_value_type(True) == "boolean"
    assert infer_value_type(4200) == "integer"
    assert infer_value_type(3.14) == "float"
    assert infer_value_type("hello") == "string"
    assert infer_value_type({"a": 1}) == "json"
    assert infer_value_type([1, 2]) == "json"
    assert infer_value_type(None) == "json"


def test_bool_not_inferred_as_integer():
    # True is an int in Python; order matters.
    assert infer_value_type(True) == "boolean"
    assert infer_value_type(False) == "boolean"


def test_scans_collection_with_inferred_types(tmp_path):
    write_collection(tmp_path, "strategy", {"wedge": "simplicity", "mrr": 4200, "live": True})
    result = scan_collections(tmp_path)
    assert result.ok
    assert len(result.collections) == 1
    col = result.collections[0]
    assert col.slug == "strategy"
    by_key = {d.key: (d.value, d.value_type) for d in col.documents}
    assert by_key["wedge"] == ("simplicity", "string")
    assert by_key["mrr"] == (4200, "integer")
    assert by_key["live"] == (True, "boolean")


def test_skips_manifest(tmp_path):
    write_collection(tmp_path, "strategy", {"a": 1})
    (tmp_path / "collections" / "_manifest.json").write_text(json.dumps({"stores": {}}))
    result = scan_collections(tmp_path)
    assert {c.slug for c in result.collections} == {"strategy"}


def test_reports_invalid_json(tmp_path):
    col_dir = tmp_path / "collections"
    col_dir.mkdir()
    (col_dir / "broken.json").write_text("{not valid")
    result = scan_collections(tmp_path)
    assert not result.ok
    assert "Invalid JSON" in result.errors[0].message


def test_reports_non_object_file(tmp_path):
    col_dir = tmp_path / "collections"
    col_dir.mkdir()
    (col_dir / "list.json").write_text(json.dumps([1, 2, 3]))
    result = scan_collections(tmp_path)
    assert not result.ok
    assert "must be a JSON object" in result.errors[0].message


def test_no_collections_dir_is_empty_not_error(tmp_path):
    result = scan_collections(tmp_path)
    assert result.ok
    assert result.collections == []
