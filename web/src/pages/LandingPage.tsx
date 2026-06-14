import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { CodeBlock, InlineCommand } from '@/components/CodeBlock';
import { cn } from '@/lib/utils';
import {
  ArrowRight,
  BookOpen,
  Activity,
  Boxes,
  CopyCheck,
  FileText,
  GitBranch,
  GitMerge,
  Link2,
  Paperclip,
  Search,
  ShieldCheck,
  Terminal,
  Users,
} from 'lucide-react';

function quickstartTabs(origin: string) {
  return [
    {
      id: 'cli',
      label: 'CLI',
      code: `npx @erdo/magpie login --api-url ${origin}
magpie link --workspace my-app --project acme

magpie write --title "Acme positioning" --file notes.md
magpie search "what did we decide about pricing?"
magpie read <entry-id> --resolved`,
    },
    {
      id: 'mcp',
      label: 'MCP (agents)',
      code: `# Claude Code — hosted (OAuth)
claude mcp add --transport http magpie ${origin}/mcp

# or stdio via the CLI
claude mcp add magpie -- npx @erdo/magpie mcp

# your agent now has: search, read, write, list_links,
# resolve_knowledge, kv get/set, list_updates, entry_history,
# upload_attachment, ...`,
    },
    {
      id: 'rest',
      label: 'REST',
      code: `curl -X POST ${origin}/api/search \\
  -H "Authorization: Bearer $MAGPIE_TOKEN" \\
  -d '{"query": "enterprise buyers", "workspace": "reach", "project": "acme"}'`,
    },
    {
      id: 'selfhost',
      label: 'Self-host',
      code: `pip install erdo-magpie
export DATABASE_URL=postgres://...   # pgvector optional
magpie serve                          # REST + MCP + UI on :8200`,
    },
  ];
}

const COLLECTIONS_EXAMPLE = `# Curated config — canonical in git, typed on write
magpie kv set config trial_days    --value 14      --type integer
magpie kv set config price_monthly  --value '"$29"' --type string
magpie kv set config signups_open   --value true    --type boolean

# Read one whole, by key — comes back as the real type
magpie kv get config trial_days        # → 14  (integer, not "14")`;

const COHERENCE_EXAMPLE = `# Don't fork a near-duplicate — update the closest match
magpie write --title "Pricing decision" --file note.md --dedupe

# Surface entries that already cover the same ground
magpie duplicates --workspace acme
#   Cluster 1 (2 entries):
#     - Pricing decision         (dist: 0.04)
#     - Pricing for enterprise   (dist: 0.04)

# Collapse them into one — sources archived with lineage
magpie merge <id-a> <id-b> --title "Pricing" --file merged.md`;

const COHERENCE_POINTS = [
  {
    icon: CopyCheck,
    title: 'Dedupe on write',
    body: 'A write with dedupe updates the closest existing entry instead of forking a new one — agents stop re-recording what they already know.',
  },
  {
    icon: GitMerge,
    title: 'Find & merge',
    body: 'Semantic find_duplicates surfaces clusters covering the same topic; merge collapses them into one, archiving the sources with lineage.',
  },
  {
    icon: ShieldCheck,
    title: "KV stores can't drift",
    body: 'A manifest registry rejects undeclared or near-duplicate stores ("Did you mean \'config\'?") — at push time and on live writes.',
  },
];

// Before/after for the read-time resolution demo.
const ENTRY_STORED = `## Acme onboarding

New users get {{config.trial_days}} days free,
then {{config.price_monthly}}/mo.

Questions? {{config.support_email}}

![logo]({{attachment:logo-primary}})

See [[Pricing policy]] for the edge cases.`;

const ENTRY_RESOLVED = `## Acme onboarding

New users get 14 days free,
then $29/mo.

Questions? help@acme.com

![logo](https://cdn.acme.com/logo-primary.png)

See [Pricing policy](/entries/abc123) for the edge cases.`;

const STORED_RE = /(\{\{[^}]+\}\}|\[\[[^\]]+\]\])/g;
const RESOLVED_RE =
  /(14 days|\$29\/mo|help@acme\.com|https:\/\/cdn\.acme\.com\/logo-primary\.png|\[Pricing policy\]\(\/entries\/abc123\))/g;

function TokenizedCode({
  text,
  pattern,
  tokenClass,
}: {
  text: string;
  pattern: RegExp;
  tokenClass: string;
}) {
  return (
    <pre className="overflow-x-auto p-4 text-[12.5px] leading-relaxed">
      <code className="font-mono">
        {text.split(pattern).map((seg, i) =>
          i % 2 === 1 ? (
            <span key={i} className={cn('rounded px-1', tokenClass)}>
              {seg}
            </span>
          ) : (
            <span key={i}>{seg}</span>
          ),
        )}
      </code>
    </pre>
  );
}

