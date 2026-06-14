import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, Update } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { FileText, Database, Archive } from 'lucide-react';

const ACTION_STYLE: Record<string, string> = {
  created: 'text-[oklch(0.65_0.17_145)]',
  updated: 'text-[oklch(0.6_0.16_250)]',
  archived: 'text-muted-foreground',
};

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return 'just now';
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export function UpdatesPage() {
  const [updates, setUpdates] = useState<Update[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listUpdates({ limit: '100' })
      .then(setUpdates)
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  return (
    <div>
      <div className="mb-5">
        <h1 className="text-xl font-semibold">Updates</h1>
        <p className="text-xs text-muted-foreground mt-0.5">
          Recent activity across your notes and KV stores, newest first.
        </p>
      </div>

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading...</p>
      ) : updates.length === 0 ? (
        <p className="text-muted-foreground text-sm">Nothing yet — changes will show up here as you write.</p>
      ) : (
        <div className="flex flex-col rounded-lg border border-border overflow-hidden">
          {updates.map((u, i) => {
            const Icon = u.kind === 'entry' ? (u.action === 'archived' ? Archive : FileText) : Database;
            const scope = u.workspace
              ? (u.project ? `${u.workspace}/${u.project}` : u.workspace)
              : null;
            const to = u.kind === 'entry' && u.entry_id ? `/entries/${u.entry_id}` : '/kv';
            return (
              <div
                key={`${u.kind}-${u.entry_id || u.title}-${i}`}
                className="flex items-center gap-3 px-4 py-2.5 bg-card border-b border-border last:border-b-0 hover:bg-accent/30 transition-colors"
              >
                <Icon size={15} className="text-muted-foreground shrink-0" />
                <span className={`text-xs font-medium capitalize shrink-0 ${ACTION_STYLE[u.action] || ''}`}>
                  {u.action}
                </span>
                <Link to={to} className="text-sm hover:underline truncate min-w-0 flex-1">
                  {u.kind === 'kv' ? <span className="font-mono">{u.title}</span> : u.title}
                </Link>
                {scope && (
                  <Badge variant="secondary" className="text-[10px] shrink-0">{scope}</Badge>
                )}
                <span className="text-xs text-muted-foreground shrink-0 w-16 text-right">
                  {relativeTime(u.at)}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
