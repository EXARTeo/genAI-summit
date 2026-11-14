import { useEffect } from 'react';
import { useOpenGates } from '@/features/approvals/hooks/useApprovals';
import { useNavBadges } from '@/shared/stores/nav';

/** Feeds sidebar badge counts from feature queries. Renders nothing. */
export function NavBadgesSync() {
  const { gates } = useOpenGates();
  const setBadge = useNavBadges((s) => s.setBadge);
  useEffect(() => setBadge('approvals', gates.length), [gates.length, setBadge]);
  return null;
}
