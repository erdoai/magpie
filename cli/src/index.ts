#!/usr/bin/env node
/** Magpie CLI — knowledge and context store for agents and teams. */

import { existsSync, mkdirSync, readFileSync, readdirSync, statSync, writeFileSync } from 'node:fs';
import { basename, dirname, extname, join } from 'node:path';
import { createInterface } from 'node:readline/promises';
import { Command } from 'commander';
import { api, ApiError, qs, requireToken } from './client.js';
import {
  DEFAULT_API_URL,
  clearToken,
  loadConfig,
  resolveApiUrl,
  resolveOrg,
  resolveToken,
  saveConfig,
} from './config.js';
import { runMcpServer } from './mcp.js';

interface Entry {
  id: string;
  title: string;
  content: string;
  archived_at: string | null;
  tags: string[];
  workspace: string | null;
  project: string | null;
  score?: number;
  updated_at: string;
}

const program = new Command();

program
  .name('magpie')
  .description('Magpie — knowledge and context store for agents and teams')
  .version('0.2.0')
  .showHelpAfterError();

program.addHelpText(
  'after',
  `
Getting started:
  $ magpie login                       sign in (use --api-url for a self-hosted instance)
  $ magpie whoami                      show the instance you're connected to + your orgs
  $ magpie search "<query>"            search your knowledge
  $ magpie mcp                         run the MCP stdio server for local agents

Self-hosting:
  Point the CLI at your own instance with --api-url on login, or set
  MAGPIE_API_URL. Default instance: ${DEFAULT_API_URL}

Docs: ${DEFAULT_API_URL}/docs`,
);

function scope(opts: { workspace?: string; project?: string }): {
  workspace?: string;
  project?: string;
} {
  const config = loadConfig();
  return {
    workspace: opts.workspace || config.workspace,
    project: opts.project || config.project,
  };
}

function entryLine(e: Entry): string {
  const ws = e.workspace || 'general';
  const scopeStr = e.project ? `${ws}/${e.project}` : ws;
  const score = e.score != null ? ` (${e.score})` : '';
  const archived = e.archived_at ? ' [archived]' : '';
  return `- ${e.title} [${scopeStr}]${archived}${score}\n  id: ${e.id}`;
}

async function prompt(question: string): Promise<string> {
  const rl = createInterface({ input: process.stdin, output: process.stdout });
  const answer = await rl.question(question);
  rl.close();
  return answer.trim();
}

function fail(err: unknown): never {
  if (err instanceof ApiError) {
    console.error(`Error (${err.status}): ${err.message}`);
  } else {
    console.error(String(err));
  }
  process.exit(1);
}

// -- Auth --

program
  .command('login')
  .description('Sign in with email OTP and store an access token locally')
  .option('--api-url <url>', `Magpie server URL (default: ${DEFAULT_API_URL})`)
  .action(async (opts: { apiUrl?: string }) => {
    try {
      if (opts.apiUrl) {
        const config = loadConfig();
        config.apiUrl = opts.apiUrl;
        saveConfig(config);
      }
      const base = resolveApiUrl();
      const email = await prompt('Email: ');
      let res = await fetch(`${base}/api/auth/send-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      if (!res.ok) fail(new ApiError(res.status, await res.text()));

      const code = await prompt('Code (check your email): ');
      res = await fetch(`${base}/api/auth/verify-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, code }),
      });
      if (!res.ok) fail(new ApiError(res.status, await res.text()));
      const body = (await res.json()) as { user?: { email: string }; error?: string };
      if (body.error || !body.user) fail(new ApiError(401, body.error || 'Login failed'));

      const cookie = res.headers.get('set-cookie');
      if (!cookie) fail(new ApiError(500, 'No session cookie returned'));

      // Mint an access token for the CLI using the fresh session
      const tokenRes = await fetch(`${base}/api/tokens`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Cookie: cookie.split(';')[0] },
        body: JSON.stringify({ name: `cli-${new Date().toISOString().slice(0, 10)}` }),
      });
      if (!tokenRes.ok) fail(new ApiError(tokenRes.status, await tokenRes.text()));
      const minted = (await tokenRes.json()) as { token: string };

      const config = loadConfig();
      config.token = minted.token;
      saveConfig(config);
      console.log(`Signed in as ${body.user.email}. Access token stored in ~/.config/magpie/.`);
    } catch (err) {
      fail(err);
    }
  });

