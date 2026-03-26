import { useState } from 'react';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';

export function OnboardingPage({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState<'name' | 'org' | 'connect'>('name');
  const [displayName, setDisplayName] = useState('');
  const [orgName, setOrgName] = useState('');
  const [apiKey, setApiKey] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleName = async () => {
    if (!displayName.trim()) return;
    setLoading(true);
    await api.updateProfile(displayName);
    setLoading(false);
    setStep('org');
  };

  const handleOrg = async () => {
    if (!orgName.trim()) return;
    setLoading(true);
    try {
      await api.createOrg(orgName);
      // Create an API key for the user
      const key = await api.createKey('default');
      setApiKey(key.key!);
      setStep('connect');
    } catch {
      // org might already exist
    }
    setLoading(false);
  };

  return (
    <div className="flex items-center justify-center min-h-screen">
      <Card className="w-[440px]">
        <CardHeader>
          <CardTitle className="text-xl">Welcome to magpie</CardTitle>
          <CardDescription>
            {step === 'name' && "Let's set up your account."}
            {step === 'org' && 'Create an organization to share knowledge.'}
            {step === 'connect' && "You're all set. Connect your tools."}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {step === 'name' && (
            <div className="flex flex-col gap-3">
              <Input
                value={displayName}
                onChange={e => setDisplayName(e.target.value)}
                placeholder="Your name"
                autoFocus
                onKeyDown={e => e.key === 'Enter' && handleName()}
              />
              <Button onClick={handleName} disabled={loading} className="w-full">
                Continue
              </Button>
            </div>
          )}

          {step === 'org' && (
            <div className="flex flex-col gap-3">
              <Input
                value={orgName}
                onChange={e => setOrgName(e.target.value)}
                placeholder="Organization name (e.g. your company)"
                autoFocus
                onKeyDown={e => e.key === 'Enter' && handleOrg()}
              />
              <p className="text-xs text-muted-foreground">
                Team members you invite will share knowledge within this org.
              </p>
              <Button onClick={handleOrg} disabled={loading} className="w-full">
                Create organization
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setStep('connect')}>
                Skip — I'll do this later
              </Button>
            </div>
          )}

          {step === 'connect' && (
            <div className="flex flex-col gap-4">
              {apiKey && (
                <div className="p-3 rounded-md border border-border bg-card">
                  <p className="text-xs text-muted-foreground mb-1.5">
                    Your API key:
                  </p>
                  <code className="text-xs break-all">{apiKey}</code>
                </div>
              )}

              <div className="p-3 rounded-md border border-border bg-card">
                <p className="text-sm font-medium mb-2">
                  Connect Claude Code
                </p>
                <p className="text-xs text-muted-foreground mb-2">
                  Run this in your terminal:
                </p>
                <pre className="text-xs bg-background p-2 rounded overflow-x-auto">
{`claude mcp add --transport http magpie \\
  ${window.location.origin}/mcp \\
  --header "Authorization: Bearer ${apiKey || 'YOUR_API_KEY'}"`}
                </pre>
              </div>

              <div className="flex flex-wrap gap-1.5">
                <Badge variant="outline">magpie - search</Badge>
                <Badge variant="outline">magpie - write</Badge>
                <Badge variant="outline">magpie - read</Badge>
                <Badge variant="outline">magpie - list_entries</Badge>
                <Badge variant="outline">magpie - archive</Badge>
              </div>

              <Button onClick={onComplete} className="w-full">
                Go to dashboard
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
