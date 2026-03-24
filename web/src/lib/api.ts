const BASE = '';

function headers(): HeadersInit {
  const h: HeadersInit = { 'Content-Type': 'application/json' };
  const key = localStorage.getItem('magpie_api_key');
  if (key) h['Authorization'] = `Bearer ${key}`;
  return h;
}

async function request<T>(path: string, opts?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, { ...opts, headers: headers() });
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
  project_id: string | null;
  org_id: string | null;
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
  created_at: string;
  last_used_at: string | null;
}

export const api = {
  // Entries
  listEntries: (params?: Record<string, string>) => {
    const qs = params ? '?' + new URLSearchParams(params).toString() : '';
    return request<Entry[]>(`/api/entries${qs}`);
  },
  getEntry: (id: string) => request<Entry>(`/api/entries/${id}`),
  createEntry: (data: Partial<Entry>) =>
    request<Entry>('/api/entries', { method: 'POST', body: JSON.stringify(data) }),
  updateEntry: (id: string, data: Partial<Entry>) =>
    request<Entry>(`/api/entries/${id}`, { method: 'PUT', body: JSON.stringify(data) }),
  deleteEntry: (id: string) =>
    request<{ ok: boolean }>(`/api/entries/${id}`, { method: 'DELETE' }),
  archiveEntry: (id: string) =>
    request<{ ok: boolean }>(`/api/entries/${id}/archive`, { method: 'POST' }),
  search: (query: string, opts?: { category?: string; tags?: string[]; limit?: number }) =>
    request<Entry[]>('/api/search', {
      method: 'POST',
      body: JSON.stringify({ query, ...opts }),
    }),

  // Keys
  listKeys: () => request<ApiKey[]>('/api/keys'),
  createKey: (name: string) =>
    request<ApiKey>('/api/keys', { method: 'POST', body: JSON.stringify({ name }) }),
  deleteKey: (id: string) =>
    request<{ ok: boolean }>(`/api/keys/${id}`, { method: 'DELETE' }),
};