program
  .command('logout')
  .description('Remove the stored access token')
  .action(() => {
    clearToken();
    console.log('Logged out.');
  });

program
  .command('whoami')
  .description('Show server, auth, and linked scope')
  .action(async () => {
    const config = loadConfig();
    const apiUrl = resolveApiUrl();
    const which = apiUrl === DEFAULT_API_URL ? 'default' : 'self-hosted';
    console.log(`Instance: ${apiUrl} (${which})`);
    const token = resolveToken();
    if (!token) {
      console.log('Auth: not signed in');
      return;
    }
    console.log(`Auth: access token ${token.slice(0, 12)}…`);
    const activeOrg = resolveOrg();
    if (activeOrg) console.log(`Active org: ${activeOrg}`);
    if (config.workspace || config.project) {
      console.log(`Linked: workspace=${config.workspace || '-'} project=${config.project || '-'}`);
    }
    try {
      const orgs = await api<{ id: string; name: string; slug: string; role?: string }[]>('/api/orgs');
      if (orgs.length) {
        console.log('Orgs:');
        for (const org of orgs) {
          const marker = org.id === activeOrg || org.slug === activeOrg ? '* ' : '  ';
          console.log(`  ${marker}${org.name} (${org.slug})${org.role ? ` [${org.role}]` : ''}`);
        }
      }
    } catch {
      /* key without session-user context */
    }
  });

program
  .command('link')
  .description('Set the default workspace/project for this machine')
  .option('--workspace <workspace>', 'Default workspace')
  .option('--project <project>', 'Default project')
  .action((opts: { workspace?: string; project?: string }) => {
    const config = loadConfig();
    if (opts.workspace !== undefined) config.workspace = opts.workspace;
    if (opts.project !== undefined) config.project = opts.project;
    saveConfig(config);
    console.log(`Linked: workspace=${config.workspace || '-'} project=${config.project || '-'}`);
  });

// -- Orgs / workspaces --

const org = program.command('org').description('Organization commands');

org
  .command('list')
  .description('List your organizations')
  .action(async () => {
    requireToken();
    try {
      const active = resolveOrg();
      const orgs = await api<{ id: string; name: string; slug: string; role?: string }[]>('/api/orgs');
      if (!orgs.length) return console.log('No orgs.');
      for (const o of orgs) {
        const marker = o.id === active || o.slug === active ? '* ' : '  ';
        console.log(`${marker}${o.name} (${o.slug})${o.role ? ` [${o.role}]` : ''} id=${o.id}`);
      }
    } catch (err) {
      fail(err);
    }
  });

org
  .command('create <name>')
  .description('Create an organization and switch to it')
  .option('--slug <slug>', 'URL slug (defaults to a slugified name)')
  .action(async (name: string, opts: { slug?: string }) => {
    requireToken();
    try {
      const created = await api<{ id: string; name: string; slug: string }>('/api/orgs', {
        method: 'POST',
        body: { name, slug: opts.slug },
      });
      console.log(`Created ${created.name} (${created.slug}) id=${created.id}`);
      // You created it — make it active on this machine.
      const config = loadConfig();
      config.org = created.id;
      saveConfig(config);
      await api(`/api/orgs/${created.id}/select`, { method: 'POST' }).catch(() => {});
      console.log(`Active org: ${created.id}`);
    } catch (err) {
      fail(err);
    }
  });

org
  .command('invite <org> <email>')
  .description('Invite a member to an org (admin+)')
  .option('--role <role>', 'viewer | editor | admin | owner', 'editor')
  .action(async (orgId: string, email: string, opts: { role: string }) => {
    requireToken();
    try {
      await api(`/api/orgs/${orgId}/members`, {
        method: 'POST',
        body: { email, role: opts.role },
      });
      console.log(`Invited ${email} to ${orgId} as ${opts.role}.`);
    } catch (err) {
      fail(err);
    }
  });

