import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api, Entry } from '../lib/api';

export function EntryPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [entry, setEntry] = useState<Entry | null>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ title: '', content: '', category: '', tags: '' });
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!id) return;
    api.getEntry(id).then(e => {
      setEntry(e);
      setForm({
        title: e.title,
        content: e.content,
        category: e.category,
        tags: e.tags.join(', '),
      });
    });
  }, [id]);

  const handleSave = async () => {
    if (!id) return;
    setSaving(true);
    try {
      const updated = await api.updateEntry(id, {
        title: form.title,
        content: form.content,
        category: form.category,
        tags: form.tags.split(',').map(t => t.trim()).filter(Boolean),
      });
      setEntry(updated);
      setEditing(false);
    } catch (e) {
      console.error(e);
    }
    setSaving(false);
  };

  const handleDelete = async () => {
    if (!id || !confirm('Delete this entry?')) return;
    await api.deleteEntry(id);
    navigate('/');
  };

  if (!entry) return <p style={{ color: 'var(--text-muted)' }}>Loading...</p>;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 20 }}>
        <button className="btn-ghost" onClick={() => navigate('/')}>Back</button>
        <div style={{ display: 'flex', gap: 8 }}>
          {editing ? (
            <>
              <button className="btn-ghost" onClick={() => setEditing(false)}>Cancel</button>
              <button className="btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? 'Saving...' : 'Save'}
              </button>
            </>
          ) : (
            <>
              <button className="btn-ghost" onClick={() => setEditing(true)}>Edit</button>
              <button className="btn-danger" onClick={handleDelete}>Delete</button>
            </>
          )}
        </div>
      </div>

      {editing ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} placeholder="Title" />
          <select value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}>
            <option value="project">Project</option>
            <option value="area">Area</option>
            <option value="resource">Resource</option>
            <option value="archive">Archive</option>
          </select>
          <input value={form.tags} onChange={e => setForm({ ...form, tags: e.target.value })} placeholder="Tags (comma separated)" />
          <textarea
            value={form.content}
            onChange={e => setForm({ ...form, content: e.target.value })}
            rows={16}
            style={{ fontFamily: 'monospace', fontSize: 13, lineHeight: 1.6 }}
          />
        </div>
      ) : (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
            <h1 style={{ fontSize: 22, fontWeight: 600 }}>{entry.title}</h1>
            <span className={`tag category-${entry.category}`}>{entry.category}</span>
          </div>
          {entry.tags.length > 0 && (
            <div style={{ display: 'flex', gap: 4, marginBottom: 16 }}>
              {entry.tags.map(t => <span key={t} className="tag">{t}</span>)}
            </div>
          )}
          <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
            ID: {entry.id} | Source: {entry.source || 'manual'} | Updated: {new Date(entry.updated_at).toLocaleString()}
          </div>
          <div style={{
            whiteSpace: 'pre-wrap',
            lineHeight: 1.6,
            fontSize: 14,
            background: 'var(--bg-surface)',
            padding: 16,
            borderRadius: 8,
            border: '1px solid var(--border)',
          }}>
            {entry.content}
          </div>
        </div>
      )}
    </div>
  );
}
