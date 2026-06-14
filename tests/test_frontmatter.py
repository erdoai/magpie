"""Tests for the strict, versioned, closed frontmatter spec."""

import pytest

from magpie.frontmatter import (
    FRONTMATTER_VERSION,
    Frontmatter,
    FrontmatterError,
    parse,
    serialize,
    split_frontmatter,
)


def doc(frontmatter: str, body: str = "Body text.") -> str:
    return f"---\n{frontmatter}\n---\n\n{body}\n"


def test_parses_minimal_valid_frontmatter():
    meta, body = parse(doc("magpie_version: 1"))
    assert meta.magpie_version == "1"
    assert meta.title is None
    assert meta.tags == []
    assert meta.source is None
    assert meta.archived is False
    assert body.strip() == "Body text."


def test_parses_all_fields_with_inline_tags():
    meta, _ = parse(
        doc(
            "magpie_version: 1\ntitle: Alertee positioning\n"
            "tags: [reach, positioning]\nsource: strategy-doc"
        )
    )
    assert meta.title == "Alertee positioning"
    assert meta.tags == ["reach", "positioning"]
    assert meta.source == "strategy-doc"


def test_parses_archived_flag():
    meta, _ = parse(doc("magpie_version: 1\narchived: true"))
    assert meta.archived is True


def test_parses_yaml_block_tag_list():
    meta, _ = parse(
        doc("magpie_version: 1\ntags:\n  - one\n  - two\n  - three")
    )
    assert meta.tags == ["one", "two", "three"]


def test_strips_quotes_from_values():
    meta, _ = parse(doc('magpie_version: "1"\ntitle: "Quoted Title"'))
    assert meta.title == "Quoted Title"


def test_rejects_missing_frontmatter():
    with pytest.raises(FrontmatterError, match="Missing frontmatter"):
        parse("# Just a heading\n\nNo frontmatter here.")


def test_rejects_unterminated_frontmatter():
    with pytest.raises(FrontmatterError, match="Unterminated"):
        parse("---\nmagpie_version: 1\n\nno closing fence")


def test_rejects_unknown_field():
    with pytest.raises(FrontmatterError, match="Unknown frontmatter field"):
        parse(doc("magpie_version: 1\nmrr: 4200"))


def test_rejects_missing_required_fields():
    with pytest.raises(FrontmatterError, match="Missing required"):
        parse(doc("title: No version"))


def test_rejects_unsupported_version():
    with pytest.raises(FrontmatterError, match="Unsupported magpie_version"):
        parse(doc("magpie_version: 99"))


def test_rejects_category_as_unknown_field():
    # `category` was removed from the spec; it is now an off-contract field.
    with pytest.raises(FrontmatterError, match="Unknown frontmatter field"):
        parse(doc("magpie_version: 1\ncategory: resource"))


def test_rejects_duplicate_key():
    with pytest.raises(FrontmatterError, match="Duplicate"):
        parse(doc("magpie_version: 1\ntitle: a\ntitle: b"))


def test_split_returns_none_without_fence():
    block, body = split_frontmatter("no fence here")
    assert block is None
    assert body == "no fence here"


def test_serialize_roundtrips():
    meta = Frontmatter(
        title="Round Trip",
        tags=["a", "b"],
        source="src",
    )
    rendered = serialize(meta, "# Heading\n\nSome body.")
    reparsed, body = parse(rendered)
    assert reparsed == meta
    assert "# Heading" in body
    assert "Some body." in body


def test_serialize_roundtrips_archived():
    meta = Frontmatter(title="Done", archived=True)
    rendered = serialize(meta, "Body.")
    assert "archived: true" in rendered
    reparsed, _ = parse(rendered)
    assert reparsed == meta
    assert reparsed.archived is True


def test_serialize_omits_empty_fields():
    rendered = serialize(Frontmatter(), "Body.")
    assert "title:" not in rendered
    assert "tags:" not in rendered
    assert "source:" not in rendered
    assert "archived:" not in rendered
    assert f"magpie_version: {FRONTMATTER_VERSION}" in rendered