org
  .command('use <org>')
  .description('Set the active org for this machine (sent as X-Organization-ID)')
  .action(async (orgId: string) => {
    requireToken();
    const config = loadConfig();
    config.org = orgId;
    saveConfig(config);
    console.log(`Active org: ${orgId}`);
    // Best-effort: also persist as the server-side default (for session logins
    // and unpinned keys). Membership is enforced server-side.
    try {
      await api(`/api/orgs/${orgId}/select`, { method: 'POST' });
    } catch (err) {
      if (err instanceof ApiError && (err.status === 404 || err.status === 403)) {
        console.error(`Warning: you don't appear to be a member of ${orgId}.`);
      }
    }
  });

org
  .command('current')
  .description('Show the active org')
  .action(() => {
    const active = resolveOrg();
    console.log(active ? `Active org: ${active}` : 'No active org set (using your default).');
  });

org
  .command('clear')
  .description('Clear the active org override (fall back to your default)')
  .action(() => {
    const config = loadConfig();
    delete config.org;
    saveConfig(config);
    console.log('Active org cleared.');
  });

const workspaceCmd = program.command('workspace').description('Workspace commands');

workspaceCmd
  .command('list <orgId>')
  .description('List workspaces in an org')
  .action(async (orgId: string) => {
    requireToken();
    try {
      const list = await api<{ name: string; slug: string }[]>(`/api/orgs/${orgId}/workspaces`);
      if (!list.length) return console.log('No workspaces.');
      for (const ws of list) console.log(`- ${ws.name} (${ws.slug})`);
    } catch (err) {
      fail(err);
    }
  });

workspaceCmd
  .command('create <orgId> <name>')
  .description('Create a workspace in an org (editor+)')
  .option('--slug <slug>', 'URL slug (defaults to a slugified name)')
  .action(async (orgId: string, name: string, opts: { slug?: string }) => {
    requireToken();
    try {
      const ws = await api<{ slug: string }>(`/api/orgs/${orgId}/workspaces`, {
        method: 'POST',
        body: { name, slug: opts.slug },
      });
      console.log(`Created workspace ${name} (${ws.slug}). Use it with: magpie link --workspace ${ws.slug}`);
    } catch (err) {
      fail(err);
    }
  });

const projectCmd = program.command('project').description('Project commands');

projectCmd
  .command('list <workspaceId>')
  .description('List projects in a workspace')
  .action(async (workspaceId: string) => {
    requireToken();
    try {
      const list = await api<{ name: string; slug: string }[]>(
        `/api/workspaces/${workspaceId}/projects`,
      );
      if (!list.length) return console.log('No projects.');
      for (const p of list) console.log(`- ${p.name} (${p.slug})`);
    } catch (err) {
      fail(err);
    }
  });

projectCmd
  .command('create <workspaceId> <name>')
  .description('Create a project in a workspace (editor+)')
  .option('--slug <slug>', 'URL slug (defaults to a slugified name)')
  .action(async (workspaceId: string, name: string, opts: { slug?: string }) => {
    requireToken();
    try {
      const p = await api<{ slug: string }>(`/api/workspaces/${workspaceId}/projects`, {
        method: 'POST',
        body: { name, slug: opts.slug },
      });
      console.log(`Created project ${name} (${p.slug}). Use it with: magpie link --project ${p.slug}`);
    } catch (err) {
      fail(err);
    }
  });

// -- Knowledge --

program
  .command('search <query>')
  .description('Search knowledge (semantic + keyword)')
  .option('--workspace <workspace>')
  .option('--project <project>')
  .option('--limit <n>', 'Max results', '10')
  .action(async (query: string, opts: { workspace?: string; project?: string; limit: string }) => {
    requireToken();
    try {
      const results = await api<Entry[]>('/api/search', {
        method: 'POST',
        body: { query, ...scope(opts), limit: parseInt(opts.limit, 10) },
      });
      if (!results.length) return console.log('No results.');
      for (const e of results) console.log(entryLine(e));
    } catch (err) {
      fail(err);
    }
  });

