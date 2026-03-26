import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, Entry } from '@/lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Search, Plus, FolderOpen, Archive, Layers, BookOpen } from 'lucide-react';

interface Stats {
  total: number;
  byCategory: Record<string, number>;
  byWorkspace: Record<string, number>;
}

export function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [recent, setRecent] = useState<Entry[]>([]);

  useEffect(() => {
    // Load all entries to compute stats
    api.listEntries({ limit: '200' }).then(entries => {
      const byCategory: Record<string, number> = {};
      const byWorkspace: Record<string, number> = {};
      for (const e of entries) {
        byCategory[e.category] = (byCategory[e.category] || 0) + 1;
        const ws = e.workspace || 'unscoped';
        byWorkspace[ws] = (byWorkspace[ws] || 0) + 1;
      }
      setStats({ total: entries.length, byCategory, byWorkspace });
      setRecent(entries.slice(0, 5));
    }).catch(() => {});
  }, []);

  const categoryIcons: Record<string, typeof Layers> = {
    project: Layers,
    area: FolderOpen,
    resource: BookOpen,
    archive: Archive,
  };

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
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
            <Card>
              <CardContent className="pt-4 pb-3">
                <p className="text-2xl font-bold">{stats.total}</p>
                <p className="text-xs text-muted-foreground">total entries</p>
              </CardContent>
            </Card>
            {['project', 'area', 'resource', 'archive'].map(cat => {
              const Icon = categoryIcons[cat] || Layers;
              return (
                <Card key={cat}>
                  <CardContent className="pt-4 pb-3">
                    <div className="flex items-center gap-2">
                      <Icon size={14} className="text-muted-foreground" />
                      <p className="text-2xl font-bold">{stats.byCategory[cat] || 0}</p>
                    </div>
                    <p className="text-xs text-muted-foreground">{cat}s</p>
                  </CardContent>
                </Card>
              );
            })}
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
                      <Link key={ws} to={`/?workspace=${ws}`}>
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
                  <div className="flex items-center gap-2">
                    <span className="text-sm">{entry.title}</span>
                    <Badge variant="outline" className="text-[10px]">{entry.category}</Badge>
                    {entry.workspace && (
                      <Badge variant="secondary" className="text-[10px]">{entry.workspace}</Badge>
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
