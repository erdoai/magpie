import { useState } from 'react';
import { api } from '../lib/api';

export function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [key, setKey] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!key.trim()) return;

    setLoading(true);
    setError('');

    // Temporarily set the key to test it
    localStorage.setItem('magpie_api_key', key.trim());
    const valid = await api.checkAuth();

    if (valid) {
      onLogin();
    } else {
      localStorage.removeItem('magpie_api_key');
      setError('Invalid API key');
    }
    setLoading(false);
  };

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      minHeight: '100vh',
    }}>
      <div style={{ width: 360 }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, marginBottom: 8 }}>magpie</h1>
        <p style={{ color: 'var(--text-muted)', fontSize: 14, marginBottom: 24 }}>
          Enter your API key to continue.
        </p>

        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <input
            type="password"
            value={key}
            onChange={e => setKey(e.target.value)}
            placeholder="mgp_... or static API key"
            autoFocus
          />
          {error && (
            <p style={{ color: 'var(--red)', fontSize: 13 }}>{error}</p>
          )}
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? 'Checking...' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
}