program
  .command('read <entryId>')
  .description('Read an entry')
  .option('--resolved', 'Resolve {{references}} and [[wikilinks]]')
  .action(async (entryId: string, opts: { resolved?: boolean }) => {
    requireToken();
    try {
      const entry = await api<Entry>(`/api/entries/${entryId}`);
      let content = entry.content;
      if (opts.resolved) {
        const resolution = await api<{ markdown: string }>(`/api/entries/${entryId}/resolve`, {
          method: 'POST',
        });
        content = resolution.markdown;
      }
      const ws = entry.workspace || 'general';
      console.log(`# [${entry.project ? `${ws}/${entry.project}` : ws}] ${entry.title}\n`);
      console.log(content);
    } catch (err) {
      fail(err);
    }
  });

interface Revision {
  previous_title: string;
  previous_content: string;
  previous_tags: string[];
  previous_source: string | null;
  actor_type: string | null;
  created_at: string;
}

program
  .command('history <entryId>')
  .description('Show previous versions of an entry (newest first)')
  .option('--limit <n>', 'Max revisions (capped at 100)', '20')
  .option('--full', 'Print the full previous content of each revision')
  .action(async (entryId: string, opts: { limit: string; full?: boolean }) => {
    requireToken();
    try {
      const revisions = await api<Revision[]>(
        `/api/entries/${entryId}/history${qs({ limit: opts.limit })}`,
      );
      if (!revisions.length) return console.log('No prior revisions (current version is the only one).');
      for (const r of revisions) {
        console.log(`\n${r.created_at}  (by ${r.actor_type || 'unknown'})`);
        console.log(`  ${r.previous_title} [${(r.previous_tags || []).join(', ')}]`);
        if (opts.full) console.log(`\n${r.previous_content}\n`);
      }
    } catch (err) {
      fail(err);
    }
  });

program
  .command('write')
  .description('Create a knowledge entry')
  .requiredOption('--title <title>')
  .option('--file <path>', 'Markdown file with the content')
  .option('--content <content>', 'Inline content')
  .option('--tags <tags>', 'Comma-separated tags')
  .option('--dedupe', 'Update an existing similar entry instead of creating a duplicate')
  .option('--workspace <workspace>')
  .option('--project <project>')
  .action(async (opts: {
    title: string; file?: string; content?: string;
    tags?: string; dedupe?: boolean; workspace?: string; project?: string;
  }) => {
    requireToken();
    try {
      const content = opts.file ? readFileSync(opts.file, 'utf-8') : opts.content;
      if (!content) fail(new Error('Provide --file or --content'));
      const entry = await api<Entry>('/api/entries', {
        method: 'POST',
        body: {
          title: opts.title,
          content,
          tags: opts.tags ? opts.tags.split(',').map((t) => t.trim()) : [],
          dedupe: opts.dedupe || false,
          ...scope(opts),
        },
      });
      console.log(`${opts.dedupe ? 'Saved' : 'Created'} entry ${entry.id}: ${entry.title}`);
    } catch (err) {
      fail(err);
    }
  });

program
  .command('archive <entryId>')
  .description('Archive an entry')
  .action(async (entryId: string) => {
    requireToken();
    try {
      await api(`/api/entries/${entryId}/archive`, { method: 'POST' });
      console.log(`Archived ${entryId}.`);
    } catch (err) {
      fail(err);
    }
  });

program
  .command('unarchive <entryId>')
  .description('Unarchive an entry')
  .action(async (entryId: string) => {
    requireToken();
    try {
      await api(`/api/entries/${entryId}/unarchive`, { method: 'POST' });
      console.log(`Unarchived ${entryId}.`);
    } catch (err) {
      fail(err);
    }
  });

interface DuplicateEntry {
  id: string;
  title: string;
  workspace: string | null;
  tags: string[];
  content: string;
  min_distance: number;
}

