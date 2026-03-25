import { useState } from 'react';
import { api, Entry } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { EntryCard } from '@/components/EntryCard';
import { Search } from 'lucide-react';

export function SearchPage() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Entry[]>([]);
  const [searched, setSearched] = useState(false);
  const [loading, setLoading] = useState(false);

  const handleSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    setLoading(true);
    try {
      setResults(await api.search(query));
      setSearched(true);
    } catch (e) {
      console.error(e);
    }
    setLoading(false);
  };

  return (
    <div>
      <h1 className="text-xl font-semibold mb-5">Search</h1>

      <form onSubmit={handleSearch} className="flex gap-2 mb-6">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search knowledge entries..."
            autoFocus
            className="pl-9"
          />
        </div>
        <Button type="submit" disabled={loading}>
          {loading ? 'Searching...' : 'Search'}
        </Button>
      </form>

      {searched && results.length === 0 && (
        <p className="text-muted-foreground text-sm text-center py-8">No results found.</p>
      )}

      {results.length > 0 && (
        <div className="flex flex-col rounded-lg border border-border overflow-hidden">
          {results.map(entry => (
            <EntryCard key={entry.id} entry={entry} showScore />
          ))}
        </div>
      )}
    </div>
  );
}
