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
    // Try clearing API key and redirecting
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
  category: string;
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

export interface ApiKey {
  id: string;
  name: string;
  key_prefix: string;
  key?: string;
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

export interface Collection {
  id: string;
  org_id: string | null;
  workspace: string | null;
  project: string | null;
  slug: string;
  title: string;
  description: string | null;
  visibility: string;
  document_count?: number;
  created_at: string;
  updated_at: string;
}

export type ValueType = 'json' | 'string' | 'integer' | 'float' | 'boolean' | 'datetime';

export interface CollectionDocument {
  id: string;
  collection_id: string;
  key: string;
  value: unknown;
  value_type: ValueType;
  summary: string | null;
  created_at: string;
  updated_at: string;
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
  createEntry: (data: Partial<Entry>) =>
    request<Entry>('/api/entries', { method: 'POST', body: JSON.stringify(data) }),
  updateEntry: (id: string, data: Partial<Entry>) =>
    request<Entry>(`/api/entries/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteEntry: (id: string) =>
    request<{ ok: boolean }>(`/api/entries/${id}`, { method: 'DELETE' }),
  archiveEntry: (id: string) =>
    request<{ ok: boolean }>(`/api/entries/${id}/archive`, { method: 'POST' }),
  search: (query: string, opts?: {
    category?: string; tags?: string[]; workspace?: string; project?: string;
    limit?: number; semantic?: boolean; keyword?: boolean;
  }) =>
    request<Entry[]>('/api/search', {
      method: 'POST',
      body: JSON.stringify({ query, ...opts }),
    }),

  // Collections
  listCollections: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request<Collection[]>(`/api/collections${qs}`);
  },
  createCollection: (data: {
    slug: string; title: string; description?: string;
    workspace?: string; project?: string;
  }) =>
    request<Collection>('/api/collections', {
      method: 'POST', body: JSON.stringify(data),
    }),
  deleteCollection: (id: string) =>
    request<{ ok: boolean }>(`/api/collections/${id}`, { method: 'DELETE' }),
  listDocuments: (slug: string) =>
    request<{ collection: Collection; documents: CollectionDocument[] }>(
      `/api/collections/${slug}/documents`
    ),
  setDocument: (slug: string, key: string, data: {
    value: unknown; value_type?: ValueType; summary?: string;
  }) =>
    request<CollectionDocument>(`/api/collections/${slug}/documents/${key}`, {
      method: 'PUT', body: JSON.stringify(data),
    }),
  deleteDocument: (slug: string, key: string) =>
    request<{ ok: boolean }>(`/api/collections/${slug}/documents/${key}`, {
      method: 'DELETE',
    }),

  // Keys
  listKeys: () => request<ApiKey[]>('/api/keys'),
  createKey: (name: string, opts?: { workspace?: string; project?: string; role?: string }) =>
    request<ApiKey>('/api/keys', { method: 'POST', body: JSON.stringify({ name, ...opts }) }),
  deleteKey: (id: string) =>
    request<{ ok: boolean }>(`/api/keys/${id}`, { method: 'DELETE' }),

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
};
