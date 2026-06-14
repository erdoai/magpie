import { useEffect, useRef, useState } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import { api, Attachment, Entry, EntryLinks, EntryRevision, OutgoingLink } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { ArrowLeft, Copy, ExternalLink, History, Link2, Paperclip, Pencil, Trash2, Upload } from 'lucide-react';
import Markdown from 'react-markdown';

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const secs = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (secs < 60) return 'just now';
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function OutgoingLinkRow({ link }: { link: OutgoingLink }) {
  if (link.target_type === 'entry' && link.target_id) {
    return (
      <Link to={`/entries/${link.target_id}`} className="text-sm hover:underline">
        {link.target_title || link.link_text}
      </Link>
    );
  }
  if (link.target_type === 'url' && link.target_ref) {
    return (
      <a href={link.target_ref} target="_blank" rel="noreferrer"
         className="text-sm hover:underline inline-flex items-center gap-1">
        {link.link_text} <ExternalLink size={12} />
      </a>
    );
  }
  if (link.target_type === 'resource') {
    return <span className="text-sm font-mono">{link.target_ref}</span>;
  }
  return (
    <span className="text-sm text-muted-foreground">
      {link.link_text} <Badge variant="outline" className="text-[10px] ml-1">unresolved</Badge>
    </span>
  );
}

