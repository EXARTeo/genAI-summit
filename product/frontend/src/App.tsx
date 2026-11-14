import { lazy } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import { WorkspaceShell } from './app/WorkspaceShell';

// Pages are thin route views (src/pages/*View.tsx) composing features; lazy for small chunks.
const SystemsView = lazy(() => import('./pages/SystemsView'));
const SystemDetailView = lazy(() => import('./pages/SystemDetailView'));
const AuditsView = lazy(() => import('./pages/AuditsView'));
const ApprovalsView = lazy(() => import('./pages/ApprovalsView'));
const RegulationView = lazy(() => import('./pages/RegulationView'));
const MemoryView = lazy(() => import('./pages/MemoryView'));
const ChatView = lazy(() => import('./pages/ChatView'));
const SettingsView = lazy(() => import('./pages/SettingsView'));
const NotFoundView = lazy(() => import('./pages/NotFoundView'));

export default function App() {
  return (
    <Routes>
      <Route element={<WorkspaceShell />}>
        <Route index element={<Navigate to="/systems" replace />} />
        <Route path="systems" element={<SystemsView />} />
        <Route path="systems/:systemId" element={<SystemDetailView />} />
        <Route path="systems/:systemId/:tab" element={<SystemDetailView />} />
        <Route path="audits/*" element={<AuditsView />} />
        <Route path="approvals/*" element={<ApprovalsView />} />
        <Route path="regulation/*" element={<RegulationView />} />
        <Route path="memory/*" element={<MemoryView />} />
        <Route path="chat/*" element={<ChatView />} />
        <Route path="settings" element={<SettingsView />} />
        <Route path="*" element={<NotFoundView />} />
      </Route>
    </Routes>
  );
}
