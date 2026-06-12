"""Wikilink parsing and link/backlink behavior tests."""

from magpie.links import normalize_target, parse_wikilinks

from .test_isolation import FakeDatabase, add_key, auth, make_client

# -- Parser --


def test_parse_title_links():
    links = parse_wikilinks("See [[Alertee Positioning]] and [[brand style]].")
    assert [(li.kind, li.normalized) for li in links] == [
        ("title", "alertee positioning"),
        ("title", "brand style"),
    ]


def test_parse_alias_url_and_resource():
    md = (
        "Check [[Alertee positioning|the positioning doc]], "
        "[[https://example.com/docs]] and [[alertee:check:42]]."
    )
    links = parse_wikilinks(md)
    assert links[0].kind == "title"
    assert links[0].display == "the positioning doc"
    assert links[0].normalized == "alertee positioning"
    assert links[1].kind == "url"
    assert links[1].target == "https://example.com/docs"
    assert links[2].kind == "resource"
    assert links[2].target == "alertee:check:42"


def test_parse_dedupes_and_skips_code():
    md = (
        "[[Foo]] again [[foo]] and [[ FOO ]]\n"
        "```\n[[in fenced code]]\n```\n"
        "and `[[inline code]]` too"
    )
    links = parse_wikilinks(md)
    assert len(links) == 1
    assert links[0].normalized == "foo"


def test_parse_ignores_empty_and_normalizes_whitespace():
    assert parse_wikilinks("[[ ]] [[|x]]") == []
    assert normalize_target("  Multi   Word\tTitle ") == "multi word title"


# -- Link sync through the API --


def test_create_entry_syncs_resolved_and_unresolved_links():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    target = db.add_entry(org_id="org-a", title="Alertee Positioning")
    client = make_client(db)

    res = client.post(
        "/api/entries",
        headers=auth("key-a"),
        json={"title": "Strategy", "content": "See [[Alertee Positioning]] and [[Nonexistent]]."},
    )
    assert res.status_code == 200
    entry_id = res.json()["id"]

    links = db.links[entry_id]
    by_norm = {li["normalized_target"]: li for li in links}
    assert by_norm["alertee positioning"]["target_type"] == "entry"
    assert by_norm["alertee positioning"]["target_id"] == target
    assert by_norm["nonexistent"]["target_type"] == "unresolved"


def test_links_do_not_resolve_across_orgs():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    db.add_entry(org_id="org-b", title="Secret Doc")
    client = make_client(db)

    res = client.post(
        "/api/entries",
        headers=auth("key-a"),
        json={"title": "Note", "content": "About [[Secret Doc]]"},
    )
    entry_id = res.json()["id"]
    (link,) = db.links[entry_id]
    assert link["target_type"] == "unresolved"
    assert link["target_id"] is None


def test_update_content_resyncs_links():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    client = make_client(db)

    res = client.post(
        "/api/entries",
        headers=auth("key-a"),
        json={"title": "Note", "content": "[[First]]"},
    )
    entry_id = res.json()["id"]
    assert db.links[entry_id][0]["normalized_target"] == "first"

    client.put(
        f"/api/entries/{entry_id}", headers=auth("key-a"), json={"content": "[[Second]]"}
    )
    assert [li["normalized_target"] for li in db.links[entry_id]] == ["second"]


def test_links_endpoint_returns_outgoing_and_backlinks():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    client = make_client(db)

    res = client.post(
        "/api/entries",
        headers=auth("key-a"),
        json={"title": "Target Doc", "content": "no links here"},
    )
    target_id = res.json()["id"]

    res = client.post(
        "/api/entries",
        headers=auth("key-a"),
        json={"title": "Source Doc", "content": "see [[Target Doc]]"},
    )
    source_id = res.json()["id"]

    out = client.get(f"/api/entries/{source_id}/links", headers=auth("key-a")).json()
    assert out["outgoing"][0]["target_id"] == target_id
    assert out["backlinks"] == []

    back = client.get(f"/api/entries/{target_id}/links", headers=auth("key-a")).json()
    assert back["outgoing"] == []
    assert back["backlinks"][0]["source_id"] == source_id
    assert back["backlinks"][0]["source_title"] == "Source Doc"


def test_unresolved_backlinks_match_by_title():
    """An entry created after being referenced still shows the backlink."""
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    client = make_client(db)

    res = client.post(
        "/api/entries",
        headers=auth("key-a"),
        json={"title": "Early Note", "content": "mentions [[Future Doc]]"},
    )
    source_id = res.json()["id"]

    res = client.post(
        "/api/entries",
        headers=auth("key-a"),
        json={"title": "Future Doc", "content": "now exists"},
    )
    future_id = res.json()["id"]

    back = client.get(f"/api/entries/{future_id}/links", headers=auth("key-a")).json()
    assert [b["source_id"] for b in back["backlinks"]] == [source_id]


def test_backlinks_do_not_leak_across_orgs():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    add_key(db, "key-b", user_id="ub", org_id="org-b")
    client = make_client(db)

    # org-b references a title that also exists in org-a
    res = client.post(
        "/api/entries",
        headers=auth("key-b"),
        json={"title": "B Note", "content": "see [[Shared Title]]"},
    )
    assert res.status_code == 200

    res = client.post(
        "/api/entries",
        headers=auth("key-a"),
        json={"title": "Shared Title", "content": "org-a's doc"},
    )
    a_entry = res.json()["id"]

    back = client.get(f"/api/entries/{a_entry}/links", headers=auth("key-a")).json()
    assert back["backlinks"] == []


def test_links_endpoint_respects_entry_visibility():
    db = FakeDatabase()
    add_key(db, "key-a", user_id="ua", org_id="org-a")
    other = db.add_entry(org_id="org-b", title="Other")
    client = make_client(db)

    assert client.get(f"/api/entries/{other}/links", headers=auth("key-a")).status_code == 404
