import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter, Routes, Route } from 'react-router-dom';
import { App } from './App';
import { BrowsePage } from './pages/BrowsePage';
import { SearchPage } from './pages/SearchPage';
import { EntryPage } from './pages/EntryPage';
import { NewEntryPage } from './pages/NewEntryPage';
import { SettingsPage } from './pages/SettingsPage';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
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
  </React.StrictMode>
);
