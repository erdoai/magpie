import { useEffect, useState } from 'react';
import { api, ApiKey } from '../lib/api';
import { Copy, Trash2 } from 'lucide-react';

export function SettingsPage() {
  const [apiKeyInput, setApiKeyInput] = useState(localStorage.getItem('magpie_api_key') || '');
  const [saved, setSaved] = useState(false);
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKey, setNewKey] = useState<string | null>(null);

  const saveApiKey = () => {
    localStorage.setItem('magpie_api_key', apiKeyInput);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const loadKeys = async () => {
    try {
      setKeys(await api.listKeys());
    } catch {
      // Keys endpoint might fail if not authed
    }
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

  const copyKey = (key: string) => {
    navigator.clipboard.writeText(key);
  };

  return (
    <div>
      <h1 style={{ fontSize: 20, fontWeight: 600, marginBottom: 20 }}>Settings</h1>

      <section style={{ marginBottom: 32 }}>
        <h2 style={{ fontSize: 16, fontWeight: 500, marginBottom: 12 }}>API Key (for this browser)</h2>
        <div style={{ display: 'flex', gap: 8, maxWidth: 480 }}>
          <input
            type="password"
            value={apiKeyInput}
            onChange={e => setApiKeyInput(e.target.value)}
            placeholder="Paste your magpie API key..."
          />
          <button className="btn-primary" onClick={saveApiKey}>
            {saved ? 'Saved!' : 'Save'}
          </button>
        </div>
        <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>
          Stored in localStorage. Required to access the API.
        </p>
      </section>

      <section>
        <h2 style={{ fontSize: 16, fontWeight: 500, marginBottom: 12 }}>API Keys</h2>

        {newKey && (
          <div style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--green)',
            borderRadius: 8,
            padding: 12,
            marginBottom: 16,
          }}>
            <p style={{ fontSize: 13, marginBottom: 6, color: 'var(--green)' }}>
              New key created — copy it now, it won't be shown again:
            </p>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <code style={{ fontSize: 13, flex: 1 }}>{newKey}</code>
              <button className="btn-ghost" onClick={() => copyKey(newKey)} style={{ padding: '4px 8px' }}>
                <Copy size={14} />
              </button>
            </div>
          </div>
        )}

        <div style={{ display: 'flex', gap: 8, marginBottom: 16, maxWidth: 480 }}>
          <input
            value={newKeyName}
            onChange={e => setNewKeyName(e.target.value)}
            placeholder="Key name (e.g. crow-production)"
            onKeyDown={e => e.key === 'Enter' && handleCreateKey()}
          />
          <button className="btn-primary" onClick={handleCreateKey}>Create</button>
        </div>

        {keys.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>No API keys created yet.</p>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {keys.map(key => (
              <div
                key={key.id}
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  padding: '10px 12px',
                  background: 'var(--bg-surface)',
                  borderBottom: '1px solid var(--border)',
                }}
              >
                <div>
                  <span style={{ fontWeight: 500, fontSize: 14 }}>{key.name}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: 12, marginLeft: 8 }}>
                    {key.key_prefix}...
                  </span>
                  {key.last_used_at && (
                    <span style={{ color: 'var(--text-muted)', fontSize: 12, marginLeft: 12 }}>
                      Last used: {new Date(key.last_used_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
                <button className="btn-danger" onClick={() => handleDeleteKey(key.id)} style={{ padding: '4px 8px' }}>
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
