"""Self-contained static HTML viewer for an exported bundle.

Renders a single ``index.html`` with the bundle's entries and kv stores
embedded as JSON — no backend, no build step, no CDN. Open it by double-clicking
and browse the knowledge as a linked graph offline. It pairs with
``magpie export``: a bundle plus this file is a portable, browsable artifact and
makes the "you're not locked in" story tangible.

``render_viewer`` is pure (data in, HTML string out) so it is testable and never
touches the network or filesystem.
"""

from __future__ import annotations

import json

# Vanilla JS/CSS only — deliberately no external dependencies so the file works
# from file:// with no network. The embedded bundle is read from a JSON script
# tag; "<" is escaped in the JSON so a "</script>" in content can't break out.
_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Magpie bundle</title>
<style>
  :root { --bg:#0f1115; --panel:#171a21; --ink:#e6e8eb; --muted:#9aa0aa; --accent:#7aa2f7; --line:#272b34; }
  * { box-sizing: border-box; }
  body { margin:0; font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; background:var(--bg); color:var(--ink); }
  #app { display:grid; grid-template-columns:300px 1fr; height:100vh; }
  #side { border-right:1px solid var(--line); overflow:auto; padding:16px; }
  #main { overflow:auto; padding:28px 36px; }
  h1.brand { font-size:15px; letter-spacing:.04em; text-transform:uppercase; color:var(--muted); margin:0 0 16px; }
  .group { font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); margin:18px 0 6px; }
  a.item { display:block; padding:5px 8px; border-radius:6px; color:var(--ink); text-decoration:none; cursor:pointer; }
  a.item:hover { background:var(--panel); }
  a.item.active { background:var(--accent); color:#0f1115; }
  .tag { display:inline-block; font-size:11px; color:var(--muted); border:1px solid var(--line); border-radius:10px; padding:1px 8px; margin:0 4px 4px 0; }
  .meta { color:var(--muted); font-size:12px; margin-bottom:18px; }
  .body h1,.body h2,.body h3 { line-height:1.25; }
  .body code { background:var(--panel); padding:1px 5px; border-radius:4px; }
  .body pre { background:var(--panel); padding:12px; border-radius:8px; overflow:auto; }
  .wl { color:var(--accent); cursor:pointer; text-decoration:none; border-bottom:1px dotted var(--accent); }
  .links { margin-top:24px; border-top:1px solid var(--line); padding-top:14px; }
  .links h4 { margin:0 0 6px; font-size:12px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); }
  table.kv { border-collapse:collapse; width:100%; }
  table.kv td { border-bottom:1px solid var(--line); padding:6px 8px; vertical-align:top; }
  table.kv td.k { color:var(--accent); white-space:nowrap; width:1%; }
  .type { color:var(--muted); font-size:11px; }
  .empty { color:var(--muted); }
</style>
</head>
<body>
<div id="app">
  <div id="side"><h1 class="brand">Magpie</h1><div id="nav"></div></div>
  <div id="main"></div>
</div>
<script type="application/json" id="bundle">__BUNDLE__</script>
<script>
const DATA = JSON.parse(document.getElementById('bundle').textContent);
const esc = s => String(s == null ? '' : s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const norm = s => String(s||'').trim().toLowerCase();
const byTitle = {};
DATA.entries.forEach((e,i) => { e._i = i; byTitle[norm(e.title)] = i; });

// Compute link edges from [[wikilinks]] in entry bodies.
DATA.entries.forEach(e => { e._out = []; e._back = []; });
DATA.entries.forEach(e => {
  const seen = new Set();
  (e.content||'').replace(/\\[\\[([^\\]]+)\\]\\]/g, (_, raw) => {
    const t = norm(raw.split('|')[0]);
    if (byTitle[t] != null && !seen.has(t)) { seen.add(t); e._out.push(byTitle[t]); DATA.entries[byTitle[t]]._back.push(e._i); }
    return _;
  });
});

