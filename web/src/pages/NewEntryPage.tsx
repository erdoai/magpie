import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../lib/api';

export function NewEntryPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState({
    title: '',
    content: '',
    category: 'resource',
    tags: '',
    source: '',
  });
  const [saving, setSaving] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.title.trim() || !form.content.trim()) return;
    setSaving(true);
    try {
      const entry = await api.createEntry({
        title: form.title,
        content: form.content,
        category: form.category,
        tags: form.tags.split(',').map(t => t.trim()).filter(Boolean),
        source: form.source || null,
      });
      navigate(`/entries/${entry.id}`);
    } catch (e) {
      console.error(e);
    }
    setSaving(false);
  };

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20 }}>New Entry</h1>
      <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 640 }}>
        <input
          value={form.title}
          onChange={e => setForm({ ...form, title: e.target.value })}
          placeholder="Title"
          required
          autoFocus
        />
        <select value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}>
          <option value="project">Project</option>
          <option value="area">Area</option>
          <option value="resource">Resource</option>
        </select>
        <input
          value={form.tags}
          onChange={e => setForm({ ...form, tags: e.target.value })}
          placeholder="Tags (comma separated)"
        />
        <input
          value={form.source}
          onChange={e => setForm({ ...form, source: e.target.value })}
          placeholder="Source (optional — e.g. crow, devbot, manual)"
        />
        <textarea
          value={form.content}
          onChange={e => setForm({ ...form, content: e.target.value })}
          placeholder="Content (markdown supported)"
          rows={16}
          required
          style={{ fontFamily: 'monospace', fontSize: 13, lineHeight: 1.6 }}
        />
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" className="btn-ghost" onClick={() => navigate('/')}>Cancel</button>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? 'Creating...' : 'Create Entry'}
          </button>
        </div>
      </form>
    </div>
  );
}
