import { Route, Routes } from 'react-router-dom';
import { AuditRunPage } from '@/features/audits/pages/AuditRunPage';
import { AuditsListPage } from '@/features/audits/pages/AuditsListPage';

// /audits → list, /audits/:auditId → the live run page.
export default function AuditsView() {
  return (
    <Routes>
      <Route index element={<AuditsListPage />} />
      <Route path=":auditId" element={<AuditRunPage />} />
    </Routes>
  );
}
