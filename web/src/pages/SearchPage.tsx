import { useState } from 'react';
import { Link } from 'react-router-dom';
import { api, Entry } from '../lib/api';

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
      <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20 }}>Search</h1>

      <form onSubmit={handleSearch} style={{ display: 'flex', gap: 8, marginBottom: 24 }}>
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search knowledge entries..."
          autoFocus
          style={{ flex: 1 }}
        />
        <button type="submit" className="btn-primary" disabled={loading}>
          {loading ? 'Searching...' : 'Search'}
        </button>
      </form>

      {searched && results.length === 0 && (
        <p style={{ color: 'var(--text-muted)' }}>No results found.</p>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        {results.map(entry => (
          <div
            key={entry.id}
            style={{
              padding: 16,
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: 8,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <Link to={`/entries/${entry.id}`} style={{ fontWeight: 500, fontSize: 15 }}>
                {entry.title}
              </Link>
              <span className={`tag category-${entry.category}`}>{entry.category}</span>
              {entry.score != null && (
                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  score: {entry.score.toFixed(4)}
                </span>
              )}
            </div>
            <p style={{ color: 'var(--text-muted)', fontSize: 13, lineHeight: 1.5 }}>
              {entry.content.slice(0, 200)}{entry.content.length > 200 ? '...' : ''}
            </p>
            {entry.tags.length > 0 && (
              <div style={{ display: 'flex', gap: 4, marginTop: 8 }}>
                {entry.tags.map(t => <span key={t} className="tag">{t}</span>)}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
