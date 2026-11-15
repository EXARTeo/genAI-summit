import { Route, Routes } from 'react-router-dom';
import { RegulationPage } from '@/features/regulation/pages/RegulationPage';
import { SourceReaderPage } from '@/features/regulation/pages/SourceReaderPage';

// /regulation → change inbox + sources grid, /regulation/sources/:sourceId → the source reader.
export default function RegulationView() {
  return (
    <Routes>
      <Route index element={<RegulationPage />} />
      <Route path="sources/:sourceId" element={<SourceReaderPage />} />
    </Routes>
  );
}
