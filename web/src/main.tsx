import React, { useEffect, useState } from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route, Navigate, useNavigate } from 'react-router-dom';
import { App } from '@/App';
import { DashboardPage } from '@/pages/DashboardPage';
import { BrowsePage } from '@/pages/BrowsePage';
import { CollectionsPage } from '@/pages/CollectionsPage';
import { SearchPage } from '@/pages/SearchPage';
import { EntryPage } from '@/pages/EntryPage';
import { NewEntryPage } from '@/pages/NewEntryPage';
import { SettingsPage } from '@/pages/SettingsPage';
import { LoginPage } from '@/pages/LoginPage';
import { LandingPage } from '@/pages/LandingPage';
import { DocsPage } from '@/pages/DocsPage';
import { OnboardingPage } from '@/pages/OnboardingPage';
import { api } from '@/lib/api';
import './index.css';

type AuthState = 'loading' | 'anonymous' | 'onboarding' | 'app';

function LoginRoute({ onLogin }: { onLogin: () => void }) {
  const navigate = useNavigate();
  return (
    <LoginPage
      onLogin={() => {
        onLogin();
        navigate('/');
      }}
    />
  );
}

function Root() {
  const [state, setState] = useState<AuthState>('loading');

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

    setState('anonymous');
  };

  if (state === 'loading') return null;

  if (state === 'onboarding') {
    return <OnboardingPage onComplete={() => setState('app')} />;
  }

  if (state === 'anonymous') {
    return (
      <BrowserRouter>
        <Routes>
          <Route index element={<LandingPage />} />
          <Route path="docs" element={<DocsPage />} />
          <Route path="login" element={<LoginRoute onLogin={checkAuth} />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    );
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="docs" element={<DocsPage />} />
        <Route element={<App />}>
          <Route index element={<DashboardPage />} />
          <Route path="browse" element={<BrowsePage />} />
          <Route path="collections" element={<CollectionsPage />} />
          <Route path="search" element={<SearchPage />} />
          <Route path="entries/:id" element={<EntryPage />} />
          <Route path="new" element={<NewEntryPage />} />
          <Route path="settings" element={<SettingsPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>
);
