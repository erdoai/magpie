import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, Entry } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { EntryCard } from '@/components/EntryCard';
import { cn } from '@/lib/utils';
import { Plus } from 'lucide-react';

const CATEGORIES = ['all', 'project', 'area', 'resource', 'archive'] as const;

export function BrowsePage() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [category, setCategory] = useState<string>('all');
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = {};
      if (category !== 'all') params.category = category;
      setEntries(await api.listEntries(params));
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  useEffect(() => { load(); }, [category]);

  const handleArchive = async (id: string) => {
    await api.archiveEntry(id);
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
        <h1 className="text-xl font-semibold">Entries</h1>
        <Link to="/new">
          <Button size="sm"><Plus size={14} className="mr-1.5" /> New Entry</Button>
        </Link>
      </div>

      <div className="flex gap-1.5 mb-5">
        {CATEGORIES.map(c => (
          <Button
            key={c}
            variant={c === category ? 'default' : 'outline'}
            size="sm"
            className="capitalize text-xs"
            onClick={() => setCategory(c)}
          >
            {c}
          </Button>
        ))}
      </div>

      {loading ? (
        <p className="text-muted-foreground text-sm">Loading...</p>
      ) : entries.length === 0 ? (
        <div className="text-center py-12">
          <p className="text-muted-foreground text-sm mb-3">No entries found.</p>
          <Link to="/new">
            <Button variant="outline" size="sm">Create your first entry</Button>
          </Link>
        </div>
      ) : (
        <div className={cn("flex flex-col rounded-lg border border-border overflow-hidden")}>
          {entries.map(entry => (
            <EntryCard
              key={entry.id}
              entry={entry}
              onArchive={handleArchive}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}
    </div>
  );
}
