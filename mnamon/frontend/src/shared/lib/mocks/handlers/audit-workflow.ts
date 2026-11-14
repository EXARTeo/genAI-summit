// Audit workflow mocks live in the feature; this file only registers them.
import { auditRoutes } from '@/features/audits/lib/mockRoutes';

export const routes = auditRoutes;
