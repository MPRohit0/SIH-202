// SPA entry point. Replaces the Next.js app router (app/layout.tsx, app/page.tsx,
// app/[view]/page.tsx) now that the build runs on plain Vite instead of vinext.
// Client-side routing (pushState/popstate) is unchanged; this only decides what
// SentriqApp receives as its initial view, and 404s anything else, matching the
// behaviour of the removed app/[view]/page.tsx.
import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import '../app/globals.css';
import '../src/content/applyPreviewText';
import SentriqApp from '../app/sentriq/app';

const VIEWS = ['dashboard', 'simulation', 'library', 'compare', 'lab', 'impact',
  'data', 'monitoring', 'exports', 'validation', 'sites', 'settings'];

function Root() {
  const view = location.pathname.split('/')[1] || 'home';
  if (view !== 'home' && !VIEWS.includes(view)) {
    return (
      <div style={{padding: 40, fontFamily: 'Arial, Helvetica, sans-serif', color: '#e6edf3'}}>
        <h1>404</h1>
        <p>This page could not be found.</p>
      </div>
    );
  }
  return <SentriqApp initialView={view} />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>
);