function mdToHtml(md) {
  const lines = esc(md).split(/\\n/); let html = ''; let inPre = false;
  for (let ln of lines) {
    if (ln.trim().startsWith('```')) { inPre = !inPre; html += inPre ? '<pre>' : '</pre>'; continue; }
    if (inPre) { html += ln + '\\n'; continue; }
    let h = ln.match(/^(#{1,3})\\s+(.*)$/);
    if (h) { const n = h[1].length; html += `<h${n}>${h[2]}</h${n}>`; continue; }
    if (!ln.trim()) { html += ''; continue; }
    ln = ln.replace(/\\[\\[([^\\]]+)\\]\\]/g, (_, raw) => {
      const [tgt, disp] = raw.split('|'); const i = byTitle[norm(tgt)];
      const label = esc(disp || tgt);
      return i != null ? `<a class="wl" data-i="${i}">${label}</a>` : `<span class="wl" style="opacity:.6">${label}</span>`;
    }).replace(/\\*\\*([^*]+)\\*\\*/g, '<strong>$1</strong>').replace(/`([^`]+)`/g, '<code>$1</code>');
    html += `<p>${ln}</p>`;
  }
  return html;
}

function renderNav() {
  const nav = document.getElementById('nav'); let html = '';
  if (DATA.entries.length) {
    html += '<div class="group">Entries</div>';
    DATA.entries.forEach(e => { html += `<a class="item" data-i="${e._i}">${esc(e.title)}</a>`; });
  }
  if (DATA.stores.length) {
    html += '<div class="group">KV stores</div>';
    DATA.stores.forEach((c,i) => { html += `<a class="item" data-c="${i}">${esc(c.title||c.slug)}</a>`; });
  }
  nav.innerHTML = html;
}

function selectEntry(i) {
  const e = DATA.entries[i];
  setActive(`[data-i="${i}"]`);
  const tags = (e.tags||[]).map(t => `<span class="tag">${esc(t)}</span>`).join('');
  const outs = e._out.map(j => `<a class="wl" data-i="${j}">${esc(DATA.entries[j].title)}</a>`).join(', ') || '<span class="empty">none</span>';
  const backs = [...new Set(e._back)].map(j => `<a class="wl" data-i="${j}">${esc(DATA.entries[j].title)}</a>`).join(', ') || '<span class="empty">none</span>';
  document.getElementById('main').innerHTML =
    `<h1>${esc(e.title)}</h1><div class="meta">${e.archived ? 'archived &middot; ' : ''}${e.source ? esc(e.source) : 'entry'}<br>${tags}</div>` +
    `<div class="body">${mdToHtml(e.content||'')}</div>` +
    `<div class="links"><h4>Links &rarr;</h4>${outs}<h4 style="margin-top:12px">Backlinks &larr;</h4>${backs}</div>`;
  bindLinks();
}

function selectStore(i) {
  const c = DATA.stores[i];
  setActive(`[data-c="${i}"]`);
  const rows = c.pairs.map(d =>
    `<tr><td class="k">${esc(d.key)}</td><td><div class="type">${esc(d.value_type||'json')}</div><pre style="margin:4px 0 0">${esc(JSON.stringify(d.value, null, 2))}</pre></td></tr>`
  ).join('');
  document.getElementById('main').innerHTML =
    `<h1>${esc(c.title||c.slug)}</h1><div class="meta">kv store &middot; ${c.pairs.length} keys</div>` +
    `<table class="kv">${rows}</table>`;
}

function setActive(sel) {
  document.querySelectorAll('a.item').forEach(a => a.classList.remove('active'));
  const el = document.querySelector('a.item'+sel); if (el) el.classList.add('active');
}
function bindLinks() {
  document.querySelectorAll('a.wl[data-i]').forEach(a => a.onclick = () => selectEntry(+a.dataset.i));
}
document.getElementById('nav').addEventListener('click', ev => {
  const a = ev.target.closest('a.item'); if (!a) return;
  if (a.dataset.i != null) selectEntry(+a.dataset.i); else if (a.dataset.c != null) selectStore(+a.dataset.c);
});

renderNav();
if (DATA.entries.length) selectEntry(0); else if (DATA.stores.length) selectStore(0);
else document.getElementById('main').innerHTML = '<p class="empty">Empty bundle.</p>';
</script>
</body>
</html>
"""


def render_viewer(entries: list[dict], stores: list[dict]) -> str:
    """Render a self-contained viewer HTML string for a bundle."""
    payload = {
        "entries": [
            {
                "title": e.get("title") or "",
                "archived": bool(e.get("archived_at")),
                "tags": list(e.get("tags") or []),
                "source": e.get("source"),
                "content": e.get("content") or "",
            }
            for e in entries
        ],
        "stores": [
            {
                "slug": s["slug"],
                "title": s.get("title"),
                "pairs": [
                    {
                        "key": p["key"],
                        "value": p["value"],
                        "value_type": p.get("value_type", "json"),
                    }
                    for p in s["pairs"]
                ],
            }
            for s in stores
        ],
    }
    # Escape "<" so an embedded "</script>" can't terminate the script tag.
    blob = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c")
    return _TEMPLATE.replace("__BUNDLE__", blob)