export function EntryPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [entry, setEntry] = useState<Entry | null>(null);
  const [links, setLinks] = useState<EntryLinks | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploadRole, setUploadRole] = useState('');
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState({ title: '', content: '', tags: '' });
  const [saving, setSaving] = useState(false);
  const [revisions, setRevisions] = useState<EntryRevision[]>([]);
  const [openRevision, setOpenRevision] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    api.getEntry(id).then(e => {
      setEntry(e);
      setForm({
        title: e.title,
        content: e.content,
        tags: e.tags.join(', '),
      });
    });
    api.getEntryLinks(id).then(setLinks).catch(() => setLinks(null));
    api.listAttachments(id).then(setAttachments).catch(() => setAttachments([]));
    api.getEntryHistory(id).then(setRevisions).catch(() => setRevisions([]));
  }, [id]);

  const handleUpload = async (file: File | undefined) => {
    if (!id || !file) return;
    setUploading(true);
    try {
      await api.uploadAttachment(id, file, { role: uploadRole || undefined });
      setUploadRole('');
      setAttachments(await api.listAttachments(id));
    } catch (e) {
      console.error(e);
      alert(String(e));
    }
    setUploading(false);
    if (fileInput.current) fileInput.current.value = '';
  };

  const handleDeleteAttachment = async (attId: string) => {
    if (!id || !confirm('Delete this attachment?')) return;
    await api.deleteAttachment(attId);
    setAttachments(await api.listAttachments(id));
  };

  const handleSave = async () => {
    if (!id) return;
    setSaving(true);
    try {
      const updated = await api.updateEntry(id, {
        title: form.title,
        content: form.content,
        tags: form.tags.split(',').map(t => t.trim()).filter(Boolean),
      });
      setEntry(updated);
      setEditing(false);
      api.getEntryLinks(id).then(setLinks).catch(() => {});
      api.getEntryHistory(id).then(setRevisions).catch(() => {});
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
          <div className="flex flex-wrap items-center gap-2.5 mb-3">
            <h1 className="text-xl font-semibold">{entry.title}</h1>
            {entry.workspace && (
              <Badge variant="secondary">
                {entry.project ? `${entry.workspace}/${entry.project}` : entry.workspace}
              </Badge>
            )}
          </div>
          {entry.tags.length > 0 && (
            <div className="flex flex-wrap gap-1 mb-4">
              {entry.tags.map(t => <Badge key={t} variant="secondary">{t}</Badge>)}
            </div>
          )}
          <p className="text-xs text-muted-foreground mb-4">
            Source: {entry.source || 'manual'} &middot; Updated: {new Date(entry.updated_at).toLocaleString()}
          </p>
          <Card>
            <CardContent className="pt-5 prose prose-invert prose-sm max-w-none">
              <Markdown>{entry.content}</Markdown>
            </CardContent>
          </Card>

          <Card className="mt-4">
            <CardContent className="pt-5">
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wide flex items-center gap-1.5">
                  <Paperclip size={12} /> Attachments
                </h2>
                <div className="flex items-center gap-2">
                  <Input
                    value={uploadRole}
                    onChange={e => setUploadRole(e.target.value)}
                    placeholder="role (e.g. logo-primary)"
                    className="h-7 w-44 text-xs"
                  />
                  <input
                    ref={fileInput}
                    type="file"
                    className="hidden"
                    onChange={e => handleUpload(e.target.files?.[0])}
                  />
                  <Button
                    variant="outline" size="sm" className="h-7 text-xs"
                    disabled={uploading}
                    onClick={() => fileInput.current?.click()}
                  >
                    <Upload size={12} className="mr-1.5" />
                    {uploading ? 'Uploading…' : 'Upload'}
                  </Button>
                </div>
              </div>
              {attachments.length === 0 ? (
                <p className="text-xs text-muted-foreground">No attachments.</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {attachments.map(att => (
                    <li key={att.id} className="flex items-center gap-3">
                      {att.kind === 'image' && (
                        <img
                          src={att.public_url || att.download_url}
                          alt={att.filename}
                          className="h-9 w-9 object-contain rounded border border-border bg-background"
                        />
                      )}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <a
                            href={att.download_url}
                            target="_blank" rel="noreferrer"
                            className="text-sm hover:underline truncate"
                          >
                            {att.filename}
                          </a>
                          <Badge variant="outline" className="text-[10px]">{att.kind}</Badge>
                          {att.role && (
                            <Badge variant="secondary" className="text-[10px]">{att.role}</Badge>
                          )}
                          {att.public && (
                            <Badge variant="secondary" className="text-[10px]">public</Badge>
                          )}
                        </div>
                        <p className="text-[11px] text-muted-foreground">
                          {(att.byte_size / 1024).toFixed(1)} KB
                          {att.description ? ` · ${att.description}` : ''}
                        </p>
                      </div>
                      <Button
                        variant="ghost" size="sm" className="h-7 text-xs"
                        title="Copy handle"
                        onClick={() => navigator.clipboard.writeText(att.handle)}
                      >
                        <Copy size={12} className="mr-1" /> handle
                      </Button>
                      {att.public_url && (
                        <Button
                          variant="ghost" size="sm" className="h-7 text-xs"
                          title="Copy public URL"
                          onClick={() => navigator.clipboard.writeText(att.public_url!)}
                        >
                          <Copy size={12} className="mr-1" /> URL
                        </Button>
                      )}
                      <Button
                        variant="ghost" size="icon"
                        className="h-7 w-7 text-destructive hover:text-destructive"
                        onClick={() => handleDeleteAttachment(att.id)}
                      >
                        <Trash2 size={13} />
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          {links && (links.outgoing.length > 0 || links.backlinks.length > 0) && (
            <Card className="mt-4">
              <CardContent className="pt-5">
                <div className="flex flex-col gap-4 sm:flex-row sm:gap-12">
                  {links.outgoing.length > 0 && (
                    <div>
                      <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 flex items-center gap-1.5">
                        <Link2 size={12} /> Links
                      </h2>
                      <ul className="flex flex-col gap-1">
                        {links.outgoing.map(link => (
                          <li key={link.id}><OutgoingLinkRow link={link} /></li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {links.backlinks.length > 0 && (
                    <div>
                      <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-2 flex items-center gap-1.5">
                        <Link2 size={12} className="rotate-180" /> Backlinks
                      </h2>
                      <ul className="flex flex-col gap-1">
                        {links.backlinks.map(link => (
                          <li key={link.id}>
                            <Link to={`/entries/${link.source_id}`} className="text-sm hover:underline">
                              {link.source_title}
                            </Link>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          )}

          {revisions.length > 0 && (
            <Card className="mt-4">
              <CardContent className="pt-5">
                <h2 className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-3 flex items-center gap-1.5">
                  <History size={12} /> History
                </h2>
                <ul className="flex flex-col">
                  {revisions.map(rev => (
                    <li key={rev.id} className="border-b border-border last:border-b-0 py-2">
                      <button
                        className="flex items-center gap-2 w-full text-left hover:opacity-80"
                        onClick={() => setOpenRevision(openRevision === rev.id ? null : rev.id)}
                      >
                        <span className="text-sm truncate flex-1">{rev.previous_title}</span>
                        {rev.actor_type && (
                          <Badge variant="outline" className="text-[10px]">{rev.actor_type}</Badge>
                        )}
                        <span className="text-xs text-muted-foreground shrink-0">
                          {relativeTime(rev.created_at)}
                        </span>
                      </button>
                      {openRevision === rev.id && (
                        <div className="mt-2 prose prose-invert prose-sm max-w-none border-l-2 border-border pl-3">
                          <Markdown>{rev.previous_content}</Markdown>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