const FEATURES = [
  {
    icon: FileText,
    title: 'Knowledge entries',
    body: 'Durable Markdown, scoped by workspace and project. What you write is what gets stored — no lossy extraction pipeline deciding what your memory is.',
  },
  {
    icon: Search,
    title: 'Hybrid search',
    body: 'Semantic + keyword with reciprocal rank fusion. Works keyword-only without an embedding key; gets smarter with one.',
  },
  {
    icon: Link2,
    title: 'Links & references',
    body: '[[wikilinks]] become durable edges with backlinks. {{kv.key}} references resolve to live, typed values at read time.',
  },
  {
    icon: Paperclip,
    title: 'Attachments',
    body: 'Logos, screenshots, SQL snippets, briefs — owned by entries, with stable magpie:<id> handles so agents reuse real assets instead of inventing them.',
  },
  {
    icon: Users,
    title: 'Shared by a team',
    body: 'Org is the security boundary: membership and roles (owner → admin → editor → viewer). One token, many orgs, one active org at a time. Reads fail closed.',
  },
  {
    icon: Activity,
    title: 'History that survives',
    body: 'A durable activity log — entries, KV, attachments, merges, bulk edits, pushes — recording what changed, when, and by whom. It outlives overwrites and deletes, and every entry and KV key keeps its previous versions.',
  },
  {
    icon: Terminal,
    title: 'Every surface',
    body: 'REST, CLI, MCP, and a web UI — one product kept in lockstep, so the same knowledge is one command, one call, or one click away.',
  },
];

function Eyebrow({ children }: { children: React.ReactNode }) {
  return (
    <p className="mb-3 text-xs font-semibold uppercase tracking-[0.18em] text-primary/80">
      {children}
    </p>
  );
}

