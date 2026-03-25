import { Link, Outlet, useLocation } from 'react-router-dom';
import { Search, Library, Plus, Settings, LogOut } from 'lucide-react';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Separator } from '@/components/ui/separator';

const NAV = [
  { path: '/', label: 'Browse', icon: Library },
  { path: '/search', label: 'Search', icon: Search },
  { path: '/new', label: 'New', icon: Plus },
  { path: '/settings', label: 'Settings', icon: Settings },
];

export function App() {
  const location = useLocation();

  return (
    <div className="flex min-h-screen">
      <nav className="w-52 border-r border-border flex flex-col shrink-0">
        <div className="px-4 py-5 font-bold text-lg">magpie</div>
        <div className="flex flex-col gap-0.5 px-2">
          {NAV.map(({ path, label, icon: Icon }) => {
            const active = location.pathname === path;
            return (
              <Link
                key={path}
                to={path}
                className={cn(
                  'flex items-center gap-2.5 px-3 py-2 rounded-md text-sm no-underline transition-colors',
                  active
                    ? 'bg-accent text-primary font-medium'
                    : 'text-muted-foreground hover:bg-accent/50 hover:text-foreground'
                )}
              >
                <Icon size={16} />
                {label}
              </Link>
            );
          })}
        </div>
        <div className="flex-1" />
        <Separator />
        <div className="p-2">
          <Button
            variant="ghost"
            size="sm"
            className="w-full justify-start gap-2.5 text-muted-foreground"
            onClick={async () => {
              localStorage.removeItem('magpie_api_key');
              try { await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' }); } catch {}
              window.location.reload();
            }}
          >
            <LogOut size={16} />
            Sign out
          </Button>
        </div>
      </nav>
      <main className="flex-1 p-6 max-w-4xl">
        <Outlet />
      </main>
    </div>
  );
}
