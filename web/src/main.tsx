import React, { useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { App } from '@/App';
import { BrowsePage } from '@/pages/BrowsePage';
import { SearchPage } from '@/pages/SearchPage';
import { EntryPage } from '@/pages/EntryPage';
import { NewEntryPage } from '@/pages/NewEntryPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { LoginPage } from '@/pages/LoginPage';
import { api } from '@/lib/api';
import './index.css';

function Root() {
  const [authed, setAuthed] = useState<boolean | null>(null);

  useEffect(() => {
    // Check session cookie first, then API key
    api.getMe().then(res => {
      if (res.user) {
        setAuthed(true);
        return;
      }
      // No session — check if there's an API key
      const key = localStorage.getItem('magpie_api_key');
      if (key) {
        api.checkAuth().then(ok => setAuthed(ok));
      } else {
        setAuthed(false);
      }
    }).catch(() => {
      setAuthed(false);
    });
  }, []);

  if (authed === null) return null;
  if (!authed) return <LoginPage onLogin={() => setAuthed(true)} />;

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<BrowsePage />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="entries/:id" element={<EntryPage />} />
          <Route path="new" element={<NewEntryPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
