import { ArrowUpRight, ClipboardList } from 'lucide-react';
import { Link } from 'react-router-dom';
import { cn } from '@/shared/lib/utils';
import { Card, CardContent, CardHeader, Skeleton } from '@/shared/ui';
import { TONE_CLASSES, type Tone } from '@/features/audits/lib/styling';
import { useRegister } from '../hooks/useRegister';
import { summaryLine } from '../lib/register';

const PARTS: {
  key: 'open_gaps' | 'needs_review' | 'accepted_risks' | 'resolved';
  label: string;
  tone: Tone;
}[] = [
  { key: 'open_gaps', label: 'Open gaps', tone: 'danger' },
  { key: 'needs_review', label: 'Needs review', tone: 'warning' },
  { key: 'accepted_risks', label: 'Accepted risks', tone: 'info' },
  { key: 'resolved', label: 'Resolved', tone: 'success' },
];

/** The system's state across audits for the Overview: "7 open gaps · 2 accepted risks · 3 resolved". */
export function RegisterStateCard({ systemId, href }: { systemId: string; href: string }) {
  const { data, isLoading } = useRegister(systemId);
  const s = data?.summary;
  return (
    <Card className="h-full">
      <CardHeader
        icon={<ClipboardList />}
        title="Status"
        description={s && s.total > 0 ? summaryLine(s) || 'No open items' : 'Across every audit'}
      />
      <CardContent>
        {isLoading ? (
          <Skeleton className="h-16 rounded-lg" />
        ) : !s || s.total === 0 ? (
          <p className="text-sm text-muted">Nothing tracked yet: a finished audit fills the register.</p>
        ) : (
          <div className="space-y-4">
            <dl className="num grid grid-cols-2 gap-x-4 gap-y-3">
              {PARTS.map((p) => (
                <div key={p.key}>
                  <dt className="text-2xs text-muted">{p.label}</dt>
                  <dd className={cn('text-xl font-semibold', s[p.key] > 0 ? TONE_CLASSES[p.tone].text : '')}>
                    {s[p.key]}
                  </dd>
                </div>
              ))}
            </dl>
            <Link to={href} className="inline-flex items-center gap-1 text-xs text-muted hover:text-text">
              See the register <ArrowUpRight className="size-3" />
            </Link>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