export function LandingPage() {
  const [tab, setTab] = useState('cli');
  const tabs = quickstartTabs(window.location.origin);
  const active = tabs.find((t) => t.id === tab)!;

  return (
    <div className="min-h-screen overflow-x-hidden">
      {/* Nav */}
      <nav className="sticky top-0 z-20 border-b border-border/60 bg-background/80 backdrop-blur">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
          <span className="flex items-center gap-2 text-lg font-bold">
            <span className="grid h-6 w-6 place-items-center rounded-md bg-primary/15 text-primary">
              <Boxes size={15} />
            </span>
            magpie
          </span>
          <div className="flex items-center gap-2">
            <Link to="/docs">
              <Button variant="ghost" size="sm"><BookOpen size={14} className="mr-1.5" /> Docs</Button>
            </Link>
            <a href="https://github.com/erdoai/magpie" target="_blank" rel="noreferrer">
              <Button variant="ghost" size="sm">GitHub</Button>
            </a>
            <Link to="/login">
              <Button size="sm">Sign in</Button>
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="relative overflow-hidden">
        {/* glow backdrop */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-x-0 top-0 -z-10 h-[420px] opacity-70"
          style={{
            background:
              'radial-gradient(60% 100% at 50% 0%, color-mix(in oklch, var(--color-primary) 22%, transparent), transparent 70%)',
          }}
        />
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 -z-10 opacity-[0.04]"
          style={{
            backgroundImage:
              'linear-gradient(var(--color-foreground) 1px, transparent 1px), linear-gradient(90deg, var(--color-foreground) 1px, transparent 1px)',
            backgroundSize: '44px 44px',
            maskImage: 'radial-gradient(70% 60% at 50% 0%, black, transparent 80%)',
          }}
        />

        <div className="mx-auto max-w-5xl px-6 pb-16 pt-20 text-center">
          <Badge variant="secondary" className="mb-6 border border-border/60">
            MCP-native · open source · self-hostable
          </Badge>
          <h1 className="mx-auto max-w-3xl text-balance text-4xl font-bold leading-tight sm:text-5xl">
            One source of truth your agents and team keep{' '}
            <span className="bg-gradient-to-r from-primary to-[oklch(0.7_0.17_300)] bg-clip-text text-transparent">
              true
            </span>
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-pretty text-muted-foreground">
            Magpie is the consistency layer for agent and human knowledge. Define a value, a metric,
            a definition once — reference it anywhere, and it resolves to the one canonical value at
            read time. Dedupe-on-write and merge keep contradictory copies from forming, so your
            docs, your metrics, and your AI never disagree.
          </p>
          <p className="mx-auto mt-3 max-w-2xl text-pretty text-sm text-muted-foreground/80">
            Memory APIs remember your users. Magpie remembers your projects.
          </p>
          <div className="mt-9 flex flex-col items-center gap-3">
            <InlineCommand code="npx @erdo/magpie login" />
            <p className="text-xs text-muted-foreground">
              Then it's all here — your terminal, your agents, or this web UI. Same knowledge, whichever you reach for.
            </p>
          </div>
        </div>
      </section>

      {/* Resolve demo — before/after */}
      <section className="mx-auto max-w-5xl px-6 pb-20">
        <div className="text-center">
          <Eyebrow>Define once, resolve everywhere</Eyebrow>
          <h2 className="text-2xl font-semibold">Templates in. Real values out.</h2>
          <p className="mx-auto mt-3 max-w-2xl text-sm text-muted-foreground">
            This is the consistency mechanism. A value lives in one place; entries reference it and
            stay clean, reviewable templates — the stored Markdown is never mutated. Read with{' '}
            <code className="rounded bg-muted px-1 py-0.5 text-xs">--resolved</code> and every
            reference fills with the one canonical, permission-checked value. Change it once, and
            everywhere it's quoted follows.
          </p>
        </div>

        <div className="mt-8 grid items-stretch gap-3 lg:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] [&>*]:min-w-0">
          <div className="overflow-hidden rounded-xl border border-border bg-card">
            <div className="flex items-center justify-between border-b border-border px-4 py-2">
              <span className="font-mono text-xs text-muted-foreground">onboarding.md</span>
              <span className="text-[10px] uppercase tracking-wide text-muted-foreground/60">stored</span>
            </div>
            <TokenizedCode
              text={ENTRY_STORED}
              pattern={STORED_RE}
              tokenClass="bg-[oklch(0.8_0.15_85_/_0.15)] text-[oklch(0.82_0.15_85)]"
            />
          </div>

          <div className="grid place-items-center py-2 lg:py-0">
            <div className="grid h-9 w-9 place-items-center rounded-full border border-border bg-card text-primary">
              <ArrowRight size={16} className="hidden lg:block" />
              <ArrowRight size={16} className="rotate-90 lg:hidden" />
            </div>
          </div>

          <div className="overflow-hidden rounded-xl border border-primary/30 bg-card">
            <div className="flex items-center justify-between border-b border-border px-4 py-2">
              <span className="font-mono text-xs text-muted-foreground">magpie read --resolved</span>
              <span className="text-[10px] uppercase tracking-wide text-primary/70">resolved</span>
            </div>
            <TokenizedCode
              text={ENTRY_RESOLVED}
              pattern={RESOLVED_RE}
              tokenClass="bg-primary/15 text-primary"
            />
          </div>
        </div>

        <p className="mx-auto mt-5 max-w-2xl text-center text-xs text-muted-foreground">
          Same on every surface — <code className="rounded bg-muted px-1 py-0.5">read(resolved=true)</code> over
          MCP, <code className="rounded bg-muted px-1 py-0.5">POST /api/entries/{'{id}'}/resolve</code> over REST.
          Anything missing or unauthorized renders as <code className="rounded bg-muted px-1 py-0.5">⟦unresolved⟧</code> and
          is reported in a dependency list, so an agent knows exactly what's absent.
        </p>
      </section>

      {/* Coherence spotlight */}
      <section className="mx-auto max-w-5xl px-6 pb-20">
        <div className="grid items-center gap-8 rounded-2xl border border-border bg-card/40 p-6 sm:p-8 lg:grid-cols-2 [&>*]:min-w-0">
          <div>
            <Eyebrow>Stays coherent</Eyebrow>
            <h2 className="text-2xl font-semibold">Knowledge that doesn't fragment</h2>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              Every memory store rots the same way: agents pile up near-duplicates and the same
              fact drifts across half a dozen entries. Magpie fights it at every layer — so what
              you've stored stays one coherent source of truth, not a pile of slop.
            </p>
            <ul className="mt-5 space-y-3 text-sm">
              {COHERENCE_POINTS.map(({ icon: Icon, title, body }) => (
                <li key={title} className="flex gap-3">
                  <Icon size={16} className="mt-0.5 shrink-0 text-primary" />
                  <span className="text-muted-foreground">
                    <span className="text-foreground">{title}</span> — {body}
                  </span>
                </li>
              ))}
            </ul>
            <Link to="/docs" className="mt-6 inline-flex">
              <Button variant="outline" size="sm">
                Staying coherent <ArrowRight size={14} className="ml-1.5" />
              </Button>
            </Link>
          </div>
          <CodeBlock code={COHERENCE_EXAMPLE} language="shell" />
        </div>
      </section>

      {/* KV stores spotlight */}
      <section className="mx-auto max-w-5xl px-6 pb-20">
        <div className="grid items-center gap-8 rounded-2xl border border-border bg-card/40 p-6 sm:p-8 lg:grid-cols-2 [&>*]:min-w-0">
          <div>
            <Eyebrow>Typed KV stores</Eyebrow>
            <h2 className="text-2xl font-semibold">Not all knowledge is prose</h2>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              Some context is a <span className="text-foreground">value</span> — a trial length,
              a support email, a set of brand tokens. KV stores are named key/value stores your
              agents read whole by key, with typed values that deserialize without guessing — and
              they're the canonical home a <code className="rounded bg-muted px-1 py-0.5 text-xs">{'{{config.trial_days}}'}</code>{' '}
              reference points at.
            </p>
            <ul className="mt-5 space-y-3 text-sm">
              <li className="flex gap-3">
                <Boxes size={16} className="mt-0.5 shrink-0 text-primary" />
                <span className="text-muted-foreground">
                  <span className="text-foreground">Typed</span> — json, string, integer, float,
                  boolean, datetime. Validated on write, returned as the real type on read.
                </span>
              </li>
              <li className="flex gap-3">
                <GitBranch size={16} className="mt-0.5 shrink-0 text-primary" />
                <span className="text-muted-foreground">
                  <span className="text-foreground">Live or curated</span> — agent-written runtime
                  data, or repo-owned config that's canonical in git and can't drift.
                </span>
              </li>
              <li className="flex gap-3">
                <ArrowRight size={16} className="mt-0.5 shrink-0 text-primary" />
                <span className="text-muted-foreground">
                  <span className="text-foreground">Referenceable</span> —{' '}
                  <code className="rounded bg-muted px-1 py-0.5 text-xs">{'{{config.trial_days}}'}</code>{' '}
                  in any entry resolves to a live typed value at read time.
                </span>
              </li>
            </ul>
            <Link to="/docs" className="mt-6 inline-flex">
              <Button variant="outline" size="sm">
                KV stores docs <ArrowRight size={14} className="ml-1.5" />
              </Button>
            </Link>
          </div>
          <CodeBlock code={COLLECTIONS_EXAMPLE} language="shell" />
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto max-w-5xl px-6 pb-20">
        <Eyebrow>And everything else you'd expect</Eyebrow>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, body }) => (
            <div
              key={title}
              className="group rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/40 hover:bg-card/80"
            >
              <div className="mb-3 grid h-9 w-9 place-items-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary/15">
                <Icon size={17} />
              </div>
              <h3 className="mb-1.5 text-sm font-semibold">{title}</h3>
              <p className="text-sm leading-relaxed text-muted-foreground">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Quickstart tabs */}
      <section className="mx-auto max-w-3xl px-6 pb-20">
        <Eyebrow>Start in one command</Eyebrow>
        <div className="mb-3 flex gap-1.5">
          {tabs.map((t) => (
            <Button
              key={t.id}
              variant={t.id === tab ? 'default' : 'outline'}
              size="sm"
              className={cn('text-xs', t.id !== tab && 'text-muted-foreground')}
              onClick={() => setTab(t.id)}
            >
              {t.label}
            </Button>
          ))}
        </div>
        <CodeBlock code={active.code} language={tab === 'rest' ? 'bash' : 'shell'} />
      </section>

      {/* Self-host */}
      <section className="mx-auto max-w-3xl px-6 pb-24 text-center">
        <Eyebrow>Yours, either way</Eyebrow>
        <h2 className="text-2xl font-semibold">Run it on your own Postgres</h2>
        <p className="mx-auto mt-3 max-w-xl text-sm text-muted-foreground">
          One Postgres database and an S3-compatible bucket. Same code as hosted —
          auth optional for local use, keyword search works without any API keys.
        </p>
        <div className="mt-6 text-left">
          <CodeBlock
            code={`pip install erdo-magpie
export DATABASE_URL=postgres://localhost/magpie
magpie serve`}
            language="shell"
          />
        </div>
        <div className="mt-8 flex items-center justify-center gap-3">
          <Link to="/docs"><Button variant="outline" size="sm">Read the docs</Button></Link>
          <a href="https://github.com/erdoai/magpie" target="_blank" rel="noreferrer">
            <Button variant="outline" size="sm">Star on GitHub</Button>
          </a>
        </div>
      </section>

      <footer className="border-t border-border py-8 text-center text-xs text-muted-foreground">
        magpie — MIT licensed
      </footer>
    </div>
  );
}
