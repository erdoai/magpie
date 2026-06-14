"""Tests for the self-contained HTML viewer."""

from magpie.export import write_bundle
from magpie.viewer import render_viewer

ENTRIES = [
    {"title": "Orders", "tags": ["sales"], "content": "See [[Customers]]."},
    {"title": "Customers", "tags": [], "content": "People."},
]
STORES = [
    {"slug": "strategy", "title": "Strategy",
     "pairs": [{"key": "wedge", "value": "simplicity", "value_type": "string"}]},
]


def test_render_is_self_contained():
    html = render_viewer(ENTRIES, STORES)
    assert html.startswith("<!doctype html>")
    # No network dependencies — everything is inline.
    assert "http://" not in html
    assert "https://" not in html
    assert "src=" not in html  # no external scripts/styles


def test_embeds_entry_and_kv_data():
    html = render_viewer(ENTRIES, STORES)
    assert "Orders" in html
    assert "Customers" in html
    assert "strategy" in html
    assert "simplicity" in html


def test_escapes_script_breakout():
    evil = [{"title": "X", "tags": [], "content": "</script><b>hi"}]
    html = render_viewer(evil, [])
    # The literal closing tag must not appear in the embedded JSON payload.
    assert "</script><b>hi" not in html
    assert "\\u003c/script>" in html


def test_write_bundle_emits_index_html(tmp_path):
    write_bundle(tmp_path, ENTRIES, STORES)
    index = tmp_path / "index.html"
    assert index.exists()
    assert index.read_text().startswith("<!doctype html>")


def test_viewer_can_be_disabled(tmp_path):
    write_bundle(tmp_path, ENTRIES, [], viewer=False)
    assert not (tmp_path / "index.html").exists()
