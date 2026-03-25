import { useState } from 'react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export function LoginPage({ onLogin }: { onLogin: () => void }) {
  const [mode, setMode] = useState<'email' | 'api-key'>('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'email' | 'code'>('email');
  const [apiKey, setApiKey] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSendCode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim()) return;
    setLoading(true);
    setError('');
    try {
      await api.sendCode(email);
      setStep('code');
    } catch {
      setError('Failed to send code. Check email configuration.');
    }
    setLoading(false);
  };

  const handleVerifyCode = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;
    setLoading(true);
    setError('');
    try {
      await api.verifyCode(email, code);
      onLogin();
    } catch {
      setError('Invalid or expired code.');
    }
    setLoading(false);
  };

  const handleApiKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!apiKey.trim()) return;
    setLoading(true);
    setError('');
    localStorage.setItem('magpie_api_key', apiKey.trim());
    const valid = await api.checkAuth();
    if (valid) {
      onLogin();
    } else {
      localStorage.removeItem('magpie_api_key');
      setError('Invalid API key.');
    }
    setLoading(false);
  };

  return (
    <div className="flex items-center justify-center min-h-screen">
      <Card className="w-[380px]">
        <CardHeader>
          <CardTitle className="text-2xl">magpie</CardTitle>
          <CardDescription>
            {mode === 'email' ? 'Sign in with your email.' : 'Sign in with an API key.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {mode === 'email' ? (
            step === 'email' ? (
              <form onSubmit={handleSendCode} className="flex flex-col gap-3">
                <Input
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  placeholder="you@company.com"
                  autoFocus
                />
                {error && <p className="text-sm text-destructive">{error}</p>}
                <Button type="submit" disabled={loading} className="w-full">
                  {loading ? 'Sending...' : 'Send code'}
                </Button>
              </form>
            ) : (
              <form onSubmit={handleVerifyCode} className="flex flex-col gap-3">
                <p className="text-sm text-muted-foreground">
                  Code sent to <strong>{email}</strong>
                </p>
                <Input
                  value={code}
                  onChange={e => setCode(e.target.value)}
                  placeholder="6-digit code"
                  autoFocus
                  maxLength={6}
                />
                {error && <p className="text-sm text-destructive">{error}</p>}
                <Button type="submit" disabled={loading} className="w-full">
                  {loading ? 'Verifying...' : 'Verify'}
                </Button>
                <Button
                  type="button" variant="ghost" size="sm"
                  onClick={() => { setStep('email'); setCode(''); setError(''); }}
                >
                  Use a different email
                </Button>
              </form>
            )
          ) : (
            <form onSubmit={handleApiKey} className="flex flex-col gap-3">
              <Input
                type="password"
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                placeholder="mgp_... or static API key"
                autoFocus
              />
              {error && <p className="text-sm text-destructive">{error}</p>}
              <Button type="submit" disabled={loading} className="w-full">
                {loading ? 'Checking...' : 'Sign in'}
              </Button>
            </form>
          )}

          <div className="mt-4 pt-3 border-t border-border text-center">
            <Button
              variant="link" size="sm" className="text-xs text-muted-foreground"
              onClick={() => {
                setMode(mode === 'email' ? 'api-key' : 'email');
                setError('');
              }}
            >
              {mode === 'email' ? 'Use API key instead' : 'Use email instead'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
