/** Thin REST client for the Magpie API. */

import { resolveApiUrl, resolveOrg, resolveToken } from './config.js';

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  formData?: FormData;
  headers?: Record<string, string>;
  /** Skip the configured bearer token (login flow). */
  noAuth?: boolean;
}

export async function api<T = unknown>(path: string, opts: RequestOptions = {}): Promise<T> {
  const url = `${resolveApiUrl()}${path}`;
  const headers: Record<string, string> = { ...opts.headers };

  if (!opts.noAuth) {
    const token = resolveToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
    // Active org override (no-op server-side for org-pinned tokens). Let an
    // explicit per-call header win.
    const org = resolveOrg();
    if (org && !headers['X-Organization-ID']) headers['X-Organization-ID'] = org;
  }

  let body: BodyInit | undefined;
  if (opts.formData) {
    body = opts.formData;
  } else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(opts.body);
  }

  const res = await fetch(url, { method: opts.method || 'GET', headers, body });
  const text = await res.text();
  if (!res.ok) {
    let message = text;
    try {
      message = JSON.parse(text).error || text;
    } catch {
      /* raw text */
    }
    throw new ApiError(res.status, message);
  }
  return text ? JSON.parse(text) : (undefined as T);
}

export function requireToken(): void {
  if (!resolveToken()) {
    console.error(
      'Not authenticated. Run `magpie login`, or set MAGPIE_TOKEN to an access token.'
    );
    process.exit(1);
  }
}

export function qs(params: Record<string, string | undefined>): string {
  const filtered = Object.entries(params).filter(([, v]) => v !== undefined) as [string, string][];
  if (filtered.length === 0) return '';
  return '?' + new URLSearchParams(filtered).toString();
}
