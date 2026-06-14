const BASE = '';

function headers(): HeadersInit {
  const h: HeadersInit = { 'Content-Type': 'application/json' };
  const key = localStorage.getItem('magpie_api_key');
  if (key) h['Authorization'] = `Bearer ${key}`;
  return h;
}

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...opts,
    headers: { ...headers(), ...opts?.headers },
    credentials: 'include',
  });
  if (res.status === 401 && !path.includes('/auth/')) {
    // Try clearing token and redirecting
    localStorage.removeItem('magpie_api_key');
    window.location.reload();
    throw new Error('Unauthorized');
  }
  if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
  return res.json();
}

export interface Entry {
  id: string;
  title: string;
  content: string;
  archived_at: string | null;
  tags: string[];
  source: string | null;
  user_id: string | null;
  org_id: string | null;
  workspace: string | null;
  project: string | null;
  score?: number;
  created_at: string;
  updated_at: string;
}

export interface Token {
  id: string;
  name: string;
  token_prefix: string;
  token?: string;
  user_id: string | null;
  org_id: string | null;
  workspace: string | null;
  project: string | null;
  role: string;
  created_at: string;
  last_used_at: string | null;
}

export interface OutgoingLink {
  id: string;
  target_type: 'entry' | 'url' | 'resource' | 'unresolved';
  target_id: string | null;
  target_ref: string | null;
  link_text: string;
  normalized_target: string;
  target_title: string | null;
  target_workspace: string | null;
  target_project: string | null;
}

export interface Backlink {
  id: string;
  source_id: string;
  source_title: string;
  source_workspace: string | null;
  source_project: string | null;
  link_text: string;
}

export interface EntryLinks {
  outgoing: OutgoingLink[];
  backlinks: Backlink[];
}

export interface EntryRevision {
  id: string;
  previous_title: string;
  previous_content: string;
  previous_tags: string[];
  previous_source: string | null;
  actor_type: string | null;
  actor_user_id: string | null;
  created_at: string;
}

export interface KvStore {
  id: string;
  org_id: string | null;
  workspace: string | null;
  project: string | null;
  slug: string;
  title: string;
  description: string | null;
  visibility: string;
  key_count?: number;
  created_at: string;
  updated_at: string;
}

export type ValueType = 'json' | 'string' | 'integer' | 'float' | 'boolean' | 'datetime';