program
  .command('duplicates')
  .description('Find clusters of near-duplicate entries by semantic similarity')
  .option('--workspace <workspace>')
  .option('--project <project>')
  .option('--threshold <n>', 'Cosine distance threshold — lower is stricter', '0.12')
  .option('--limit <n>', 'Max pairs to consider', '50')
  .action(async (opts: { workspace?: string; project?: string; threshold: string; limit: string }) => {
    requireToken();
    try {
      const { clusters } = await api<{ clusters: DuplicateEntry[][] }>('/api/entries/find-duplicates', {
        method: 'POST',
        body: { ...scope(opts), threshold: parseFloat(opts.threshold), limit: parseInt(opts.limit, 10) },
      });
      if (!clusters.length) return console.log('No duplicate clusters found.');
      clusters.forEach((cluster, i) => {
        console.log(`\nCluster ${i + 1} (${cluster.length} entries):`);
        for (const e of cluster) {
          const ws = e.workspace || 'general';
          console.log(`  - ${e.title} [${ws}] (dist: ${e.min_distance.toFixed(3)})\n    id: ${e.id}`);
        }
      });
    } catch (err) {
      fail(err);
    }
  });

program
  .command('merge <ids...>')
  .description('Merge entries into one (sources archived with lineage)')
  .requiredOption('--title <title>')
  .option('--file <path>', 'Markdown file with the merged content')
  .option('--content <content>', 'Inline merged content')
  .option('--tags <tags>', 'Comma-separated tags')
  .option('--workspace <workspace>')
  .option('--project <project>')
  .action(async (ids: string[], opts: {
    title: string; file?: string; content?: string;
    tags?: string; workspace?: string; project?: string;
  }) => {
    requireToken();
    try {
      if (ids.length < 2) fail(new Error('Provide at least 2 entry IDs to merge'));
      const content = opts.file ? readFileSync(opts.file, 'utf-8') : opts.content;
      if (!content) fail(new Error('Provide --file or --content for the merged entry'));
      const entry = await api<Entry>('/api/entries/merge', {
        method: 'POST',
        body: {
          source_ids: ids,
          title: opts.title,
          content,
          tags: opts.tags ? opts.tags.split(',').map((t) => t.trim()) : [],
          ...scope(opts),
        },
      });
      console.log(`Merged ${ids.length} entries into ${entry.id}: ${entry.title}`);
    } catch (err) {
      fail(err);
    }
  });

interface BulkScopeView {
  workspace: string | null;
  project: string | null;
  tags: string[];
}

interface BulkResult {
  matched: number;
  updated: number;
  applied: boolean;
  sample: { title: string; before: BulkScopeView; after: BulkScopeView }[];
}

const collect = (value: string, acc: string[]): string[] => {
  acc.push(value);
  return acc;
};

function printBulk(result: BulkResult): void {
  const fmt = (v: BulkScopeView) =>
    `${v.workspace || '—'}/${v.project || '—'} [${v.tags.join(', ')}]`;
  for (const s of result.sample) {
    console.log(`  - ${s.title}: ${fmt(s.before)} → ${fmt(s.after)}`);
  }
  if (result.applied) {
    const n = result.updated;
    console.log(`Applied to ${n} entr${n === 1 ? 'y' : 'ies'}.`);
  } else {
    const n = result.matched;
    console.log(
      `Dry run: ${n} entr${n === 1 ? 'y' : 'ies'} would change. ` +
        `Re-run with --apply to commit (requires admin).`
    );
  }
}

async function runBulk(
  match: Record<string, unknown>,
  changes: Record<string, unknown>,
  apply: boolean
): Promise<void> {
  requireToken();
  try {
    const result = await api<BulkResult>('/api/entries/bulk', {
      method: 'POST',
      body: { match, changes, dry_run: !apply },
    });
    printBulk(result);
  } catch (err) {
    fail(err);
  }
}

program
  .command('rescope')
  .description('Bulk-move entries to a new workspace/project (dry-run unless --apply)')
  .option('--workspace <workspace>', 'Match: only entries in this workspace')
  .option('--project <project>', 'Match: only entries in this project')
  .option('--tag <tag>', 'Match: entries having this tag (repeatable)', collect, [])
  .option('--source <source>', 'Match: only entries with this source')
  .option('--to-workspace <workspace>', 'Move matched entries to this workspace')
  .option('--to-project <project>', 'Move matched entries to this project')
  .option('--clear-project', 'Clear the project (e.g. retiring a project namespace)')
  .option('--apply', 'Apply the change (default is a dry-run preview)')
  .action(
    async (opts: {
      workspace?: string;
      project?: string;
      tag: string[];
      source?: string;
      toWorkspace?: string;
      toProject?: string;
      clearProject?: boolean;
      apply?: boolean;
    }) => {
      await runBulk(
        {
          workspace: opts.workspace,
          project: opts.project,
          tags: opts.tag.length ? opts.tag : undefined,
          source: opts.source,
        },
        {
          workspace: opts.toWorkspace,
          project: opts.toProject,
          clear: opts.clearProject ? ['project'] : undefined,
        },
        Boolean(opts.apply)
      );
    }
  );

