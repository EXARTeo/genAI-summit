import { Navigate, Route, Routes } from 'react-router-dom';
import { WorkspaceShell } from './app/WorkspaceShell';
import { lazyPage } from './shared/lib/lazyPage';

// Pages are thin route views (src/pages/*View.tsx) composing features; lazy for small chunks.
const HomeView = lazyPage(() => import('./pages/HomeView'));
const SystemsView = lazyPage(() => import('./pages/SystemsView'));
const SystemDetailView = lazyPage(() => import('./pages/SystemDetailView'));
const RegisterSystemView = lazyPage(() => import('./pages/RegisterSystemView'));
const AuditsView = lazyPage(() => import('./pages/AuditsView'));
const RegulationView = lazyPage(() => import('./pages/RegulationView'));
const ChatView = lazyPage(() => import('./pages/ChatView'));
const NotFoundView = lazyPage(() => import('./pages/NotFoundView'));

export default function App() {
  return (
    <Routes>
      <Route element={<WorkspaceShell />}>
        <Route index element={<HomeView />} />
        <Route path="systems" element={<SystemsView />} />
        <Route path="systems/new" element={<RegisterSystemView />} />
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
