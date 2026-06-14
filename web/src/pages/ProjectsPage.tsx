import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, Workspace, Project } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { FolderGit2, Plus, Trash2 } from 'lucide-react';

export function ProjectsPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [projects, setProjects] = useState<Record<string, Project[]>>({});
  const [adding, setAdding] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [error, setError] = useState<string | null>(null);

  const loadProjects = async (ws: Workspace[]) => {
    const entries = await Promise.all(
      ws.map(async w => [w.id, await api.listProjects(w.id).catch(() => [])] as const)
    );
    setProjects(Object.fromEntries(entries));
  };

  const load = async () => {
    const orgs = await api.listOrgs().catch(() => []);
    if (orgs.length === 0) { setWorkspaces([]); return; }
    const ws = await api.listWorkspaces(orgs[0].id).catch(() => []);
    setWorkspaces(ws);
    await loadProjects(ws);
  };

  useEffect(() => { load(); }, []);

  const handleCreate = async (wsId: string) => {
    if (!name.trim()) return;
    setError(null);
    try {
      await api.createProject(wsId, name.trim());
      setName('');
      setAdding(null);
      const ws = workspaces.find(w => w.id === wsId);
      if (ws) await loadProjects([ws, ...workspaces.filter(w => w.id !== wsId)]);
    } catch (err) {
      setError(String(err));
    }
  };

  const handleDelete = async (projId: string, wsId: string) => {
    if (!confirm('Delete this project?')) return;
    await api.deleteProject(projId);
    const ws = workspaces.find(w => w.id === wsId);
    if (ws) {
      const list = await api.listProjects(wsId).catch(() => []);
      setProjects(p => ({ ...p, [wsId]: list }));
    }
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-xl font-semibold">Projects</h1>
      </div>
      <p className="text-sm text-muted-foreground mb-5">
        Projects are work areas inside a workspace. Notes and KV stores can be scoped to one.
      </p>

      {error && <p className="text-sm text-destructive mb-3">{error}</p>}

      {workspaces.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          No workspaces yet. Create one in <Link to="/settings" className="underline">Settings</Link> first.
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          {workspaces.map(ws => {
            const list = projects[ws.id] || [];
            return (
              <Card key={ws.id}>
                <CardContent className="pt-4">
                  <div className="flex items-center justify-between mb-3">
                    <h2 className="font-medium text-sm">{ws.name}</h2>
                    <Button
                      variant="outline" size="sm" className="h-7 text-xs"
                      onClick={() => { setAdding(adding === ws.id ? null : ws.id); setName(''); }}
                    >
                      <Plus size={13} className="mr-1" /> Project
                    </Button>
                  </div>

                  {adding === ws.id && (
                    <div className="flex gap-2 mb-3">
                      <Input
                        value={name}
                        onChange={e => setName(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && handleCreate(ws.id)}
                        placeholder="Project name (e.g. alertee)"
                        className="h-8 text-xs max-w-xs" autoFocus
                      />
                      <Button size="sm" className="h-8" onClick={() => handleCreate(ws.id)}>Add</Button>
                    </div>
                  )}

                  {list.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No projects.</p>
                  ) : (
                    <div className="flex flex-col rounded-lg border border-border overflow-hidden">
                      {list.map(p => (
                        <div key={p.id} className="flex items-center justify-between px-3 py-2 bg-card border-b border-border last:border-b-0">
                          <div className="flex items-center gap-2 min-w-0">
                            <FolderGit2 size={14} className="text-muted-foreground shrink-0" />
                            <Link
                              to={`/browse?workspace=${ws.slug}&project=${p.slug}`}
                              className="text-sm hover:underline truncate"
                            >
                              {p.name}
                            </Link>
                            <span className="font-mono text-[11px] text-muted-foreground truncate">{p.slug}</span>
                          </div>
                          <Button
                            variant="ghost" size="icon"
                            className="h-7 w-7 text-destructive hover:text-destructive shrink-0"
                            onClick={() => handleDelete(p.id, ws.id)}
                          >
                            <Trash2 size={13} />
                          </Button>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
