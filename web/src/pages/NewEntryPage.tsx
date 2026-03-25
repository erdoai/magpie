import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

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
      <h1 className="text-xl font-semibold mb-5">New Entry</h1>
      <form onSubmit={handleSubmit} className="flex flex-col gap-3 max-w-2xl">
        <Input
          value={form.title}
          onChange={e => setForm({ ...form, title: e.target.value })}
          placeholder="Title"
          required
          autoFocus
        />
        <Select value={form.category} onValueChange={(v) => v && setForm({ ...form, category: v })}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="project">Project</SelectItem>
            <SelectItem value="area">Area</SelectItem>
            <SelectItem value="resource">Resource</SelectItem>
          </SelectContent>
        </Select>
        <Input
          value={form.tags}
          onChange={e => setForm({ ...form, tags: e.target.value })}
          placeholder="Tags (comma separated)"
        />
        <Input
          value={form.source}
          onChange={e => setForm({ ...form, source: e.target.value })}
          placeholder="Source (optional — e.g. crow, devbot, manual)"
        />
        <Textarea
          value={form.content}
          onChange={e => setForm({ ...form, content: e.target.value })}
          placeholder="Content (markdown supported)"
          rows={16}
          required
          className="font-mono text-sm"
        />
        <div className="flex gap-2">
          <Button type="button" variant="outline" onClick={() => navigate('/')}>Cancel</Button>
          <Button type="submit" disabled={saving}>
            {saving ? 'Creating...' : 'Create Entry'}
          </Button>
        </div>
      </form>
    </div>
  );
}
