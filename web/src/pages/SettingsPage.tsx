import { useEffect, useState } from 'react';
import { api, ApiKey } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Copy, Trash2 } from 'lucide-react';

export function SettingsPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKey, setNewKey] = useState<string | null>(null);

  const loadKeys = async () => {
    try {
      setKeys(await api.listKeys());
    } catch { /* may fail if not authed */ }
  };

  useEffect(() => { loadKeys(); }, []);

  const handleCreateKey = async () => {
    if (!newKeyName.trim()) return;
    try {
      const key = await api.createKey(newKeyName);
      setNewKey(key.key!);
      setNewKeyName('');
      loadKeys();
    } catch (e) {
      console.error(e);
    }
  };

  const handleDeleteKey = async (id: string) => {
    if (!confirm('Delete this API key?')) return;
    await api.deleteKey(id);
    loadKeys();
  };

  return (
    <div className="max-w-xl">
      <h1 className="text-xl font-semibold mb-5">Settings</h1>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">API Keys</CardTitle>
          <CardDescription>Create keys for agents and integrations.</CardDescription>
        </CardHeader>
        <CardContent>
          {newKey && (
            <div className="mb-4 p-3 rounded-md border border-[oklch(0.65_0.17_145)] bg-[oklch(0.65_0.17_145)]/10">
              <p className="text-xs text-[oklch(0.65_0.17_145)] mb-1.5 font-medium">
                Copy this key now — it won't be shown again:
              </p>
              <div className="flex items-center gap-2">
                <code className="text-xs flex-1 break-all">{newKey}</code>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0"
                  onClick={() => navigator.clipboard.writeText(newKey)}
                >
                  <Copy size={14} />
                </Button>
              </div>
            </div>
          )}

          <div className="flex gap-2 mb-4">
            <Input
              value={newKeyName}
              onChange={e => setNewKeyName(e.target.value)}
              placeholder="Key name (e.g. crow-production)"
              onKeyDown={e => e.key === 'Enter' && handleCreateKey()}
            />
            <Button onClick={handleCreateKey}>Create</Button>
          </div>

          <Separator className="mb-3" />

          {keys.length === 0 ? (
            <p className="text-muted-foreground text-sm py-2">No API keys created yet.</p>
          ) : (
            <div className="flex flex-col gap-0.5">
              {keys.map(key => (
                <div key={key.id} className="flex items-center justify-between py-2 px-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">{key.name}</span>
                    <Badge variant="secondary" className="text-[10px] font-mono">
                      {key.key_prefix}...
                    </Badge>
                    {key.last_used_at && (
                      <span className="text-xs text-muted-foreground">
                        Used {new Date(key.last_used_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 text-destructive hover:text-destructive"
                    onClick={() => handleDeleteKey(key.id)}
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
