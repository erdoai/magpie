"""Tests for anti-drift manifest checks."""

from dataclasses import dataclass

from magpie.manifest import check_drift, normalize_slug, validate_manifest


@dataclass
class FakePair:
    key: str
    value: object = None
    value_type: str = "json"


@dataclass
class FakeStore:
    slug: str
    pairs: list = None

    def __post_init__(self):
        if self.pairs is None:
            self.pairs = []


def manifest(stores):
    return {"stores": stores}


def test_normalize_slug_collapses_separators_and_case():
    assert normalize_slug("reach-strategy") == "reachstrategy"
    assert normalize_slug("reach_strategy") == "reachstrategy"
    assert normalize_slug("Reach.Strategy") == "reachstrategy"


def test_no_manifest_only_checks_near_duplicates():
    result = check_drift([FakeStore("strategy")], None)
    assert result.ok


def test_near_duplicate_slugs_rejected_without_manifest():
    result = check_drift([FakeStore("reach-strategy"), FakeStore("reach_strategy")], None)
    assert not result.ok
    assert "Near-duplicate" in result.errors[0]


def test_declared_store_passes():
    result = check_drift([FakeStore("strategy")], manifest({"strategy": {"title": "S"}}))
    assert result.ok


def test_undeclared_store_rejected_with_suggestion():
    result = check_drift(
        [FakeStore("stratagy")], manifest({"strategy": {"title": "S"}})
    )
    assert not result.ok
    assert "not declared" in result.errors[0]
    assert "strategy" in result.errors[0]  # nearest-match suggestion


def test_separator_variant_suggests_canonical():
    result = check_drift(
        [FakeStore("reach_strategy")], manifest({"reach-strategy": {"title": "S"}})
    )
    assert not result.ok
    assert "reach-strategy" in result.errors[0]


def test_undeclared_key_warns_but_does_not_block():
    result = check_drift(
        [FakeStore("strategy", [FakePair("wedge"), FakePair("typo")])],
        manifest({"strategy": {"keys": ["wedge"]}}),
    )
    assert result.ok  # warning, not error
    assert any("typo" in w for w in result.warnings)


def test_declared_keys_all_present_no_warning():
    result = check_drift(
        [FakeStore("strategy", [FakePair("wedge")])],
        manifest({"strategy": {"keys": ["wedge", "mrr"]}}),
    )
    assert result.ok
    assert result.warnings == []


def test_validate_manifest_rejects_bad_structure():
    assert validate_manifest([])
    assert validate_manifest({"stores": "nope"})
    assert validate_manifest({"stores": {"s": {"keys": "notalist"}}})
    assert validate_manifest({"stores": {"s": {"keys": ["ok"]}}}) == []
