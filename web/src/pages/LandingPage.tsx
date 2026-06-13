import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { CodeBlock, InlineCommand } from '@/components/CodeBlock';
import { cn } from '@/lib/utils';
import {
  ArrowRight,
  BookOpen,
  Boxes,
  FileText,
  GitBranch,
  Link2,
  Paperclip,
  Search,
  Terminal,
  Users,
} from 'lucide-react';

function quickstartTabs(origin: string) {
  return [
    {
      id: 'cli',
      label: 'CLI',
      code: `npx @magpie/cli login --api-url ${origin}
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
claude mcp add magpie -- npx @magpie/cli mcp

# your agent now has: search, read, write, list_links,
# resolve_knowledge, get/set_document, upload_attachment, ...`,
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
      code: `pip install magpie-ai
export DATABASE_URL=postgres://...   # pgvector optional
magpie serve                          # REST + MCP + UI on :8200`,
    },
  ];
}

const COLLECTIONS_EXAMPLE = `# Curated config, owned by your repo (canonical in git)
magpie collections set config trial_days   --value 14    --type integer
magpie collections set config signups_open --value true  --type boolean
magpie collections set config support_email --value '"help@acme.com"' --type string

# Reference a value from any entry...
echo "New users get {{config.trial_days}} days free." > onboarding.md
magpie write --title "Onboarding" --file onboarding.md

# ...and it resolves to a real typed value at read time
magpie read <entry-id> --resolved
# → "New users get 14 days free."   (14 is an integer, not "14")`;

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
    body: '[[wikilinks]] become durable edges with backlinks. {{collection.key}} references resolve to live, typed values at read time.',
  },
  {
    icon: Paperclip,
    title: 'Attachments',
    body: 'Logos, screenshots, SQL snippets, briefs — owned by entries, with stable magpie:<id> handles so agents reuse real assets instead of inventing them.',
  },
  {
    icon: Users,
    title: 'Shared by a team',
    body: 'Org is the security boundary: membership and roles (owner → admin → editor → viewer). One key, many orgs, one active org at a time. Reads fail closed.',
  },
  {
    icon: Terminal,
    title: 'Every surface',
    body: 'REST, CLI, MCP, and a web UI — one product kept in lockstep. The UI is there when you want it; you never need it.',
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
    <div className="min-h-screen">
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
            The knowledge store your agents and your team{' '}
            <span className="bg-gradient-to-r from-primary to-[oklch(0.7_0.17_300)] bg-clip-text text-transparent">
              share
            </span>
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-pretty text-muted-foreground">
            Memory APIs remember your users. Magpie remembers your projects — durable Markdown,
            typed collections, and real files that agents write and read across every product you build.
          </p>
          <div className="mt-9 flex flex-col items-center gap-3">
            <InlineCommand code="npx @magpie/cli login" />
            <p className="text-xs text-muted-foreground">
              Then everything works from your terminal. There's a web UI — you just won't need it.
            </p>
          </div>
        </div>
      </section>

      {/* Quickstart tabs */}
      <section className="mx-auto max-w-3xl px-6 pb-20">
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

      {/* Collections spotlight */}
      <section className="mx-auto max-w-5xl px-6 pb-20">
        <div className="grid items-center gap-8 rounded-2xl border border-border bg-card/40 p-6 sm:p-8 lg:grid-cols-2">
          <div>
            <Eyebrow>New · Typed collections</Eyebrow>
            <h2 className="text-2xl font-semibold">Not all knowledge is prose</h2>
            <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
              Some context is a <span className="text-foreground">value</span> — a trial length,
              a support email, a set of brand tokens. Collections are named key/value stores your
              agents read whole by key, with typed values that deserialize without guessing.
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
                Collections docs <ArrowRight size={14} className="ml-1.5" />
              </Button>
            </Link>
          </div>
          <CodeBlock code={COLLECTIONS_EXAMPLE} language="shell" />
        </div>
      </section>

      {/* Features */}
      <section className="mx-auto max-w-5xl px-6 pb-20">
        <Eyebrow>Everything in the box</Eyebrow>
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
            code={`pip install magpie-ai
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