program
  .command('retag')
  .description('Bulk add/remove/rename tags on entries (dry-run unless --apply)')
  .option('--workspace <workspace>', 'Match: only entries in this workspace')
  .option('--project <project>', 'Match: only entries in this project')
  .option('--tag <tag>', 'Match: entries having this tag (repeatable)', collect, [])
  .option('--source <source>', 'Match: only entries with this source')
  .option('--add <tag>', 'Add this tag to matched entries (repeatable)', collect, [])
  .option('--remove <tag>', 'Remove this tag from matched entries (repeatable)', collect, [])
  .option('--rename <old=new>', 'Rename a tag across matched entries')
  .option('--apply', 'Apply the change (default is a dry-run preview)')
  .action(
    async (opts: {
      workspace?: string;
      project?: string;
      tag: string[];
      source?: string;
      add: string[];
      remove: string[];
      rename?: string;
      apply?: boolean;
    }) => {
      let renameFrom: string | undefined;
      let renameTo: string | undefined;
      if (opts.rename) {
        const eq = opts.rename.indexOf('=');
        if (eq < 1) fail(new Error('--rename expects old=new'));
        renameFrom = opts.rename.slice(0, eq);
        renameTo = opts.rename.slice(eq + 1);
      }
      await runBulk(
        {
          workspace: opts.workspace,
          project: opts.project,
          tags: opts.tag.length ? opts.tag : undefined,
          source: opts.source,
        },
        {
          add_tags: opts.add.length ? opts.add : undefined,
          remove_tags: opts.remove.length ? opts.remove : undefined,
          rename_from: renameFrom,
          rename_to: renameTo,
        },
        Boolean(opts.apply)
      );
    }
  );

interface ActivityEvent {
  action: string;
  subject_title: string | null;
  subject_id: string | null;
  workspace: string | null;
  project: string | null;
  at: string;
  actor_type: string | null;
}

program
  .command('updates')
  .description('Recent activity across the store (newest first) — what changed, when, and by whom')
  .option('--workspace <workspace>')
  .option('--project <project>')
  .option('--limit <n>', 'Max events (capped at 100)', '20')
  .action(async (opts: { workspace?: string; project?: string; limit: string }) => {
    requireToken();
    try {
      const s = scope(opts);
      const events = await api<ActivityEvent[]>(
        `/api/updates${qs({ workspace: s.workspace, project: s.project, limit: opts.limit })}`,
      );
      if (!events.length) return console.log('No recent activity.');
      for (const e of events) {
        const ws = e.workspace || 'general';
        const scopeStr = e.project ? `${ws}/${e.project}` : ws;
        const title = e.subject_title || e.subject_id || '';
        console.log(`${e.at}  ${e.action}  ${title} [${scopeStr}] (by ${e.actor_type || 'unknown'})`);
      }
    } catch (err) {
      fail(err);
    }
  });

// -- KV stores --

const kv = program.command('kv').description('KV store commands');

kv
  .command('list')
  .description('List KV stores')
  .option('--workspace <workspace>')
  .option('--project <project>')
  .action(async (opts: { workspace?: string; project?: string }) => {
    requireToken();
    try {
      const s = scope(opts);
      const list = await api<{ slug: string; title: string; key_count: number }[]>(
        `/api/kv${qs({ workspace: s.workspace, project: s.project })}`
      );
      if (!list.length) return console.log('No KV stores.');
      for (const c of list) console.log(`- ${c.slug} (${c.key_count} keys) — ${c.title}`);
    } catch (err) {
      fail(err);
    }
  });

