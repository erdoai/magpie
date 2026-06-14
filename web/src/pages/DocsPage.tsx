import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { CodeBlock } from '@/components/CodeBlock';
import { cn } from '@/lib/utils';

const SECTIONS = [
  { id: 'quickstart', label: 'Quickstart' },
  { id: 'concepts', label: 'Concepts' },
  { id: 'cli', label: 'CLI' },
  { id: 'mcp', label: 'MCP tools' },
  { id: 'rest', label: 'REST API' },
  { id: 'kv', label: 'KV stores' },
  { id: 'links', label: 'Links & references' },
  { id: 'attachments', label: 'Attachments' },
  { id: 'selfhost', label: 'Self-hosting' },
];

function H2({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="mb-4 scroll-mt-24 border-b border-border pb-2 pt-10 text-xl font-semibold first:pt-0">
      {children}
    </h2>
  );
}

function H3({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-2 mt-6 text-sm font-semibold">{children}</h3>;
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="mb-3 text-sm leading-relaxed text-muted-foreground">{children}</p>;
}

function Mono({ children }: { children: React.ReactNode }) {
  return <code className="rounded bg-accent px-1 py-0.5 font-mono text-[12.5px] text-foreground">{children}</code>;
}

function Table({ rows, headers }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="mb-4 overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border bg-card">
            {headers.map((h) => (
              <th key={h} className="px-3 py-2 text-left text-xs font-medium text-muted-foreground">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-b border-border last:border-0">
              {row.map((cell, j) => (
                <td key={j} className={cn('px-3 py-2 align-top', j === 0 && 'font-mono text-[12.5px] whitespace-nowrap')}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DocsPage() {
  const [activeSection, setActiveSection] = useState('quickstart');
  const origin = window.location.origin;

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActiveSection(entry.target.id);
        }
      },
      { rootMargin: '-20% 0px -70% 0px' }
    );
    for (const s of SECTIONS) {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  return (
    <div className="min-h-screen">
      <nav className="sticky top-0 z-20 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3.5">
          <div className="flex items-center gap-6">
            <Link to="/" className="text-lg font-bold no-underline">magpie</Link>
            <span className="text-sm text-muted-foreground">Docs</span>
          </div>
          <div className="flex items-center gap-2">
            <a href="https://github.com/erdoai/magpie" target="_blank" rel="noreferrer">
              <Button variant="ghost" size="sm">GitHub</Button>
            </a>
            <Link to="/login"><Button size="sm">Sign in</Button></Link>
          </div>
        </div>
      </nav>

      <div className="mx-auto flex max-w-6xl gap-10 px-6 py-8">
        {/* Sidebar */}
        <aside className="sticky top-20 hidden h-fit w-44 shrink-0 md:block">
          <ul className="flex flex-col gap-0.5">
            {SECTIONS.map((s) => (
              <li key={s.id}>
                <a
                  href={`#${s.id}`}
                  className={cn(
                    'block rounded-md px-3 py-1.5 text-sm no-underline transition-colors',
                    activeSection === s.id
                      ? 'bg-accent font-medium text-primary'
                      : 'text-muted-foreground hover:text-foreground'
                  )}
                >
                  {s.label}
                </a>
              </li>
            ))}
          </ul>
        </aside>

        {/* Content */}
        <main className="min-w-0 max-w-3xl flex-1 pb-24">
          <H2 id="quickstart">Quickstart</H2>
          <P>
            Magpie is a knowledge and context store for agents and teams: durable Markdown entries,
            typed KV stores, file attachments, and links — searchable, scoped, and exposed over
            REST, CLI, and MCP. The web UI exists; you never need it.
          </P>
          <H3>Hosted</H3>
          <CodeBlock
            language="shell"
            code={`npx @erdo/magpie login --api-url ${origin}
magpie link --workspace my-app --project acme   # defaults for every command

magpie write --title "Acme positioning" --file notes.md
magpie search "what did we decide about pricing?"`}
          />
          <H3>Connect an agent (MCP)</H3>
          <CodeBlock
            language="shell"
            code={`# Streamable HTTP with OAuth — agents get their own login
claude mcp add --transport http magpie ${origin}/mcp

# Or stdio, using your CLI credentials
claude mcp add magpie -- npx @erdo/magpie mcp`}
          />

          <H2 id="concepts">Concepts</H2>
          <Table
            headers={['Concept', 'What it is']}
            rows={[
              ['org', 'Team/account boundary. Roles: owner > admin > editor > viewer. Editors write knowledge; admins manage members and workspaces.'],
              ['workspace', 'Broad app/product namespace — "reach", "alertee", "personal".'],
              ['project', 'Narrower work area inside a workspace — a customer, a product, a codebase. Workspace + project travel together on every entry, search, and API key.'],
              ['entry', 'A Markdown knowledge document with category (PARA), tags, source, and scope.'],
              ['kv store', 'A named store of typed values, read whole by key.'],
              ['attachment', 'A file owned by an entry — logo, screenshot, SQL snippet, brief.'],
              ['visibility', 'You see your entries + your org’s entries + global entries. Cross-org access is never possible.'],
            ]}
          />
          <P>
            API keys can be pinned to a workspace/project — everything done with that key is clamped to
            that scope, which is how you give one product (or one agent) its own slice of memory.
          </P>

          <H2 id="cli">CLI</H2>
          <CodeBlock
            language="shell"
            code={`npx @erdo/magpie login        # email OTP → API key in ~/.config/magpie/
magpie logout | whoami | link

magpie search "query" [--workspace W] [--project P] [--category C]
magpie read <id> [--resolved]
magpie write --title T (--file F | --content C) [--tags a,b]
magpie archive <id>

magpie kv list | get <slug> <key> | set <slug> <key> --file v.json --type json
magpie attachments add <entry-id> ./logo.svg --role logo-primary
magpie attachments list <entry-id>

magpie import ./docs --workspace erdo --project magpie
magpie mcp                   # stdio MCP server for local agents`}
          />
          <P>
            Config precedence: env (<Mono>MAGPIE_API_URL</Mono>, <Mono>MAGPIE_TOKEN</Mono>) &gt;{' '}
            <Mono>~/.config/magpie/config.json</Mono> &gt; defaults. <Mono>magpie link</Mono> stores
            default workspace/project so you stop typing flags.
          </P>

          <H2 id="mcp">MCP tools</H2>
          <P>
            The hosted <Mono>/mcp</Mono> endpoint speaks Streamable HTTP with OAuth — each user
            authorizes their own access, and tools are scoped to their org automatically.
            <Mono>magpie mcp</Mono> runs the same tools over stdio using your API key.
          </P>
          <Table
            headers={['Tool', 'Does']}
            rows={[
              ['search', 'Hybrid semantic+keyword search with workspace/project/category/tag filters'],
              ['read', 'Full entry with links, backlinks, attachments; resolved=true renders references'],
              ['write', 'Save knowledge; dedupe=true updates a near-duplicate instead of duplicating'],
              ['list_entries', 'Browse by scope/category/tags'],
              ['archive', 'Retire an entry from search'],
              ['list_links', 'Outgoing links + backlinks for an entry'],
              ['resolve_knowledge', 'Rendered Markdown + dependency report'],
              ['list_kv / get_key / set_key / delete_key', 'Typed KV store'],
              ['upload_attachment / list_attachments / get_attachment', 'Files with stable magpie:<id> handles'],
              ['find_duplicates / merge', 'Knowledge hygiene — cluster near-duplicates, merge with lineage'],
            ]}
          />

          <H2 id="rest">REST API</H2>
          <P>Auth: <Mono>Authorization: Bearer &lt;api-key&gt;</Mono>. All list/search endpoints accept <Mono>workspace</Mono> and <Mono>project</Mono>.</P>
          <Table
            headers={['Endpoint', 'Does']}
            rows={[
              ['POST /api/search', 'Hybrid search'],
              ['POST|GET /api/entries', 'Create / list entries'],
              ['GET|PUT|DELETE /api/entries/:id', 'Read / update / delete'],
              ['POST /api/entries/:id/archive', 'Archive'],
              ['GET /api/entries/:id/links', 'Links + backlinks'],
              ['POST /api/entries/:id/resolve', 'Rendered Markdown + dependencies'],
              ['POST|GET /api/kv', 'Create / list KV stores'],
              ['GET|PUT|DELETE /api/kv/:slug/keys/:key', 'Typed key/value pairs'],
              ['POST /api/entries/:id/attachments', 'Upload (multipart)'],
              ['GET /api/attachments/:id[/download]', 'Metadata + inline text / file bytes'],
              ['GET /public/assets/:id', 'Stable public URL for opted-in browser-safe images'],
              ['POST|GET /api/keys', 'Scoped API keys'],
              ['POST|GET /api/orgs', 'Orgs, members, workspaces'],
            ]}
          />

          <H2 id="kv">KV stores</H2>
          <P>
            KV stores hold structured context that should be read whole by key — strategy, config,
            brand tokens, advisories, metrics. Every value declares a <Mono>value_type</Mono>:{' '}
            <Mono>json</Mono>, <Mono>string</Mono>, <Mono>integer</Mono>, <Mono>float</Mono>,{' '}
            <Mono>boolean</Mono>, or <Mono>datetime</Mono>. Writes are validated against the declared
            type; reads return the type so agents deserialize without guessing.
          </P>
          <CodeBlock
            language="shell"
            code={`magpie kv set reach.strategy current --file strategy.json
magpie kv set metrics mrr --value 4200.5 --type float
magpie kv get reach.strategy current`}
          />

          <H2 id="links">Links &amp; references</H2>
          <P>Entry Markdown supports two reference kinds, both parsed automatically:</P>
          <Table
            headers={['Syntax', 'Meaning']}
            rows={[
              ['[[Entry Title]]', 'Link to another entry by title (alias: [[Title|display]]). Stored as a durable edge; backlinks appear on the target — even if the target is created later.'],
              ['[[https://...]]', 'External URL'],
              ['[[alertee:check:42]]', 'Product resource reference (app:type:id)'],
              ['{{reach.strategy.current.wedge}}', 'KV value by dotted path, resolved at read time'],
              ['{{kv:reach.strategy/current#wedge}}', 'Explicit long form'],
              ['{{attachment:logo-primary}}', 'Attachment on this entry by role or filename'],
            ]}
          />
          <P>
            Resolution happens at read time (<Mono>--resolved</Mono>, <Mono>resolve_knowledge</Mono>,
            or <Mono>POST /resolve</Mono>) — stored Markdown is never mutated. Unresolved or
            unauthorized references render as visible placeholders plus a dependency report, so agents
            know exactly what's missing.
          </P>

          <H2 id="attachments">Attachments</H2>
          <P>
            Attachments belong to entries — not loose files in a bucket. Each has a stable{' '}
            <Mono>magpie:&lt;id&gt;</Mono> handle; small SQL/text files are inlined in reads, binaries
            get download URLs. Browser-safe images can opt into a permanent public URL at{' '}
            <Mono>/public/assets/:id</Mono> (never SQL/text/PDF), so generated pages don't embed
            expiring signed URLs.
          </P>
          <P>
            Role conventions give agents deterministic asset lookup:{' '}
            <Mono>logo-primary</Mono>, <Mono>logo-mono-white</Mono>, <Mono>favicon-32x32</Mono>,{' '}
            <Mono>hero-*</Mono>, <Mono>product-*</Mono>, <Mono>screenshot-*</Mono>, <Mono>query-*</Mono>.
            An agent building a landing page asks for the brand entry, inspects attachments, and uses
            the real logo instead of inventing one.
          </P>

          <H2 id="selfhost">Self-hosting</H2>
          <CodeBlock
            language="shell"
            code={`pip install erdo-magpie
export DATABASE_URL=postgres://localhost/magpie
magpie serve    # REST + MCP + UI on :8200`}
          />
          <Table
            headers={['Variable', 'Purpose']}
            rows={[
              ['DATABASE_URL', 'Postgres (required). pgvector enables semantic search; keyword-only without it.'],
              ['OPENAI_API_KEY', 'Embeddings (optional)'],
              ['API_KEY', 'Static auth key. Empty = no auth, for local single-user use.'],
              ['RESEND_API_KEY / RESEND_FROM', 'Email OTP sign-in (optional)'],
              ['OAUTH_ISSUER_URL', 'Enables OAuth on /mcp (set to your public URL)'],
              ['STORAGE_PROVIDER', 'local (filesystem) or s3 — AWS, R2, MinIO, Railway'],
              ['STORAGE_BUCKET / ENDPOINT / ACCESS_KEY_ID / SECRET_ACCESS_KEY / REGION', 'S3-compatible storage credentials'],
              ['ASSET_PUBLIC_BASE_URL', 'Base for stable public asset links'],
            ]}
          />
          <P>
            Embeddings, email, OAuth, and object storage are all optional — the minimum viable Magpie
            is Postgres plus one process.
          </P>
        </main>
      </div>
    </div>
  );
}
