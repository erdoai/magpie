import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, Entry } from '../lib/api';
import { Archive, Trash2 } from 'lucide-react';

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
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <h1 style={{ fontSize: 20, fontWeight: 600 }}>Entries</h1>
        <Link to="/new"><button className="btn-primary">+ New Entry</button></Link>
      </div>

      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {CATEGORIES.map(c => (
          <button
            key={c}
            onClick={() => setCategory(c)}
            className={c === category ? 'btn-primary' : 'btn-ghost'}
            style={{ textTransform: 'capitalize', fontSize: 13 }}
          >
            {c}
          </button>
        ))}
      </div>

      {loading ? (
        <p style={{ color: 'var(--text-muted)' }}>Loading...</p>
      ) : entries.length === 0 ? (
        <p style={{ color: 'var(--text-muted)' }}>No entries found.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
          {entries.map(entry => (
            <div
              key={entry.id}
              style={{
                padding: '14px 16px',
                background: 'var(--bg-surface)',
                borderBottom: '1px solid var(--border)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <Link to={`/entries/${entry.id}`} style={{ fontWeight: 500, fontSize: 15 }}>
                    {entry.title}
                  </Link>
                  <span className={`tag category-${entry.category}`}>{entry.category}</span>
                </div>
                <p style={{
                  color: 'var(--text-muted)',
                  fontSize: 13,
                  maxWidth: 600,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}>
                  {entry.content.slice(0, 120)}
                </p>
                {entry.tags.length > 0 && (
                  <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
                    {entry.tags.map(t => <span key={t} className="tag">{t}</span>)}
                  </div>
                )}
              </div>
              <div style={{ display: 'flex', gap: 4, marginLeft: 12 }}>
                {entry.category !== 'archive' && (
                  <button className="btn-ghost" onClick={() => handleArchive(entry.id)} title="Archive" style={{ padding: '6px 8px' }}>
                    <Archive size={14} />
                  </button>
                )}
                <button className="btn-danger" onClick={() => handleDelete(entry.id)} title="Delete" style={{ padding: '6px 8px' }}>
                  <Trash2 size={14} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
