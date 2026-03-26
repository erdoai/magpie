import { Link } from 'react-router-dom';
import { Archive, Trash2 } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import type { Entry } from '@/lib/api';

const CATEGORY_COLORS: Record<string, string> = {
  project: 'text-[oklch(0.6_0.16_250)]',
  area: 'text-[oklch(0.65_0.18_300)]',
  resource: 'text-[oklch(0.65_0.17_145)]',
  archive: 'text-muted-foreground',
};

export function EntryCard({
  entry,
  onArchive,
  onDelete,
  showScore,
}: {
  entry: Entry;
  onArchive?: (id: string) => void;
  onDelete?: (id: string) => void;
  showScore?: boolean;
}) {
  return (
    <div className="flex items-start justify-between px-4 py-3 bg-card border-b border-border hover:bg-accent/30 transition-colors">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <Link
            to={`/entries/${entry.id}`}
            className="font-medium text-sm hover:underline truncate"
          >
            {entry.title}
          </Link>
          <Badge variant="outline" className={CATEGORY_COLORS[entry.category]}>
            {entry.category}
          </Badge>
          {entry.workspace && (
            <Badge variant="secondary" className="text-[10px]">
              {entry.workspace}
            </Badge>
          )}
          {showScore && entry.score != null && (
            <span className="text-xs text-muted-foreground">
              {entry.score.toFixed(4)}
            </span>
          )}
        </div>
        <p className="text-xs text-muted-foreground truncate max-w-xl">
          {entry.content.slice(0, 140)}
        </p>
        {entry.tags.length > 0 && (
          <div className="flex gap-1 mt-1.5">
            {entry.tags.map(t => (
              <Badge key={t} variant="secondary" className="text-[10px] px-1.5 py-0">
                {t}
              </Badge>
            ))}
          </div>
        )}
      </div>
      <div className="flex gap-1 ml-3 shrink-0">
        {onArchive && entry.category !== 'archive' && (
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => onArchive(entry.id)}>
            <Archive size={14} />
          </Button>
        )}
        {onDelete && (
          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive" onClick={() => onDelete(entry.id)}>
            <Trash2 size={14} />
          </Button>
        )}
      </div>
    </div>
  );
}
