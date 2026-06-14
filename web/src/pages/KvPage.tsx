import { useEffect, useState } from 'react';
import { api, KvStore, KvPair, ValueType } from '@/lib/api';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { cn } from '@/lib/utils';
import { Plus, Trash2 } from 'lucide-react';

const VALUE_TYPES: ValueType[] = ['json', 'string', 'integer', 'float', 'boolean', 'datetime'];

function formatValue(doc: KvPair): string {
  return JSON.stringify(doc.value, null, doc.value_type === 'json' ? 2 : 0);
}

export function KvPage() {
  const [collections, setCollections] = useState<KvStore[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [documents, setDocuments] = useState<KvPair[]>([]);
  const [creating, setCreating] = useState(false);
  const [newCollection, setNewCollection] = useState({ slug: '', title: '', workspace: '', project: '' });
  const [editor, setEditor] = useState<{
    key: string; value: string; valueType: ValueType; summary: string; isNew: boolean;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadCollections = () =>
    api.listKvStores().then(cols => {
      setCollections(cols);
      if (cols.length > 0 && !selected) setSelected(cols[0].slug);
    }).catch(() => {});

  useEffect(() => { loadCollections(); }, []);

  useEffect(() => {
    if (!selected) { setDocuments([]); return; }
    api.listKeys(selected).then(r => setDocuments(r.pairs)).catch(() => setDocuments([]));
  }, [selected]);

  const reloadDocuments = () => {
    if (selected) api.listKeys(selected).then(r => setDocuments(r.pairs)).catch(() => {});
    loadCollections();
  };

  const handleCreateCollection = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.createKvStore({
        slug: newCollection.slug,
        title: newCollection.title || newCollection.slug,
        workspace: newCollection.workspace || undefined,
        project: newCollection.project || undefined,
      });
      setCreating(false);
      setNewCollection({ slug: '', title: '', workspace: '', project: '' });
      await loadCollections();
      setSelected(newCollection.slug);
    } catch (err) {
      setError(String(err));
    }
  };

  const handleSaveDocument = async () => {
    if (!selected || !editor) return;
    setError(null);
    let value: unknown;
    try {
      value = JSON.parse(editor.value);
    } catch {
      // Treat bare input as a string for convenience when type is string
      if (editor.valueType === 'string') value = editor.value;
      else { setError('Value must be valid JSON'); return; }
    }
    try {
      await api.setKey(selected, editor.key, {
        value,
        value_type: editor.valueType,
        summary: editor.summary || undefined,
      });
      setEditor(null);
      reloadDocuments();
    } catch (err) {
      setError(String(err));
    }
  };

  const handleDeleteDocument = async (key: string) => {
    if (!selected || !confirm(`Delete document "${key}"?`)) return;
    await api.deleteKey(selected, key);
    reloadDocuments();
  };

  const current = collections.find(c => c.slug === selected);

  return (
    <div>
      <div className="flex items-center justify-between mb-5">
        <div>
          <h1 className="text-xl font-semibold">KV</h1>
          <p className="text-xs text-muted-foreground mt-0.5">
            Key-value stores — typed values (JSON, strings, numbers) read whole by key.
          </p>
        </div>
        <Button size="sm" onClick={() => setCreating(!creating)}>
          <Plus size={14} className="mr-1.5" /> New store
        </Button>
      </div>

      {error && <p className="text-sm text-destructive mb-3">{error}</p>}

      {creating && (
        <form onSubmit={handleCreateCollection} className="flex flex-wrap gap-2 mb-5">
          <Input
            value={newCollection.slug}
            onChange={e => setNewCollection({ ...newCollection, slug: e.target.value })}
            placeholder="slug (e.g. reach.strategy)" className="w-52" required autoFocus
          />
          <Input
            value={newCollection.title}
            onChange={e => setNewCollection({ ...newCollection, title: e.target.value })}
            placeholder="Title" className="w-44"
          />
          <Input
            value={newCollection.workspace}
            onChange={e => setNewCollection({ ...newCollection, workspace: e.target.value })}
            placeholder="Workspace" className="w-36"
          />
          <Input
            value={newCollection.project}
            onChange={e => setNewCollection({ ...newCollection, project: e.target.value })}
            placeholder="Project" className="w-36"
          />
          <Button type="submit" size="sm">Create</Button>
        </form>
      )}

      {collections.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          No KV stores yet. A store holds typed values addressed by key — handy for config,
          counters, and structured state an agent reads whole.
        </p>
      ) : (
        <div className="flex gap-5">
          <div className="w-56 shrink-0 flex flex-col gap-1">
            {collections.map(col => (
              <button
                key={col.id}
                onClick={() => setSelected(col.slug)}
                className={cn(
                  'text-left px-3 py-2 rounded-md text-sm transition-colors',
                  col.slug === selected
                    ? 'bg-accent text-primary font-medium'
                    : 'text-muted-foreground hover:bg-accent/50'
                )}
              >
                <div className="font-mono text-xs truncate">{col.slug}</div>
                <div className="text-[11px] text-muted-foreground">
                  {col.workspace ? `${col.workspace}${col.project ? '/' + col.project : ''} · ` : ''}
                  {col.key_count ?? 0} docs
                </div>
              </button>
            ))}
          </div>

          <div className="flex-1 min-w-0">
            {current && (
              <>
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h2 className="font-medium">{current.title}</h2>
                    {current.description && (
                      <p className="text-xs text-muted-foreground">{current.description}</p>
                    )}
                  </div>
                  <Button
                    variant="outline" size="sm"
                    onClick={() => setEditor({ key: '', value: '', valueType: 'json', summary: '', isNew: true })}
                  >
                    <Plus size={14} className="mr-1.5" /> Key
                  </Button>
                </div>

                {editor && (
                  <Card className="mb-4">
                    <CardContent className="pt-4 flex flex-col gap-2">
                      <div className="flex flex-wrap gap-2">
                        <Input
                          value={editor.key}
                          onChange={e => setEditor({ ...editor, key: e.target.value })}
                          placeholder="key" className="w-48 font-mono text-xs"
                          disabled={!editor.isNew}
                        />
                        <Select
                          value={editor.valueType}
                          onValueChange={v => v && setEditor({ ...editor, valueType: v as ValueType })}
                        >
                          <SelectTrigger className="w-32"><SelectValue /></SelectTrigger>
                          <SelectContent>
                            {VALUE_TYPES.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                          </SelectContent>
                        </Select>
                        <Input
                          value={editor.summary}
                          onChange={e => setEditor({ ...editor, summary: e.target.value })}
                          placeholder="Summary (optional)" className="flex-1"
                        />
                      </div>
                      <Textarea
                        value={editor.value}
                        onChange={e => setEditor({ ...editor, value: e.target.value })}
                        placeholder={editor.valueType === 'json' ? '{"key": "value"}' : 'JSON value, e.g. 42, true, "text"'}
                        rows={editor.valueType === 'json' ? 8 : 2}
                        className="font-mono text-xs"
                      />
                      <div className="flex gap-2">
                        <Button variant="outline" size="sm" onClick={() => setEditor(null)}>Cancel</Button>
                        <Button size="sm" onClick={handleSaveDocument} disabled={!editor.key.trim()}>Save</Button>
                      </div>
                    </CardContent>
                  </Card>
                )}

                {documents.length === 0 ? (
                  <p className="text-muted-foreground text-sm">Empty — no keys yet.</p>
                ) : (
                  <div className="flex flex-col rounded-lg border border-border overflow-hidden">
                    {documents.map(doc => (
                      <div key={doc.id} className="px-4 py-3 bg-card border-b border-border">
                        <div className="flex items-center justify-between gap-2">
                          <div className="flex items-center gap-2 min-w-0">
                            <span className="font-mono text-sm font-medium truncate">{doc.key}</span>
                            <Badge variant="outline" className="text-[10px] shrink-0">{doc.value_type}</Badge>
                          </div>
                          <div className="flex gap-1 shrink-0">
                            <Button
                              variant="ghost" size="sm" className="h-7 text-xs"
                              onClick={() => setEditor({
                                key: doc.key,
                                value: formatValue(doc),
                                valueType: doc.value_type,
                                summary: doc.summary || '',
                                isNew: false,
                              })}
                            >
                              Edit
                            </Button>
                            <Button
                              variant="ghost" size="icon"
                              className="h-7 w-7 text-destructive hover:text-destructive"
                              onClick={() => handleDeleteDocument(doc.key)}
                            >
                              <Trash2 size={13} />
                            </Button>
                          </div>
                        </div>
                        {doc.summary && (
                          <p className="text-xs text-muted-foreground mt-0.5">{doc.summary}</p>
                        )}
                        <pre className="text-xs font-mono text-muted-foreground mt-1.5 max-h-32 overflow-auto whitespace-pre-wrap break-all">
                          {formatValue(doc)}
                        </pre>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
