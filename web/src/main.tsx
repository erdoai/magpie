import React, { useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { App } from '@/App';
import { DashboardPage } from '@/pages/DashboardPage';
import { BrowsePage } from '@/pages/BrowsePage';
import { SearchPage } from '@/pages/SearchPage';
import { EntryPage } from '@/pages/EntryPage';
import { NewEntryPage } from '@/pages/NewEntryPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { LoginPage } from '@/pages/LoginPage';
import { OnboardingPage } from '@/pages/OnboardingPage';
import { api } from '@/lib/api';
import './index.css';

function Root() {
  const [state, setState] = useState<'loading' | 'login' | 'onboarding' | 'app'>('loading');

  useEffect(() => {
    checkAuth();
  }, []);

  const checkAuth = async () => {
    try {
      const res = await api.getMe();
      if (res.user) {
        // Logged in via session — check if onboarding needed
        if (!res.user.display_name || res.orgs.length === 0) {
          setState('onboarding');
        } else {
          setState('app');
        }
        return;
      }
    } catch {}

    // No session — try API key
    const key = localStorage.getItem('magpie_api_key');
    if (key) {
      const ok = await api.checkAuth();
      if (ok) { setState('app'); return; }
    }

    setState('login');
  };

  if (state === 'loading') return null;
  if (state === 'login') return <LoginPage onLogin={checkAuth} />;
  if (state === 'onboarding') return <OnboardingPage onComplete={() => setState('app')} />;

  return (
    <BrowserRouter>
      <Routes>
        <Route element={<App />}>
          <Route index element={<DashboardPage />} />
          <Route path="browse" element={<BrowsePage />} />
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
