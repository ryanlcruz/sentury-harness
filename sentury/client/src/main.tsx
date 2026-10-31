import React from 'react';
import ReactDOM from 'react-dom/client';
import { AppShell } from './app/AppShell';
import { InterfaceAtlas } from './dev/InterfaceAtlas';
import './styles/index.css';

const rootEl = document.getElementById('root');

if (rootEl) {
  const showAtlas = import.meta.env.DEV && new URLSearchParams(window.location.search).has('atlas');
  ReactDOM.createRoot(rootEl).render(
    <React.StrictMode>
      {showAtlas ? <InterfaceAtlas /> : <AppShell />}
    </React.StrictMode>
  );
}
