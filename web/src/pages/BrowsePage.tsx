import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, Entry, Workspace } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { EntryCard } from '@/components/EntryCard';
import { Plus, Archive } from 'lucide-react';

export function BrowsePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [workspace, setWorkspace] = useState<string>(searchParams.get('workspace') || 'all');
  const [project, setProject] = useState<string>(searchParams.get('project') || '');
  const [showArchived, setShowArchived] = useState(false);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.listOrgs().then(orgs => {
      if (orgs.length > 0) {
        api.listWorkspaces(orgs[0].id).then(setWorkspaces);
      }
    }).catch(() => {});
  }, []);

  const load = async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (workspace !== 'all') params.workspace = workspace;
      if (project.trim()) params.project = project.trim();
      params.archived = showArchived ? 'true' : 'false';
      const rows = await api.listEntries(params);
      setEntries(rows);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  useEffect(() => {
    // Keep the URL in sync so scoped links are shareable/refresh-safe.
    const next: Record<string, string> = {};
    if (workspace !== 'all') next.workspace = workspace;
    if (project.trim()) next.project = project.trim();
    setSearchParams(next, { replace: true });
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace, project, showArchived]);

  const handleArchive = async (id: string) => {
    await api.archiveEntry(id);
    load();
  };

  const handleUnarchive = async (id: string) => {
    await api.unarchiveEntry(id);
    load();
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Delete this entry?')) return;
    await api.deleteEntry(id);
    load();
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <h1 className="text-xl font-semibold">{showArchived ? 'Archived notes' : 'Notes'}</h1>
        <Link to="/new">
          <Button size="sm"><Plus size={14} className="mr-1.5" /> New</Button>
        </Link>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-5">
        {workspaces.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            <Button
              variant={workspace === 'all' ? 'default' : 'outline'}
              size="sm"
              className="text-xs"
              onClick={() => setWorkspace('all')}
            >
              all workspaces
            </Button>
            {workspaces.map(ws => (
              <Button
                key={ws.id}
                variant={workspace === ws.slug ? 'default' : 'outline'}
                size="sm"
                className="text-xs"
                onClick={() => setWorkspace(ws.slug)}
              >
                {ws.name}
              </Button>
            ))}
          </div>
        )}
        <Input
          value={project}
          onChange={e => setProject(e.target.value)}
          placeholder="Filter by project"
          className="h-8 w-44 text-xs"
        />
        <Button
          variant={showArchived ? 'default' : 'outline'}
          size="sm"
          className="text-xs ml-auto"
          onClick={() => setShowArchived(v => !v)}
        >
          <Archive size={13} className="mr-1.5" /> Archived
        </Button>
      </div>

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading...</p>
      ) : entries.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-muted-foreground text-sm mb-3">
            {showArchived ? 'No archived notes.' : 'No notes found.'}
          </p>
          {!showArchived && (
            <Link to="/new">
              <Button variant="outline" size="sm">
                Create your first note
              </Button>
            </Link>
          )}
        </div>
      ) : (
        <div className="flex flex-col rounded-lg border border-border overflow-hidden">
          {entries.map(entry => (
            <EntryCard
              key={entry.id}
              entry={entry}
              onArchive={showArchived ? undefined : handleArchive}
              onUnarchive={showArchived ? handleUnarchive : undefined}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}
