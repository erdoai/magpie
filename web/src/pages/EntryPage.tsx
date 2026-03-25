import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { api, Entry } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ArrowLeft, Pencil, Trash2 } from 'lucide-react';

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

  if (!entry) return <p className="text-muted-foreground text-sm">Loading...</p>;

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <Button variant="ghost" size="sm" onClick={() => navigate('/')}>
          <ArrowLeft size={14} className="mr-1.5" /> Back
        </Button>
        <div className="flex gap-2">
          {editing ? (
            <>
              <Button variant="outline" size="sm" onClick={() => setEditing(false)}>Cancel</Button>
              <Button size="sm" onClick={handleSave} disabled={saving}>
                {saving ? 'Saving...' : 'Save'}
              </Button>
            </>
          ) : (
            <>
              <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                <Pencil size={14} className="mr-1.5" /> Edit
              </Button>
              <Button variant="outline" size="sm" className="text-destructive hover:text-destructive" onClick={handleDelete}>
                <Trash2 size={14} className="mr-1.5" /> Delete
              </Button>
            </>
          )}
        </div>
      </div>

      {editing ? (
        <div className="flex flex-col gap-3 max-w-2xl">
          <Input value={form.title} onChange={e => setForm({ ...form, title: e.target.value })} placeholder="Title" />
          <Select value={form.category} onValueChange={(v) => v && setForm({ ...form, category: v })}>
            <SelectTrigger><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="project">Project</SelectItem>
              <SelectItem value="area">Area</SelectItem>
              <SelectItem value="resource">Resource</SelectItem>
              <SelectItem value="archive">Archive</SelectItem>
            </SelectContent>
          </Select>
          <Input value={form.tags} onChange={e => setForm({ ...form, tags: e.target.value })} placeholder="Tags (comma separated)" />
          <Textarea
            value={form.content}
            onChange={e => setForm({ ...form, content: e.target.value })}
            rows={16}
            className="font-mono text-sm"
          />
        </div>
      ) : (
        <div>
          <div className="flex items-center gap-2.5 mb-3">
            <h1 className="text-xl font-semibold">{entry.title}</h1>
            <Badge variant="outline">{entry.category}</Badge>
          </div>
          {entry.tags.length > 0 && (
            <div className="flex gap-1 mb-4">
              {entry.tags.map(t => <Badge key={t} variant="secondary">{t}</Badge>)}
            </div>
          )}
          <p className="text-xs text-muted-foreground mb-4">
            ID: {entry.id} &middot; Source: {entry.source || 'manual'} &middot; Updated: {new Date(entry.updated_at).toLocaleString()}
          </p>
          <Card>
            <CardContent className="pt-5">
              <div className="whitespace-pre-wrap text-sm leading-relaxed">
                {entry.content}
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
