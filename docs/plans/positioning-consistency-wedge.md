# Positioning: lead with the consistency wedge

## Status (2026-06-14)

**Done.** Hero headline locked (🧑): *"One source of truth your agents and team
keep true."* (consistency-led, not staleness — Magpie doesn't auto-refresh values;
it keeps one canonical value and stops contradictory copies). Shipped: landing
page hero + subhead + section reorder (Hero → resolve demo → coherence → KV →
features → quickstart → self-host); docs intro rewrite + frontmatter description;
README one-liner; consistency framing line on `kv`/`coherence`/`links`/`search`
concept pages. No code/schema changes. Remaining: 🧑 step 4 — read the first
screen cold and confirm it lands.

## The decision behind this

We pressure-tested what makes Magpie 10x rather than "another knowledge store."
Verdict: **the moat is not "a knowledge store with KV + dual search"** (that's
the crowded category — mem0, Zep, vector DBs, Notion-with-an-API). The moat is a
narrower, agent-native claim the incumbents structurally can't make:

> **Your agents maintain one source of truth for your org's facts and
> definitions as a byproduct of their work — and it resolves live everywhere
> it's referenced, so your docs, your metrics, and your AI never quote a stale
> number.**

Why this and not breadth:
- **CMS / Notion synced blocks** do variables-in-prose, but aren't agent-native
  or retrievable-as-memory.
- **mem0 / Zep** do agent memory, but have *no consistency model* — they'll store
  five contradictory facts and return whichever embeds closest.
- **Config services** hold canonical values, but not inside prose and not searchable.

Magpie sits in the seam: read-time `{{kv.key}}` resolution **+** dual search over
the same store **+** coherence (dedupe/find/merge) that stops the contradictory
copies forming. The agent maintains the layer; the human never pays the
curation tax that killed every "single source of truth" product before it.

## Current state (what the page says today)

The wedge exists on the site but is **not the spine** — it's diffuse:

- **Hero** (`web/src/pages/LandingPage.tsx:259`): *"The knowledge store your agents
  and your team share."* Subhead lists **breadth** ("durable Markdown, typed KV
  stores, and real files"). This is category framing.
- The consistency story is scattered: a `"KV stores can't drift"` feature card,
  the read-time resolve before/after demo, and a strong anti-rot block ("the same
  fact drifts across half a dozen entries… one coherent source of truth, not a
  pile of slop"). All good copy — but downstream of a generic hero, not the lead.
- **Docs intro** (`docs/site/introduction.mdx`): leads with *"a store, not a
  search box… two kinds of context."* Breadth-first; consistency is a bullet
  ("Coherence") not the thesis.
- **README**: *"Knowledge store with semantic + keyword search. Built for AI
  agents."* Category-first.

Net: a reader leaves knowing Magpie is a *tidy shared knowledge store*. They do
**not** leave with the one sentence that makes them switch.

## The retarget

Promote consistency to the spine; demote breadth to "and it also holds
everything else." Concretely:

### 1. Hero 🧑 (headline is a judgement call — options below)

Lead with the pain + the agent-native promise, not the category. Candidate
headlines (pick/merge — keep it about *staleness/truth*, not *storage*):

- **"Your AI shouldn't quote last quarter's numbers."**
- **"One source of truth your agents actually keep true."**
- **"Define a fact once. It stays right everywhere — docs, metrics, agent answers."**

Candidate subhead:

> Magpie is the consistency layer for agent + human knowledge. Define a value,
> a metric, a definition once; reference it anywhere; it resolves live at read
> time — and your agents keep it deduped and current as a side effect of their
> work. Nothing drifts, and your AI never cites a stale number.

Keep the existing *"Memory APIs remember your users — Magpie remembers your
projects"* line; it's a sharp incumbent contrast — but move it **below** the
consistency promise, as support, not as the lead.

### 2. Landing page section order 🤖 (`web/src/pages/LandingPage.tsx`)

Reorder so the narrative is **pain → mechanism → proof**:
1. Hero (new consistency promise).
2. **The resolve demo** (before/after `{{kv.key}}`) — currently mid-page; this is
   the "aha", move it up directly under the hero.
3. **The anti-rot / coherence block** ("every memory store rots the same way…") —
   this is already the best copy on the page; make it section 2, framed as *why
   consistency is hard and how Magpie holds it* (dedupe-on-write, find/merge,
   "KV stores can't drift").
4. *Then* breadth — Markdown + KV + files + dual search + surfaces — as
   "everything else you'd expect," not the headline.
5. Self-host / quickstart as today.

No new components; this is reordering + hero copy.

### 3. Docs intro 🤖 (`docs/site/introduction.mdx`)

Rewrite the opening two paragraphs to lead with the consistency thesis and the
"agents maintain it" mechanism, then keep the existing "two halves of context"
structure as the *how*. Update the frontmatter `description` to the consistency
line (it currently lists features).

### 4. README 🤖

Swap the one-liner from "Knowledge store with semantic + keyword search" to the
consistency promise; keep the feature list below the fold.

### 5. Concept-page framing pass 🤖 (`docs/site/concepts/*`)

`kv.mdx`, `links.mdx`, `coherence.mdx`, `search.mdx` each currently stand alone.
Add a one-line "why this serves consistency" framing at the top of each so the
thesis is reinforced, not just stated once on the landing page. `kv.mdx` and
`coherence.mdx` are the load-bearing ones — make them explicitly about
"one true value, kept true."

## Explicitly out of scope

- **No product/code changes.** The features already exist; this is messaging.
- **The agent-maintained-consistency claim is the one open risk** (do agents keep
  the layer clean enough to trust?). Don't over-promise it in copy beyond what's
  demonstrably true today — "dedupe-on-write + find/merge" is real; "agents
  autonomously keep your whole org's truth perfect" is not yet. Keep the claim to
  *the mechanisms that ship*.
- **Not** repositioning as an Erdo-internal component. Erdo is building its own
  knowledge/collections layer (dataset linking is core to Erdo and out of Magpie's
  scope), so Magpie stands as its own product — this retarget is for *that*
  product's own audience.

## Suggested sequence

1. 🧑 Lock the hero headline (the one judgement call).
2. 🤖 Landing reorder + hero/subhead.
3. 🤖 Docs intro + README + concept-page framing pass.
4. 🧑 Read it cold: does the first screen make a stranger with the stale-number
   pain want to try it? If not, the headline's still wrong — iterate on 1.
