import { Link, Outlet, useLocation } from 'react-router-dom';
import { Search, Library, Plus, Settings, LogOut } from 'lucide-react';

const NAV = [
  { path: '/', label: 'Browse', icon: Library },
  { path: '/search', label: 'Search', icon: Search },
  { path: '/new', label: 'New', icon: Plus },
  { path: '/settings', label: 'Settings', icon: Settings },
];

export function App() {
  const location = useLocation();

  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <nav style={{
        width: 200,
        borderRight: '1px solid var(--border)',
        padding: '20px 0',
        flexShrink: 0,
        display: 'flex',
        flexDirection: 'column',
      }}>
        <div style={{ padding: '0 16px 20px', fontWeight: 700, fontSize: 18 }}>
          magpie
        </div>
        {NAV.map(({ path, label, icon: Icon }) => {
          const active = location.pathname === path;
          return (
            <Link
              key={path}
              to={path}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                padding: '10px 16px',
                color: active ? 'var(--accent)' : 'var(--text-muted)',
                textDecoration: 'none',
                fontSize: 14,
                background: active ? 'var(--bg-hover)' : 'transparent',
              }}
            >
              <Icon size={16} />
              {label}
            </Link>
          );
        })}
        <div style={{ flex: 1 }} />
        <button
          onClick={() => { localStorage.removeItem('magpie_api_key'); window.location.reload(); }}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '10px 16px',
            color: 'var(--text-muted)',
            fontSize: 14,
            background: 'transparent',
            width: '100%',
            textAlign: 'left',
          }}
        >
          <LogOut size={16} />
          Sign out
        </button>
      </nav>
      <main style={{ flex: 1, padding: 24, maxWidth: 960 }}>
        <Outlet />
      </main>
    </div>
  );
}
