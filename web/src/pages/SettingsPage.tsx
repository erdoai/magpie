import { useEffect, useState } from 'react';
import { api, ApiKey, Org, Workspace } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Separator } from '@/components/ui/separator';
import { Copy, Trash2, Plus, Users, FolderOpen } from 'lucide-react';

export function SettingsPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [newKeyName, setNewKeyName] = useState('');
  const [newKey, setNewKey] = useState<string | null>(null);
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [selectedOrg, setSelectedOrg] = useState<Org | null>(null);
  const [members, setMembers] = useState<
    { id: string; email: string; display_name: string | null; role: string }[]
  >([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [newOrgName, setNewOrgName] = useState('');
  const [inviteEmail, setInviteEmail] = useState('');
  const [newWsName, setNewWsName] = useState('');

  const loadKeys = async () => {
    try { setKeys(await api.listKeys()); } catch {}
  };

  const loadOrgs = async () => {
    try { setOrgs(await api.listOrgs()); } catch {}
  };

  const loadOrgDetails = async (org: Org) => {
    setSelectedOrg(org);
    try {
      setMembers(await api.listMembers(org.id));
      setWorkspaces(await api.listWorkspaces(org.id));
    } catch {}
  };

  useEffect(() => { loadKeys(); loadOrgs(); }, []);

  const handleCreateKey = async () => {
    if (!newKeyName.trim()) return;
    try {
      const key = await api.createKey(newKeyName);
      setNewKey(key.key!);
      setNewKeyName('');
      loadKeys();
    } catch (e) { console.error(e); }
  };

  const handleCreateOrg = async () => {
    if (!newOrgName.trim()) return;
    try {
      const org = await api.createOrg(newOrgName);
      setNewOrgName('');
      loadOrgs();
      loadOrgDetails(org as unknown as Org);
    } catch (e) { console.error(e); }
  };

  const handleInvite = async () => {
    if (!selectedOrg || !inviteEmail.trim()) return;
    try {
      await api.inviteMember(selectedOrg.id, inviteEmail);
      setInviteEmail('');
      loadOrgDetails(selectedOrg);
    } catch (e) { console.error(e); }
  };

  const handleCreateWorkspace = async () => {
    if (!selectedOrg || !newWsName.trim()) return;
    try {
      await api.createWorkspace(selectedOrg.id, newWsName);
      setNewWsName('');
      loadOrgDetails(selectedOrg);
    } catch (e) { console.error(e); }
  };

  return (
    <div className="max-w-2xl space-y-6">
      <h1 className="text-xl font-semibold">Settings</h1>

      {/* Organizations */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Users size={16} /> Organizations
          </CardTitle>
          <CardDescription>
            Create orgs to share knowledge with your team.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex gap-2 mb-4">
            <Input
              value={newOrgName}
              onChange={e => setNewOrgName(e.target.value)}
              placeholder="Organization name"
              onKeyDown={e => e.key === 'Enter' && handleCreateOrg()}
            />
            <Button onClick={handleCreateOrg}><Plus size={14} className="mr-1" /> Create</Button>
          </div>

          {orgs.length > 0 && (
            <div className="flex gap-2 flex-wrap mb-4">
              {orgs.map(org => (
                <Button
                  key={org.id}
                  variant={selectedOrg?.id === org.id ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => loadOrgDetails(org)}
                >
                  {org.name}
                  <Badge variant="secondary" className="ml-1.5 text-[10px]">{org.role}</Badge>
                </Button>
              ))}
            </div>
          )}

          {selectedOrg && (
            <div className="space-y-4">
              <Separator />

              {/* Members */}
              <div>
                <h3 className="text-sm font-medium mb-2">Members</h3>
                <div className="flex gap-2 mb-2">
                  <Input
                    value={inviteEmail}
                    onChange={e => setInviteEmail(e.target.value)}
                    placeholder="Invite by email"
                    onKeyDown={e => e.key === 'Enter' && handleInvite()}
                  />
                  <Button size="sm" onClick={handleInvite}>Invite</Button>
                </div>
                <div className="flex flex-col gap-0.5">
                  {members.map(m => (
                    <div key={m.id} className="flex items-center justify-between py-1.5 px-1">
                      <div className="flex items-center gap-2">
                        <span className="text-sm">{m.display_name || m.email}</span>
                        {m.display_name && (
                          <span className="text-xs text-muted-foreground">{m.email}</span>
                        )}
                        <Badge variant="secondary" className="text-[10px]">{m.role}</Badge>
                      </div>
                      {m.role !== 'owner' && (
                        <Button
                          variant="ghost" size="icon" className="h-6 w-6 text-destructive"
                          onClick={async () => {
                            await api.removeMember(selectedOrg.id, m.id);
                            loadOrgDetails(selectedOrg);
                          }}
                        >
                          <Trash2 size={12} />
                        </Button>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <Separator />

              {/* Workspaces */}
              <div>
                <h3 className="text-sm font-medium mb-2 flex items-center gap-1.5">
                  <FolderOpen size={14} /> Workspaces
                </h3>
                <div className="flex gap-2 mb-2">
                  <Input
                    value={newWsName}
                    onChange={e => setNewWsName(e.target.value)}
                    placeholder="Workspace name (e.g. devbot, crow)"
                    onKeyDown={e => e.key === 'Enter' && handleCreateWorkspace()}
                  />
                  <Button size="sm" onClick={handleCreateWorkspace}>Create</Button>
                </div>
                {workspaces.length === 0 ? (
                  <p className="text-xs text-muted-foreground">No workspaces yet.</p>
                ) : (
                  <div className="flex gap-1.5 flex-wrap">
                    {workspaces.map(ws => (
                      <Badge key={ws.id} variant="outline" className="gap-1">
                        {ws.name}
                        <button
                          className="text-destructive hover:text-destructive"
                          onClick={async () => {
                            await api.deleteWorkspace(ws.id);
                            loadOrgDetails(selectedOrg);
                          }}
                        >
                          <Trash2 size={10} />
                        </button>
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* API Keys */}
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
                  variant="ghost" size="icon" className="h-7 w-7 shrink-0"
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
            <p className="text-muted-foreground text-sm py-2">No API keys yet.</p>
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
                    variant="ghost" size="icon"
                    className="h-7 w-7 text-destructive hover:text-destructive"
                    onClick={async () => {
                      if (!confirm('Delete this API key?')) return;
                      await api.deleteKey(key.id);
                      loadKeys();
                    }}
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
