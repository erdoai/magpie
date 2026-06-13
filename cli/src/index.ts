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
  category: string;
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
  .version('0.2.0');

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
  return `- ${e.title} [${scopeStr}/${e.category}]${score}\n  id: ${e.id}`;
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
  .description('Sign in with email OTP and store an API key locally')
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

      // Mint an API key for the CLI using the fresh session
      const keyRes = await fetch(`${base}/api/keys`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Cookie: cookie.split(';')[0] },
        body: JSON.stringify({ name: `cli-${new Date().toISOString().slice(0, 10)}` }),
      });
      if (!keyRes.ok) fail(new ApiError(keyRes.status, await keyRes.text()));
      const key = (await keyRes.json()) as { key: string };

      const config = loadConfig();
      config.token = key.key;
      saveConfig(config);
      console.log(`Signed in as ${body.user.email}. API key stored in ~/.config/magpie/.`);
    } catch (err) {
      fail(err);
    }
  });

program
  .command('logout')
  .description('Remove the stored API key')
  .action(() => {
    clearToken();
    console.log('Logged out.');
  });

program
  .command('whoami')
  .description('Show server, auth, and linked scope')
  .action(async () => {
    const config = loadConfig();
    console.log(`Server: ${resolveApiUrl()}`);
    const token = resolveToken();
    if (!token) {
      console.log('Auth: not signed in');
      return;
    }
    console.log(`Auth: API key ${token.slice(0, 12)}…`);
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

// -- Knowledge --

program
  .command('search <query>')
  .description('Search knowledge (semantic + keyword)')
  .option('--workspace <workspace>')
  .option('--project <project>')
  .option('--category <category>')
  .option('--limit <n>', 'Max results', '10')
  .action(async (query: string, opts: { workspace?: string; project?: string; category?: string; limit: string }) => {
    requireToken();
    try {
      const results = await api<Entry[]>('/api/search', {
        method: 'POST',
        body: { query, ...scope(opts), category: opts.category, limit: parseInt(opts.limit, 10) },
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

program
  .command('write')
  .description('Create a knowledge entry')
  .requiredOption('--title <title>')
  .option('--file <path>', 'Markdown file with the content')
  .option('--content <content>', 'Inline content')
  .option('--category <category>', 'project | area | resource', 'resource')
  .option('--tags <tags>', 'Comma-separated tags')
  .option('--workspace <workspace>')
  .option('--project <project>')
  .action(async (opts: {
    title: string; file?: string; content?: string; category: string;
    tags?: string; workspace?: string; project?: string;
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
          category: opts.category,
          tags: opts.tags ? opts.tags.split(',').map((t) => t.trim()) : [],
          ...scope(opts),
        },
      });
      console.log(`Created entry ${entry.id}: ${entry.title}`);
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

// -- Collections --

const collections = program.command('collections').description('Collection commands');

collections
  .command('list')
  .description('List collections')
  .option('--workspace <workspace>')
  .option('--project <project>')
  .action(async (opts: { workspace?: string; project?: string }) => {
    requireToken();
    try {
      const s = scope(opts);
      const list = await api<{ slug: string; title: string; document_count: number }[]>(
        `/api/collections${qs({ workspace: s.workspace, project: s.project })}`
      );
      if (!list.length) return console.log('No collections.');
      for (const c of list) console.log(`- ${c.slug} (${c.document_count} docs) — ${c.title}`);
    } catch (err) {
      fail(err);
    }
  });

collections
  .command('get <slug> <key>')
  .description('Read a document (prints the value as JSON)')
  .action(async (slug: string, key: string) => {
    requireToken();
    try {
      const doc = await api<{ value: unknown; value_type: string }>(
        `/api/collections/${slug}/documents/${key}`
      );
      console.log(JSON.stringify(doc.value, null, 2));
    } catch (err) {
      fail(err);
    }
  });

collections
  .command('set <slug> <key>')
  .description('Write a document from a JSON file or inline value')
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
      await api(`/api/collections/${slug}/documents/${key}`, {
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
  collections: number;
  documents: number;
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
      // Entries: every .md outside the reserved collections/ and attachments/ dirs.
      const entries: { path: string; text: string }[] = [];
      const walk = (d: string, relBase = '') => {
        for (const name of readdirSync(d)) {
          const abs = join(d, name);
          const rel = relBase ? `${relBase}/${name}` : name;
          if (statSync(abs).isDirectory()) {
            if (!relBase && (name === 'collections' || name === 'attachments')) continue;
            walk(abs, rel);
          } else if (extname(name) === '.md') {
            entries.push({ path: rel, text: readFileSync(abs, 'utf-8') });
          }
        }
      };
      walk(dir);

      // Repo-canonical collections + the anti-drift manifest.
      const collections: { slug: string; text: string }[] = [];
      let manifest: unknown = null;
      const colDir = join(dir, 'collections');
      if (existsSync(colDir)) {
        for (const name of readdirSync(colDir)) {
          if (extname(name) !== '.json') continue;
          const text = readFileSync(join(colDir, name), 'utf-8');
          if (name === '_manifest.json') manifest = JSON.parse(text);
          else collections.push({ slug: basename(name, '.json'), text });
        }
      }

      const res = await api<PushResult>('/api/bundle/push', {
        method: 'POST',
        body: { entries, collections, manifest, ...scope(opts) },
      });
      for (const w of res.warnings) console.log(`  warning: ${w}`);
      console.log(
        `Pushed ${res.created + res.updated} entries (${res.created} created, ` +
          `${res.updated} updated) and ${res.collections} repo collections (${res.documents} docs).`
      );
    } catch (err) {
      fail(err);
    }
  });

program
  .command('export <dir>')
  .description('Export entries and repo-canonical collections as a bundle on disk')
  .option('--workspace <workspace>')
  .option('--project <project>')
  .action(async (dir: string, opts: { workspace?: string; project?: string }) => {
    requireToken();
    try {
      const s = scope(opts);
      const res = await api<{ files: { path: string; content: string }[]; entries: number; collections: number }>(
        `/api/bundle/export${qs({ workspace: s.workspace, project: s.project })}`
      );
      for (const file of res.files) {
        const dest = join(dir, file.path);
        mkdirSync(dirname(dest), { recursive: true });
        writeFileSync(dest, file.content);
      }
      console.log(
        `Exported ${res.entries} entries and ${res.collections} repo collections to ${dir} ` +
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

program.parseAsync().catch(fail);
