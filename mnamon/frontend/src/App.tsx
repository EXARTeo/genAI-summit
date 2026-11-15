import { lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { WorkspaceShell } from './app/WorkspaceShell';

// Pages are thin route views (src/pages/*View.tsx) composing features; lazy for small chunks.
const HomeView = lazy(() => import('./pages/HomeView'));
const SystemsView = lazy(() => import('./pages/SystemsView'));
const SystemDetailView = lazy(() => import('./pages/SystemDetailView'));
const AuditsView = lazy(() => import('./pages/AuditsView'));
const RegulationView = lazy(() => import('./pages/RegulationView'));
const ChatView = lazy(() => import('./pages/ChatView'));
const NotFoundView = lazy(() => import('./pages/NotFoundView'));

export default function App() {
  return (
    <Routes>
      <Route element={<WorkspaceShell />}>
        <Route index element={<HomeView />} />
        <Route path="systems" element={<SystemsView />} />
        <Route path="systems/:systemId" element={<SystemDetailView />} />
        <Route path="systems/:systemId/:tab" element={<SystemDetailView />} />
        <Route path="audits/*" element={<AuditsView />} />
        {/* The Approvals page is gone (gates live on the audit page); old links land on Audits. */}
        <Route path="approvals/*" element={<Navigate to="/audits" replace />} />
        <Route path="regulation/*" element={<RegulationView />} />
        <Route path="chat/*" element={<ChatView />} />
        <Route path="*" element={<NotFoundView />} />
      </Route>
    </Routes>
  );
}