kv
  .command('get <slug> <key>')
  .description('Read a key (prints the value as JSON)')
  .action(async (slug: string, key: string) => {
    requireToken();
    try {
      const doc = await api<{ value: unknown; value_type: string }>(
        `/api/kv/${slug}/keys/${key}`
      );
      console.log(JSON.stringify(doc.value, null, 2));
    } catch (err) {
      fail(err);
    }
  });

kv
  .command('history <slug> <key>')
  .description('Show previous values of a KV key (newest first)')
  .option('--limit <n>', 'Max revisions (capped at 100)', '20')
  .action(async (slug: string, key: string, opts: { limit: string }) => {
    requireToken();
    try {
      const revisions = await api<{
        previous_value: unknown; previous_value_type: string;
        previous_summary: string | null; actor_type: string | null; created_at: string;
      }[]>(`/api/kv/${slug}/keys/${key}/history${qs({ limit: opts.limit })}`);
      if (!revisions.length) return console.log('No prior revisions (current value is the only one).');
      for (const r of revisions) {
        console.log(`\n${r.created_at}  (by ${r.actor_type || 'unknown'}) [${r.previous_value_type}]`);
        console.log(JSON.stringify(r.previous_value, null, 2));
      }
    } catch (err) {
      fail(err);
    }
  });

kv
  .command('set <slug> <key>')
  .description('Write a key from a JSON file or inline value')
  .option('--file <path>', 'JSON file with the value')
  .option('--value <json>', 'Inline JSON value')
  .option('--type <type>', 'json | string | integer | float | boolean | datetime', 'json')
  .option('--summary <summary>')
  .action(async (slug: string, key: string, opts: {
    file?: string; value?: string; type: string; summary?: string;
  }) => {
    requireToken();
    try {
      const raw = opts.file ? readFileSync(opts.file, 'utf-8') : opts.value;
      if (raw === undefined) fail(new Error('Provide --file or --value'));
      const value = JSON.parse(raw);
      await api(`/api/kv/${slug}/keys/${key}`, {
        method: 'PUT',
        body: { value, value_type: opts.type, summary: opts.summary },
      });
      console.log(`Set ${slug}/${key} (${opts.type}).`);
    } catch (err) {
      fail(err);
    }
  });

// -- Attachments --

const attachments = program.command('attachments').description('Attachment commands');

attachments
  .command('add <entryId> <file>')
  .description('Attach a file to an entry')
  .option('--role <role>', 'Role tag (e.g. logo-primary, query-revenue)')
  .option('--description <description>')
  .option('--public', 'Serve via stable /public/assets URL (images only)')
  .action(async (entryId: string, file: string, opts: {
    role?: string; description?: string; public?: boolean;
  }) => {
    requireToken();
    try {
      const data = readFileSync(file);
      const form = new FormData();
      form.append('file', new Blob([new Uint8Array(data)]), basename(file));
      if (opts.role) form.append('role', opts.role);
      if (opts.description) form.append('description', opts.description);
      if (opts.public) form.append('public', 'true');
      const att = await api<{ handle: string; kind: string; byte_size: number }>(
        `/api/entries/${entryId}/attachments`,
        { method: 'POST', formData: form }
      );
      console.log(`Attached ${basename(file)} (${att.kind}, ${att.byte_size} bytes). Handle: ${att.handle}`);
    } catch (err) {
      fail(err);
    }
  });

attachments
  .command('list <entryId>')
  .description('List attachments on an entry')
  .action(async (entryId: string) => {
    requireToken();
    try {
      const list = await api<{
        filename: string; kind: string; role: string | null; byte_size: number; handle: string;
      }[]>(`/api/entries/${entryId}/attachments`);
      if (!list.length) return console.log('No attachments.');
      for (const a of list) {
        const role = a.role ? ` role=${a.role}` : '';
        console.log(`- ${a.filename} [${a.kind}]${role} (${a.byte_size} bytes) ${a.handle}`);
      }
    } catch (err) {
      fail(err);
    }
  });

// -- Import --

