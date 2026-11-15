import { useEffect } from 'react';
import { useOpenGates } from '@/features/approvals/hooks/useApprovals';
import { useNavBadges } from '@/shared/stores/nav';

/** Feeds sidebar badge counts from feature queries: open HITL gates badge the Audits entry. Renders nothing. */
export function NavBadgesSync() {
  const { gates } = useOpenGates();
  const setBadge = useNavBadges((s) => s.setBadge);
  useEffect(() => setBadge('audits', gates.length), [gates.length, setBadge]);
  return null;
}
