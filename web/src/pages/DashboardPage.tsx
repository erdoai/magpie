import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, Entry } from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Search, Plus, FileText, Archive, FolderGit2 } from 'lucide-react';

interface Stats {
  total: number;
  active: number;
  archived: number;
  workspaceCount: number;
  byWorkspace: Record<string, number>;
}

export function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [recent, setRecent] = useState<Entry[]>([]);

  useEffect(() => {
    // Load all entries to compute stats
    api.listEntries({ limit: '200' }).then(entries => {
      const byWorkspace: Record<string, number> = {};
      let archived = 0;
      for (const e of entries) {
        if (e.category === 'archive') { archived++; continue; }
        const ws = e.workspace || 'unscoped';
        byWorkspace[ws] = (byWorkspace[ws] || 0) + 1;
      }
      const active = entries.length - archived;
      setStats({
        total: entries.length,
        active,
        archived,
        workspaceCount: Object.keys(byWorkspace).filter(w => w !== 'unscoped').length,
        byWorkspace,
      });
      setRecent(entries.filter(e => e.category !== 'archive').slice(0, 5));
    }).catch(() => {});
  }, []);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold">Dashboard</h1>
        <div className="flex gap-2">
          <Link to="/search"><Button variant="outline" size="sm"><Search size={14} className="mr-1.5" /> Search</Button></Link>
          <Link to="/new"><Button size="sm"><Plus size={14} className="mr-1.5" /> New</Button></Link>
        </div>
      </div>

      {stats && (
        <>
          {/* Stats cards */}
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-6">
            <Card>
              <CardContent className="pt-4 pb-3">
                <div className="flex items-center gap-2">
                  <FileText size={14} className="text-muted-foreground" />
                  <p className="text-2xl font-bold">{stats.active}</p>
                </div>
                <p className="text-xs text-muted-foreground">notes</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4 pb-3">
                <div className="flex items-center gap-2">
                  <FolderGit2 size={14} className="text-muted-foreground" />
                  <p className="text-2xl font-bold">{stats.workspaceCount}</p>
                </div>
                <p className="text-xs text-muted-foreground">workspaces</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="pt-4 pb-3">
                <div className="flex items-center gap-2">
                  <Archive size={14} className="text-muted-foreground" />
                  <p className="text-2xl font-bold">{stats.archived}</p>
                </div>
                <p className="text-xs text-muted-foreground">archived</p>
              </CardContent>
            </Card>
          </div>

          {/* Workspaces breakdown */}
          {Object.keys(stats.byWorkspace).length > 0 && (
            <Card className="mb-6">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm">By workspace</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(stats.byWorkspace)
                    .sort((a, b) => b[1] - a[1])
                    .map(([ws, count]) => (
                      <Link key={ws} to={ws === 'unscoped' ? '/browse' : `/browse?workspace=${ws}`}>
                        <Badge variant="outline" className="gap-1.5 cursor-pointer hover:bg-accent">
                          {ws} <span className="text-muted-foreground">{count}</span>
                        </Badge>
                      </Link>
                    ))}
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* Recent entries */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Recent entries</CardTitle>
        </CardHeader>
        <CardContent>
          {recent.length === 0 ? (
            <p className="text-sm text-muted-foreground py-2">No entries yet.</p>
          ) : (
            <div className="flex flex-col gap-1">
              {recent.map(entry => (
                <Link
                  key={entry.id}
                  to={`/entries/${entry.id}`}
                  className="flex items-center justify-between py-1.5 px-2 rounded hover:bg-accent/50 no-underline"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-sm truncate">{entry.title}</span>
                    {entry.workspace && (
                      <Badge variant="secondary" className="text-[10px] shrink-0">{entry.workspace}</Badge>
                    )}
                  </div>
                  <span className="text-xs text-muted-foreground">
                    {new Date(entry.updated_at).toLocaleDateString()}
                  </span>
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
