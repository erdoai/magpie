"""Tests for repo-canonical kv store scanning and type inference."""

import json
from pathlib import Path

from magpie.bundle import scan_kv_stores
from magpie.kv import infer_value_type


def write_kv_store(root: Path, slug: str, data: dict) -> None:
    kv_dir = root / "kv"
    kv_dir.mkdir(parents=True, exist_ok=True)
    (kv_dir / f"{slug}.json").write_text(json.dumps(data))


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


def test_scans_store_with_inferred_types(tmp_path):
    write_kv_store(tmp_path, "strategy", {"wedge": "simplicity", "mrr": 4200, "live": True})
    result = scan_kv_stores(tmp_path)
    assert result.ok
    assert len(result.stores) == 1
    store = result.stores[0]
    assert store.slug == "strategy"
    by_key = {d.key: (d.value, d.value_type) for d in store.pairs}
    assert by_key["wedge"] == ("simplicity", "string")
    assert by_key["mrr"] == (4200, "integer")
    assert by_key["live"] == (True, "boolean")


def test_skips_manifest(tmp_path):
    write_kv_store(tmp_path, "strategy", {"a": 1})
    (tmp_path / "kv" / "_manifest.json").write_text(json.dumps({"stores": {}}))
    result = scan_kv_stores(tmp_path)
    assert {c.slug for c in result.stores} == {"strategy"}


def test_reports_invalid_json(tmp_path):
    kv_dir = tmp_path / "kv"
    kv_dir.mkdir()
    (kv_dir / "broken.json").write_text("{not valid")
    result = scan_kv_stores(tmp_path)
    assert not result.ok
    assert "Invalid JSON" in result.errors[0].message


def test_reports_non_object_file(tmp_path):
    kv_dir = tmp_path / "kv"
    kv_dir.mkdir()
    (kv_dir / "list.json").write_text(json.dumps([1, 2, 3]))
    result = scan_kv_stores(tmp_path)
    assert not result.ok
    assert "must be a JSON object" in result.errors[0].message


def test_no_kv_dir_is_empty_not_error(tmp_path):
    result = scan_kv_stores(tmp_path)
    assert result.ok
    assert result.stores == []
