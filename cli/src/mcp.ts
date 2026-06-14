/**
 * MCP stdio server — exposes Magpie knowledge tools to local agents
 * (Claude Code, etc.) by proxying to the Magpie REST API with the
 * stored/env API key. Mirrors the hosted /mcp tool surface.
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';
import { api, qs } from './client.js';
import { loadConfig } from './config.js';

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

function text(content: string) {
  return { content: [{ type: 'text' as const, text: content }] };
}

function entryScope(e: Entry): string {
  const ws = e.workspace || 'general';
  return e.project ? `${ws}/${e.project}` : ws;
}

function formatEntry(e: Entry): string {
  return (
    `## [${entryScope(e)}] ${e.title}${e.score != null ? ` (score: ${e.score})` : ''}\n` +
    `Category: ${e.category} | Tags: ${(e.tags || []).join(', ')}\n` +
    `ID: ${e.id}\n\n${e.content}`
  );
}

async function guarded(fn: () => Promise<{ content: { type: 'text'; text: string }[] }>) {
  try {
    return await fn();
  } catch (err) {
    return text(`Error: ${err instanceof Error ? err.message : String(err)}`);
  }
}

export async function runMcpServer(): Promise<void> {
  const config = loadConfig();
  const server = new McpServer({ name: 'magpie', version: '0.1.0' });

  const scopeArgs = {
    workspace: z.string().optional().describe('Workspace (app/product namespace)'),
    project: z.string().optional().describe('Project within the workspace'),
  };

  const applyScope = (args: { workspace?: string; project?: string }) => ({
    workspace: args.workspace || config.workspace,
    project: args.project || config.project,
  });

  server.tool(
    'search',
    'Search the knowledge base. Semantic + keyword matching.',
    {
      query: z.string().describe('Natural-language query'),
      ...scopeArgs,
      category: z.string().optional().describe('project | area | resource | archive'),
      limit: z.number().optional().describe('Max results (default 10)'),
    },
    async (args) =>
      guarded(async () => {
        const results = await api<Entry[]>('/api/search', {
          method: 'POST',
          body: { query: args.query, ...applyScope(args), category: args.category, limit: args.limit ?? 10 },
        });
        if (!results.length) return text('No entries found.');
        return text(results.map(formatEntry).join('\n\n---\n\n'));
      })
  );

  server.tool(
    'read',
    'Read a knowledge entry by ID, with links, backlinks, and attachments.',
    {
      id: z.string().describe('Entry ID'),
      resolved: z.boolean().optional().describe('Resolve {{references}} and [[wikilinks]]'),
    },
    async (args) =>
      guarded(async () => {
        const entry = await api<Entry>(`/api/entries/${args.id}`);
        let content = entry.content;
        if (args.resolved) {
          const resolution = await api<{ markdown: string }>(
            `/api/entries/${args.id}/resolve`,
            { method: 'POST' }
          );
          content = resolution.markdown;
        }
        return text(`# [${entryScope(entry)}] ${entry.title}\nID: ${entry.id}\n\n${content}`);
      })
  );

  server.tool(
    'write',
    'Save knowledge — learnings, decisions, patterns worth remembering across sessions.',
    {
      title: z.string(),
      content: z.string().describe('Markdown content with context and reasoning'),
      ...scopeArgs,
      category: z.string().optional().describe('project | area | resource (default resource)'),
      tags: z.array(z.string()).optional(),
      dedupe: z.boolean().optional().describe('Update an existing similar entry if found'),
    },
    async (args) =>
      guarded(async () => {
        const entry = await api<Entry>('/api/entries', {
          method: 'POST',
          body: {
            title: args.title,
            content: args.content,
            category: args.category || 'resource',
            tags: args.tags || [],
            dedupe: args.dedupe || false,
            source: 'magpie-cli-mcp',
            ...applyScope(args),
          },
        });
        return text(`Created entry ${entry.id} in [${entryScope(entry)}]: ${entry.title}`);
      })
  );

  server.tool(
    'list_entries',
    'Browse knowledge entries (use search for specific queries).',
    {
      ...scopeArgs,
      category: z.string().optional(),
      limit: z.number().optional(),
    },
    async (args) =>
      guarded(async () => {
        const s = applyScope(args);
        const entries = await api<Entry[]>(
          `/api/entries${qs({
            workspace: s.workspace,
            project: s.project,
            category: args.category,
            limit: String(args.limit ?? 20),
          })}`
        );
        if (!entries.length) return text('No entries found.');
        return text(
          entries
            .map((e) => `- ${e.title} [${entryScope(e)}/${e.category}] (${e.id.slice(0, 8)}…)`)
            .join('\n')
        );
      })
  );

  server.tool(
    'archive',
    'Archive a knowledge entry — removes it from search results.',
    { id: z.string().describe('Entry ID') },
    async (args) =>
      guarded(async () => {
        await api(`/api/entries/${args.id}/archive`, { method: 'POST' });
        return text(`Archived entry ${args.id}.`);
      })
  );

  server.tool(
    'find_duplicates',
    'Find clusters of near-duplicate entries by semantic similarity. Use before merging to spot consolidation opportunities.',
    {
      ...scopeArgs,
      threshold: z.number().optional().describe('Cosine distance threshold — lower is stricter (default 0.12)'),
      limit: z.number().optional().describe('Max pairs to consider (default 50)'),
    },
    async (args) =>
      guarded(async () => {
        const s = applyScope(args);
        const { clusters } = await api<{
          clusters: {
            id: string; title: string; workspace: string | null;
            tags: string[]; content: string; min_distance: number;
          }[][];
        }>('/api/entries/find-duplicates', {
          method: 'POST',
          body: { workspace: s.workspace, project: s.project, threshold: args.threshold ?? 0.12, limit: args.limit ?? 50 },
        });
        if (!clusters.length) return text('No duplicate clusters found.');
        const parts = clusters.map((cluster, i) => {
          const lines = [`## Cluster ${i + 1} (${cluster.length} entries)`];
          for (const e of cluster) {
            const ws = e.workspace || 'general';
            const snippet = (e.content || '').slice(0, 120).replace(/\n/g, ' ');
            lines.push(
              `- **${e.title}** [${ws}] (id: ${e.id}, dist: ${(e.min_distance ?? 0).toFixed(3)})\n` +
                `  Tags: ${(e.tags || []).join(', ')}\n  ${snippet}…`
            );
          }
          return lines.join('\n');
        });
        return text(parts.join('\n\n'));
      })
  );

  server.tool(
    'merge',
    'Merge several entries into one; the sources are archived with lineage. You provide the synthesized title and content.',
    {
      source_ids: z.array(z.string()).describe('Entry IDs to merge (2+, archived after)'),
      title: z.string(),
      content: z.string().describe('Synthesized merged content (markdown)'),
      category: z.string().optional().describe('project | area | resource (default resource)'),
      tags: z.array(z.string()).optional(),
      ...scopeArgs,
    },
    async (args) =>
      guarded(async () => {
        const entry = await api<Entry>('/api/entries/merge', {
          method: 'POST',
          body: {
            source_ids: args.source_ids,
            title: args.title,
            content: args.content,
            category: args.category || 'resource',
            tags: args.tags || [],
            ...applyScope(args),
          },
        });
        return text(`Merged ${args.source_ids.length} entries into ${entry.id} [${entryScope(entry)}]: ${entry.title}`);
      })
  );

  server.tool(
    'resolve_knowledge',
    'Resolve an entry\'s {{references}} and [[wikilinks]]; returns rendered Markdown plus a dependency report.',
    { id: z.string().describe('Entry ID') },
    async (args) =>
      guarded(async () => {
        const resolution = await api<{
          markdown: string;
          dependencies: { ref: string; kind: string; status: string; detail?: string }[];
        }>(`/api/entries/${args.id}/resolve`, { method: 'POST' });
        const deps = resolution.dependencies.length
          ? '\n\n## Dependencies\n' +
            resolution.dependencies
              .map((d) => `- ${d.ref} [${d.kind}] ${d.status}${d.detail ? ` — ${d.detail}` : ''}`)
              .join('\n')
          : '';
        return text(resolution.markdown + deps);
      })
  );

  server.tool(
    'list_links',
    'List links and backlinks for an entry. Links come from [[wikilinks]]; backlinks are entries that reference this one.',
    { id: z.string().describe('Entry ID') },
    async (args) =>
      guarded(async () => {
        const { outgoing, backlinks } = await api<{
          outgoing: {
            link_text: string; target_type: string;
            target_title?: string; target_id?: string; target_ref?: string;
          }[];
          backlinks: { source_title: string; source_id: string }[];
        }>(`/api/entries/${args.id}/links`);
        if (!outgoing.length && !backlinks.length) return text('No links or backlinks.');
        const parts: string[] = [];
        if (outgoing.length) {
          parts.push(
            '## Links\n' +
              outgoing
                .map((l) => {
                  if (l.target_type === 'entry')
                    return `- [[${l.link_text}]] → ${l.target_title} (id: ${l.target_id})`;
                  if (l.target_type === 'url') return `- [[${l.link_text}]] → ${l.target_ref}`;
                  if (l.target_type === 'resource')
                    return `- [[${l.link_text}]] → resource ${l.target_ref}`;
                  return `- [[${l.link_text}]] (unresolved)`;
                })
                .join('\n')
          );
        }
        if (backlinks.length) {
          parts.push(
            '## Backlinks\n' +
              backlinks.map((b) => `- ${b.source_title} (id: ${b.source_id})`).join('\n')
          );
        }
        return text(parts.join('\n\n'));
      })
  );

  server.tool(
    'kv_list',
    'List KV stores — named typed key→value stores for structured context (config, brand tokens, metrics).',
    { ...scopeArgs },
    async (args) =>
      guarded(async () => {
        const s = applyScope(args);
        const cols = await api<{
          slug: string; description: string | null; key_count: number;
          workspace: string | null; project: string | null;
        }[]>(`/api/kv${qs({ workspace: s.workspace, project: s.project })}`);
        if (!cols.length) return text('No KV stores found.');
        return text(
          cols
            .map((c) => {
              const ws = c.workspace || 'global';
              const scope = c.project ? `${ws}/${c.project}` : ws;
              const desc = c.description ? ` — ${c.description}` : '';
              return `- **${c.slug}** [${scope}] (${c.key_count} keys)${desc}`;
            })
            .join('\n')
        );
      })
  );

  server.tool(
    'kv_get',
    'Read a typed value from a KV store by key.',
    {
      store: z.string().describe('KV store slug (e.g. reach.strategy)'),
      key: z.string(),
      ...scopeArgs,
    },
    async (args) =>
      guarded(async () => {
        const s = applyScope(args);
        const doc = await api<{ value: unknown; value_type: string; updated_at: string }>(
          `/api/kv/${args.store}/keys/${args.key}${qs({
            workspace: s.workspace,
            project: s.project,
          })}`
        );
        return text(
          `# ${args.store}/${args.key}\nType: ${doc.value_type} | Updated: ${doc.updated_at}\n\n` +
            JSON.stringify(doc.value, null, 2)
        );
      })
  );

  server.tool(
    'kv_set',
    'Write a typed value to a KV store (creates or overwrites by key).',
    {
      store: z.string(),
      key: z.string(),
      value: z.string().describe('JSON-encoded value (e.g. \'{"a":1}\', \'42\', \'"text"\')'),
      value_type: z
        .string()
        .optional()
        .describe('json | string | integer | float | boolean | datetime'),
      summary: z.string().optional(),
      ...scopeArgs,
    },
    async (args) =>
      guarded(async () => {
        const s = applyScope(args);
        await api(
          `/api/kv/${args.store}/keys/${args.key}${qs({
            workspace: s.workspace,
            project: s.project,
          })}`,
          {
            method: 'PUT',
            body: {
              value: JSON.parse(args.value),
              value_type: args.value_type || 'json',
              summary: args.summary,
            },
          }
        );
        return text(`Set ${args.store}/${args.key}.`);
      })
  );

  server.tool(
    'kv_delete',
    'Delete a key from a KV store. Rejected for repo-canonical stores.',
    { store: z.string(), key: z.string(), ...scopeArgs },
    async (args) =>
      guarded(async () => {
        const s = applyScope(args);
        await api(
          `/api/kv/${args.store}/keys/${args.key}${qs({
            workspace: s.workspace,
            project: s.project,
          })}`,
          { method: 'DELETE' }
        );
        return text(`Deleted ${args.store}/${args.key}.`);
      })
  );

  server.tool(
    'upload_attachment',
    'Attach a file to an entry (logos, screenshots, SQL, briefs). Future agents reuse the real asset via its magpie:<id> handle.',
    {
      entry_id: z.string(),
      filename: z.string().describe('Filename with extension (drives kind/media type)'),
      content_base64: z.string().describe('File bytes, base64-encoded'),
      description: z.string().optional().describe('What this is and when to use it'),
      role: z.string().optional().describe('Role tag, e.g. logo-primary, query-revenue'),
      public: z.boolean().optional().describe('Serve via stable /public/assets URL (images only)'),
    },
    async (args) =>
      guarded(async () => {
        const data = Buffer.from(args.content_base64, 'base64');
        if (!data.length) return text('Error: empty or invalid base64 content.');
        const form = new FormData();
        form.append('file', new Blob([new Uint8Array(data)]), args.filename);
        if (args.role) form.append('role', args.role);
        if (args.description) form.append('description', args.description);
        if (args.public) form.append('public', 'true');
        const att = await api<{ handle: string; kind: string; byte_size: number }>(
          `/api/entries/${args.entry_id}/attachments`,
          { method: 'POST', formData: form }
        );
        return text(
          `Attached ${args.filename} (${att.kind}, ${att.byte_size} bytes) to entry ${args.entry_id}. Handle: ${att.handle}`
        );
      })
  );

  server.tool(
    'list_attachments',
    'List attachments on a knowledge entry.',
    { entry_id: z.string() },
    async (args) =>
      guarded(async () => {
        const list = await api<{
          filename: string; kind: string; role: string | null;
          byte_size: number; handle: string; description: string | null;
        }[]>(`/api/entries/${args.entry_id}/attachments`);
        if (!list.length) return text('No attachments.');
        return text(
          list
            .map((a) => {
              const role = a.role ? ` role=${a.role}` : '';
              const desc = a.description ? ` — ${a.description}` : '';
              return `- ${a.filename} [${a.kind}]${role} (${a.byte_size} bytes, handle: ${a.handle})${desc}`;
            })
            .join('\n')
        );
      })
  );

  server.tool(
    'get_attachment',
    'Read an attachment by ID or magpie:<id> handle — inline text for small SQL/text files, download URL otherwise.',
    { id: z.string() },
    async (args) =>
      guarded(async () => {
        const attId = args.id.replace(/^magpie:/, '');
        const att = await api<{
          filename: string; kind: string; byte_size: number; handle: string;
          media_type: string; content_text: string | null;
          download_url: string; public_url: string | null;
        }>(`/api/attachments/${attId}`);
        const lines = [
          `# ${att.filename} (${att.kind}, ${att.byte_size} bytes)`,
          `Handle: ${att.handle} | Media type: ${att.media_type}`,
        ];
        if (att.public_url) lines.push(`Public URL: ${att.public_url}`);
        if (att.content_text !== null) lines.push(`\n\`\`\`\n${att.content_text}\n\`\`\``);
        else lines.push(`Download: ${att.download_url}`);
        return text(lines.join('\n'));
      })
  );

  const transport = new StdioServerTransport();
  await server.connect(transport);
}