program
  .command('import <dir>')
  .description('Import markdown files from a directory as entries')
  .option('--workspace <workspace>')
  .option('--project <project>')
  .action(async (dir: string, opts: { workspace?: string; project?: string }) => {
    requireToken();
    try {
      const files: string[] = [];
      const walk = (d: string) => {
        for (const name of readdirSync(d)) {
          const path = join(d, name);
          if (statSync(path).isDirectory()) walk(path);
          else if (extname(name) === '.md') files.push(path);
        }
      };
      walk(dir);
      let count = 0;
      for (const file of files) {
        const content = readFileSync(file, 'utf-8').trim();
        if (!content) continue;
        const title = basename(file, '.md').replace(/[-_]/g, ' ');
        await api('/api/entries', {
          method: 'POST',
          body: { title, content, source: 'cli-import', ...scope(opts) },
        });
        console.log(`  Imported: ${title}`);
        count++;
      }
      console.log(`Imported ${count} entries.`);
    } catch (err) {
      fail(err);
    }
  });

// -- Repo sync (bundles) --

interface PushResult {
  created: number;
  updated: number;
  stores: number;
  pairs: number;
  warnings: string[];
}

program
  .command('push <dir>')
  .description('Sync a knowledge bundle to the server (repo = source of truth)')
  .option('--workspace <workspace>')
  .option('--project <project>')
  .action(async (dir: string, opts: { workspace?: string; project?: string }) => {
    requireToken();
    try {
      // Entries: every .md outside the reserved kv/ and attachments/ dirs.
      const entries: { path: string; text: string }[] = [];
      const walk = (d: string, relBase = '') => {
        for (const name of readdirSync(d)) {
          const abs = join(d, name);
          const rel = relBase ? `${relBase}/${name}` : name;
          if (statSync(abs).isDirectory()) {
            if (!relBase && (name === 'kv' || name === 'attachments')) continue;
            walk(abs, rel);
          } else if (extname(name) === '.md') {
            entries.push({ path: rel, text: readFileSync(abs, 'utf-8') });
          }
        }
      };
      walk(dir);

      // Repo-canonical KV stores + the anti-drift manifest.
      const kv: { slug: string; text: string }[] = [];
      let manifest: unknown = null;
      const kvDir = join(dir, 'kv');
      if (existsSync(kvDir)) {
        for (const name of readdirSync(kvDir)) {
          if (extname(name) !== '.json') continue;
          const text = readFileSync(join(kvDir, name), 'utf-8');
          if (name === '_manifest.json') manifest = JSON.parse(text);
          else kv.push({ slug: basename(name, '.json'), text });
        }
      }

      const res = await api<PushResult>('/api/bundle/push', {
        method: 'POST',
        body: { entries, kv, manifest, ...scope(opts) },
      });
      for (const w of res.warnings) console.log(`  warning: ${w}`);
      console.log(
        `Pushed ${res.created + res.updated} entries (${res.created} created, ` +
          `${res.updated} updated) and ${res.stores} repo KV stores (${res.pairs} keys).`
      );
    } catch (err) {
      fail(err);
    }
  });

program
  .command('export <dir>')
  .description('Export entries and repo-canonical KV stores as a bundle on disk')
  .option('--workspace <workspace>')
  .option('--project <project>')
  .action(async (dir: string, opts: { workspace?: string; project?: string }) => {
    requireToken();
    try {
      const s = scope(opts);
      const res = await api<{ files: { path: string; content: string }[]; entries: number; stores: number }>(
        `/api/bundle/export${qs({ workspace: s.workspace, project: s.project })}`
      );
      for (const file of res.files) {
        const dest = join(dir, file.path);
        mkdirSync(dirname(dest), { recursive: true });
        writeFileSync(dest, file.content);
      }
      console.log(
        `Exported ${res.entries} entries and ${res.stores} repo KV stores to ${dir} ` +
          `(open ${join(dir, 'index.html')} to browse).`
      );
    } catch (err) {
      fail(err);
    }
  });

// -- MCP stdio --

program
  .command('mcp')
  .description('Run an MCP stdio server proxying to the Magpie API (for local agent setups)')
  .action(async () => {
    requireToken();
    await runMcpServer();
  });

if (process.argv.length <= 2) {
  program.outputHelp();
  process.exit(0);
}

program.parseAsync().catch(fail);