export interface KvPair {
  id: string;
  store_id: string;
  key: string;
  value: unknown;
  value_type: ValueType;
  summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface Attachment {
  id: string;
  entry_id: string;
  handle: string;
  kind: 'image' | 'sql' | 'text' | 'pdf' | 'file';
  filename: string;
  media_type: string;
  byte_size: number;
  description: string | null;
  role: string | null;
  public: boolean;
  download_url: string;
  public_url: string | null;
  content_text: string | null;
  created_at: string;
}

export interface User {
  id: string;
  email: string;
  display_name: string | null;
}

export interface Org {
  id: string;
  name: string;
  slug: string;
  role: string;
  created_at: string;
}

export interface Workspace {
  id: string;
  org_id: string;
  name: string;
  slug: string;
  created_at: string;
}

export interface Project {
  id: string;
  workspace_id: string;
  name: string;
  slug: string;
  created_at?: string;
}

export interface Update {
  kind: 'entry' | 'kv' | 'attachment' | 'bundle';
  // Verb from the namespaced action — created/updated/archived/unarchived/
  // deleted/merged/bulk_updated/set/added/pushed.
  action: string;
  title: string | null;
  entry_id: string | null;
  store: string | null;
  key: string | null;
  value_type: string | null;
  workspace: string | null;
  project: string | null;
  at: string;
  // Richer event shape (from the activity log).
  id: string;
  subject_type: string;
  subject_id: string | null;
  subject_title: string | null;
  actor_user_id: string | null;
  actor_type: string | null;
  metadata: Record<string, unknown>;
}

export const api = {
  // Auth
  sendCode: (email: string) =>
    request<{ ok: boolean }>('/api/auth/send-code', {
      method: 'POST', body: JSON.stringify({ email }),
    }),
  verifyCode: (email: string, code: string) =>
    request<{ user: User; orgs: Org[] }>('/api/auth/verify-code', {
      method: 'POST', body: JSON.stringify({ email, code }),
    }),
  getMe: () => request<{ user: User | null; orgs: Org[] }>('/api/auth/me'),
  logout: () => request<{ ok: boolean }>('/api/auth/logout', { method: 'POST' }),
  updateProfile: (display_name: string) =>
    request<{ ok: boolean }>('/api/auth/profile', {
      method: 'PUT', body: JSON.stringify({ display_name }),
    }),
  checkAuth: async (): Promise<boolean> => {
    try {
      const res = await fetch('/api/auth/check', {
        headers: headers(),
        credentials: 'include',
      });
      return res.ok;
    } catch {
      return false;
    }
  },

  // Entries
  listEntries: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request<Entry[]>(`/api/entries${qs}`);
  },
  getEntry: (id: string) => request<Entry>(`/api/entries/${id}`),
  getEntryLinks: (id: string) => request<EntryLinks>(`/api/entries/${id}/links`),
  getEntryHistory: (id: string) => request<EntryRevision[]>(`/api/entries/${id}/history`),
  createEntry: (data: Partial<Entry>) =>
    request<Entry>('/api/entries', { method: 'POST', body: JSON.stringify(data) }),
  updateEntry: (id: string, data: Partial<Entry>) =>
    request<Entry>(`/api/entries/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteEntry: (id: string) =>
    request<{ ok: boolean }>(`/api/entries/${id}`, { method: 'DELETE' }),
  archiveEntry: (id: string) =>
    request<{ ok: boolean }>(`/api/entries/${id}/archive`, { method: 'POST' }),
  unarchiveEntry: (id: string) =>
    request<{ ok: boolean }>(`/api/entries/${id}/unarchive`, { method: 'POST' }),
  search: (query: string, opts?: {
    tags?: string[]; workspace?: string; project?: string;
    limit?: number; semantic?: boolean; keyword?: boolean;
  }) =>
    request<Entry[]>('/api/search', {
      method: 'POST',
      body: JSON.stringify({ query, ...opts }),
    }),

  // KV
  listKvStores: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request<KvStore[]>(`/api/kv${qs}`);
  },
  createKvStore: (data: {
    slug: string; title: string; description?: string;
    workspace?: string; project?: string;
  }) =>
    request<KvStore>('/api/kv', {
      method: 'POST', body: JSON.stringify(data),
    }),
  deleteKvStore: (id: string) =>
    request<{ ok: boolean }>(`/api/kv/${id}`, { method: 'DELETE' }),
  listKeys: (slug: string) =>
    request<{ store: KvStore; pairs: KvPair[] }>(
      `/api/kv/${slug}/keys`
    ),
  setKey: (slug: string, key: string, data: {
    value: unknown; value_type?: ValueType; summary?: string;
  }) =>
    request<KvPair>(`/api/kv/${slug}/keys/${key}`, {
      method: 'PUT', body: JSON.stringify(data),
    }),
  deleteKey: (slug: string, key: string) =>
    request<{ ok: boolean }>(`/api/kv/${slug}/keys/${key}`, {
      method: 'DELETE',
    }),

  // Attachments
  listAttachments: (entryId: string) =>
    request<Attachment[]>(`/api/entries/${entryId}/attachments`),
  uploadAttachment: async (entryId: string, file: File, opts?: {
    role?: string; description?: string; public?: boolean;
  }): Promise<Attachment> => {
    const form = new FormData();
    form.append('file', file);
    if (opts?.role) form.append('role', opts.role);
    if (opts?.description) form.append('description', opts.description);
    if (opts?.public) form.append('public', 'true');
    const h: HeadersInit = {};
    const key = localStorage.getItem('magpie_api_key');
    if (key) h['Authorization'] = `Bearer ${key}`;
    const res = await fetch(`/api/entries/${entryId}/attachments`, {
      method: 'POST', body: form, headers: h, credentials: 'include',
    });
    if (!res.ok) throw new Error(`${res.status}: ${await res.text()}`);
    return res.json();
  },
  deleteAttachment: (id: string) =>
    request<{ ok: boolean }>(`/api/attachments/${id}`, { method: 'DELETE' }),

  // Access tokens
  listTokens: () => request<Token[]>('/api/tokens'),
  createToken: (name: string, opts?: { workspace?: string; project?: string; role?: string }) =>
    request<Token>('/api/tokens', { method: 'POST', body: JSON.stringify({ name, ...opts }) }),
  deleteToken: (id: string) =>
    request<{ ok: boolean }>(`/api/tokens/${id}`, { method: 'DELETE' }),

  // Orgs
  listOrgs: () => request<Org[]>('/api/orgs'),
  createOrg: (name: string, slug?: string) =>
    request<Org>('/api/orgs', {
      method: 'POST', body: JSON.stringify({ name, slug }),
    }),
  listMembers: (orgId: string) =>
    request<{ id: string; email: string; display_name: string | null; role: string }[]>(
      `/api/orgs/${orgId}/members`
    ),
  inviteMember: (orgId: string, email: string) =>
    request<{ ok: boolean }>(`/api/orgs/${orgId}/members`, {
      method: 'POST', body: JSON.stringify({ email }),
    }),
  removeMember: (orgId: string, memberId: string) =>
    request<{ ok: boolean }>(`/api/orgs/${orgId}/members/${memberId}`, {
      method: 'DELETE',
    }),

  // Workspaces
  listWorkspaces: (orgId: string) =>
    request<Workspace[]>(`/api/orgs/${orgId}/workspaces`),
  createWorkspace: (orgId: string, name: string) =>
    request<Workspace>(`/api/orgs/${orgId}/workspaces`, {
      method: 'POST', body: JSON.stringify({ name }),
    }),
  deleteWorkspace: (wsId: string) =>
    request<{ ok: boolean }>(`/api/workspaces/${wsId}`, { method: 'DELETE' }),

  // Updates (activity feed)
  listUpdates: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request<Update[]>(`/api/updates${qs}`);
  },

  // Projects (managed children of workspaces)
  listProjects: (wsId: string) =>
    request<Project[]>(`/api/workspaces/${wsId}/projects`),
  createProject: (wsId: string, name: string) =>
    request<Project>(`/api/workspaces/${wsId}/projects`, {
      method: 'POST', body: JSON.stringify({ name }),
    }),
  deleteProject: (projId: string) =>
    request<{ ok: boolean }>(`/api/projects/${projId}`, { method: 'DELETE' }),
};
