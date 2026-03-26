import { useState } from 'react';
import { api, Entry } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { EntryCard } from '@/components/EntryCard';
import { Search, Sparkles, Type, Layers } from 'lucide-react';

type SearchMode = 'both' | 'semantic' | 'keyword';

export function SearchPage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Entry[]>([]);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);
  const [mode, setMode] = useState<SearchMode>('both');

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    try {
      setResults(await api.search(query, {
        semantic: mode !== 'keyword',
        keyword: mode !== 'semantic',
      }));
      setSearched(true);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  const modes: { value: SearchMode; label: string; icon: typeof Layers }[] = [
    { value: 'both', label: 'Both', icon: Layers },
    { value: 'semantic', label: 'Semantic', icon: Sparkles },
    { value: 'keyword', label: 'Keyword', icon: Type },
  ];

  return (
    <div>
      <h1 className="text-xl font-semibold mb-5">Search</h1>

      <form onSubmit={handleSearch} className="mb-6">
        <div className="flex gap-2 mb-3">
          <div className="relative flex-1">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Search knowledge..."
              autoFocus
              className="pl-9"
            />
          </div>
          <Button type="submit" disabled={loading}>
            {loading ? 'Searching...' : 'Search'}
          </Button>
        </div>
        <div className="flex gap-1.5">
          {modes.map(({ value, label, icon: Icon }) => (
            <Button
              key={value}
              type="button"
              variant={mode === value ? 'default' : 'outline'}
              size="sm"
              className="text-xs gap-1.5"
              onClick={() => setMode(value)}
            >
              <Icon size={12} /> {label}
            </Button>
          ))}
          <span className="text-xs text-muted-foreground self-center ml-2">
            {mode === 'both' && 'Semantic similarity + keyword matching, fused'}
            {mode === 'semantic' && 'Vector similarity only — finds related concepts'}
            {mode === 'keyword' && 'Full-text search — exact term matching'}
          </span>
        </div>
      </form>

      {searched && results.length === 0 && (
        <p className="text-muted-foreground text-sm text-center py-8">
          No results found.
        </p>
      )}

      {results.length > 0 && (
        <>
          <p className="text-xs text-muted-foreground mb-3">
            {results.length} result{results.length !== 1 ? 's' : ''} via {mode === 'both' ? 'semantic + keyword fusion' : mode}
          </p>
          <div className="flex flex-col rounded-lg border border-border overflow-hidden">
            {results.map(entry => (
              <EntryCard key={entry.id} entry={entry} showScore />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
