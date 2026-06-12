import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { CodeBlock, InlineCommand } from '@/components/CodeBlock';
import { cn } from '@/lib/utils';
import {
  BookOpen,
  FileText,
  FolderKanban,
  Link2,
  Paperclip,
  Search,
  Terminal,
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
    icon: FolderKanban,
    title: 'Typed collections',
    body: 'Named JSON document stores for structured context — strategy, config, brand tokens, metrics. Values declare their type: json, string, integer, float, boolean, datetime.',
  },
  {
    icon: Paperclip,
    title: 'Attachments',
    body: 'Logos, screenshots, SQL snippets, briefs — owned by entries, with stable magpie:<id> handles and role conventions so agents reuse real assets instead of inventing them.',
  },
  {
    icon: Link2,
    title: 'Links & references',
    body: '[[wikilinks]] become durable edges with backlinks. {{collection.key.path}} references resolve to live values at read time.',
  },
  {
    icon: Terminal,
    title: 'Every surface',
    body: 'REST, CLI, MCP, and a web UI. The UI is there when you want it — you never need it.',
  },
];

export function LandingPage() {
  const [tab, setTab] = useState('cli');
  const tabs = quickstartTabs(window.location.origin);
  const active = tabs.find((t) => t.id === tab)!;

  return (
    <div className="min-h-screen">
      {/* Nav */}
      <nav className="mx-auto flex max-w-5xl items-center justify-between px-6 py-5">
        <span className="text-lg font-bold">magpie</span>
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
      </nav>

      {/* Hero */}
      <section className="mx-auto max-w-5xl px-6 pb-16 pt-20 text-center">
        <Badge variant="secondary" className="mb-6">MCP-native · open source · self-hostable</Badge>
        <h1 className="mx-auto max-w-3xl text-balance text-4xl font-bold leading-tight sm:text-5xl">
          The knowledge store your agents and your team share
        </h1>
        <p className="mx-auto mt-5 max-w-2xl text-pretty text-muted-foreground">
          Memory APIs remember your users. Magpie remembers your projects — durable Markdown,
          typed data, and real files that agents write and read across every product you build.
        </p>
        <div className="mt-9 flex flex-col items-center gap-3">
          <InlineCommand code="npx @magpie/cli login" />
          <p className="text-xs text-muted-foreground">
            Then everything works from your terminal. There's a web UI — you just won't need it.
          </p>
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

      {/* Features */}
      <section className="mx-auto max-w-5xl px-6 pb-20">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ icon: Icon, title, body }) => (
            <div key={title} className="rounded-lg border border-border bg-card p-5">
              <Icon size={18} className="mb-3 text-primary" />
              <h3 className="mb-1.5 text-sm font-semibold">{title}</h3>
              <p className="text-sm leading-relaxed text-muted-foreground">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* Self-host */}
      <section className="mx-auto max-w-3xl px-6 pb-24 text-center">
        <h2 className="text-2xl font-semibold">Yours, either way</h2>
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
