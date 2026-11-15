import { motion } from 'framer-motion';
import {
  AlertTriangle,
  ArrowRight,
  BellRing,
  Check,
  ExternalLink,
  GitCompare,
  History,
  X,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { TONE_CLASSES } from '@/features/audits/lib/styling';
import { formatBytes, formatDateTime, formatRelative } from '@/shared/lib/format';
import { listItem, staggerList } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import {
  AgentThinking,
  Badge,
  Button,
  Card,
  EmptyState,
  Markdown,
  Select,
  Skeleton,
  StatusPill,
  toast,
} from '@/shared/ui';
import { useDecideChange, useDocDiff, useDocText, useOverrideJudge } from '../hooks/useRegulation';
import {
  JUDGE,
  bindingLabel,
  diffStats,
  effectiveDecision,
  latestVersion,
  parseUnifiedDiff,
  worstDecision,
} from '../lib/regulation';
import type { JudgeDecision, RegChange, RegSource } from '../lib/types';

export function SourceRow({
  s,
  selected,
  onSelect,
}: {
  s: RegSource;
  selected: boolean;
  onSelect: () => void;
}) {
  const b = bindingLabel(s.binding);
  const last = s.versions[s.versions.length - 1];
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'w-full rounded-lg border bg-surface p-3 text-left transition-colors',
        selected ? 'border-primary/60 ring-1 ring-primary/30' : 'border-border hover:border-text/20',
      )}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge>{s.kind}</Badge>
        <Badge tone={b.tone}>{b.label}</Badge>
        <StatusPill status={s.status} tone={s.status === 'draft' ? 'warning' : 'success'} />
        <span className="ml-auto font-mono text-xs text-muted">v{latestVersion(s)}</span>
      </div>
      <div className="mt-1 text-sm font-medium">{s.title}</div>
      <div className="text-xs text-muted">
        {s.publisher} · {s.documents} doc{s.documents === 1 ? '' : 's'} · fetched{' '}
        {formatRelative(last?.fetchedAt)}
      </div>
    </button>
  );
}

export function DiffViewer({ docId, from, to }: { docId: string; from: number; to: number }) {
  const { data, isLoading } = useDocDiff(docId, from, to);
  if (isLoading) return <Skeleton className="h-40 w-full" />;
  if (!data) return <EmptyState compact title="No diff" description="Only one version so far." />;
  const lines = parseUnifiedDiff(data.unified);
  const st = diffStats(lines);
  return (
    <div>
      <div className="mb-2 flex items-center gap-2 text-xs">
        <GitCompare className="size-4 text-muted" /> v{from} → v{to}
        <span className="text-success">+{st.added}</span>
        <span className="text-danger">−{st.removed}</span>
      </div>
      <div className="overflow-x-auto rounded-lg border border-border font-mono text-xs leading-5">
        {lines.map((l, i) => (
          <div
            key={i}
            className={cn(
              'whitespace-pre-wrap px-3',
              l.type === 'add' && 'bg-success/10 text-success',
              l.type === 'del' && 'bg-danger/10 text-danger line-through decoration-danger/40',
              l.type === 'hunk' && 'bg-info/10 text-info',
              l.type === 'meta' && 'text-muted',
            )}
          >
            {l.type === 'add' ? '+ ' : l.type === 'del' ? '− ' : '  '}
            {l.text}
          </div>
        ))}
      </div>
    </div>
  );
}

export function SourceDetail({
  s,
  version,
  onVersion,
}: {
  s: RegSource;
  version: number;
  onVersion: (v: number) => void;
}) {
  const text = useDocText(s.id, version);
  const versionsWithText = s.versions.filter((v) => v.status !== 'same' && v.status !== 'failed');
  const changed = versionsWithText.filter((v) => v.version > 1);
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-semibold">{s.title}</h2>
        {s.url && (
          <a
            href={s.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
          >
            source <ExternalLink className="size-3" />
          </a>
        )}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {s.tags.map((t) => (
          <Badge key={t}>{t}</Badge>
        ))}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead className="text-muted">
            <tr>
              <th className="py-1 pr-3">Version</th>
              <th className="pr-3">Fetched</th>
              <th className="pr-3">Status</th>
              <th className="pr-3">Size</th>
              <th>Changed sections</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {s.versions.map((v) => (
              <tr
                key={v.version}
                className={cn(
                  'cursor-pointer hover:bg-surface-muted/50',
                  v.version === version && 'bg-primary/5',
                )}
                onClick={() => v.status !== 'same' && onVersion(v.version)}
              >
                <td className="py-1.5 pr-3 font-mono">v{v.version}</td>
                <td className="pr-3">{formatDateTime(v.fetchedAt)}</td>
                <td className="pr-3">
                  <StatusPill
                    status={v.status}
                    tone={v.status === 'changed' ? 'warning' : v.status === 'failed' ? 'danger' : 'neutral'}
                  />
                </td>
                <td className="pr-3">{formatBytes(v.bytes)}</td>
                <td>{v.diff?.changedSections.join(', ') ?? '–'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {changed.length > 0 && (
        <div>
          <h3 className="mb-2 text-xs font-semibold text-text/80">Latest diff</h3>
          <DiffViewer
            docId={s.id}
            from={changed[changed.length - 1].version - 1}
            to={changed[changed.length - 1].version}
          />
        </div>
      )}
      <div>
        <h3 className="mb-2 text-xs font-semibold text-text/80">Text v{version}</h3>
        {text.isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : text.data ? (
          <div className="max-h-[32rem] overflow-y-auto rounded-lg border border-border p-4">
            <Markdown>{text.data.text}</Markdown>
          </div>
        ) : (
          <EmptyState compact title="No extracted text" />
        )}
      </div>
    </div>
  );
}

function JudgeBadge({ d }: { d: JudgeDecision }) {
  const j = JUDGE[d];
  return <Badge tone={j.tone}>{j.label}</Badge>;
}

export function RegChangeCard({ c }: { c: RegChange }) {
  const decide = useDecideChange();
  const override = useOverrideJudge();
  const worst = worstDecision(c);
  return (
    <motion.div variants={listItem}>
      <Card className={cn('space-y-3 p-4', c.status === 'proposed' && 'border-warning/40')}>
        <div className="flex flex-wrap items-center gap-2">
          {c.status === 'proposed' && <BellRing className="size-4 text-warning" />}
          <span className="font-mono text-xs text-muted">{c.id}</span>
          <StatusPill status={c.status} />
          <Badge>{c.changeType}</Badge>
          <Badge className="font-mono">
            v{c.fromVersion} → v{c.toVersion} · kb {c.candidateKbVersion}
          </Badge>
          <span className="ml-auto text-xs text-muted">{formatRelative(c.detectedAt)}</span>
        </div>
        <div className="font-medium">{c.title}</div>
        <p className="text-sm text-muted">{c.summary}</p>
        <div className="flex flex-wrap gap-1.5">
          {c.provisions.map((p) => (
            <Badge key={p} tone="primary">
              {p}
            </Badge>
          ))}
        </div>

        {c.judge === 'running' && (
          <div className="rounded-lg border border-primary/25 bg-primary/5 px-3 py-2">
            <AgentThinking size="sm" label="Change judge: impact index, then Oumi Iris per affected system" />
          </div>
        )}
        {c.judge === 'failed' && (
          <div className="flex items-center gap-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-sm text-danger">
            <AlertTriangle className="size-4 shrink-0" />
            The change judge failed. The change stays accepted; check the trace and run it again.
          </div>
        )}

        {c.affected.length > 0 ? (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-xs font-semibold text-text/80">
              Affected systems{' '}
              <span className={cn('size-2 rounded-full', TONE_CLASSES[JUDGE[worst].tone].bg)} /> worst:{' '}
              {JUDGE[worst].label}
            </div>
            <motion.div
              variants={staggerList(0.06)}
              initial="initial"
              animate="animate"
              className="space-y-2"
            >
              {c.affected.map((a) => {
                const eff = effectiveDecision(a);
                return (
                  <motion.div
                    key={a.systemId}
                    variants={listItem}
                    className="rounded-lg border border-border p-3"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs">{a.systemId}</span>
                      <span className="text-sm font-medium">{a.systemName}</span>
                      <JudgeBadge d={eff} />
                      {a.humanDecision && a.humanDecision !== a.decision && (
                        <span className="text-xs text-muted">
                          (judge said {JUDGE[a.decision].label}, overridden)
                        </span>
                      )}
                      <span className="ml-auto text-xs text-muted">
                        judge confidence {Math.round(a.confidence * 100)}%
                      </span>
                    </div>
                    <div className="mt-1 flex flex-wrap items-center gap-1 font-mono text-[11px] text-muted">
                      {a.path.map((p, i) => (
                        <span key={i} className="inline-flex items-center gap-1">
                          {i > 0 && <ArrowRight className="size-3" />}
                          {p}
                        </span>
                      ))}
                    </div>
                    <p className="mt-1 text-sm [overflow-wrap:anywhere]">{a.reasoning}</p>
                    {a.counterArgument && (
                      <p className="mt-1 text-xs text-muted [overflow-wrap:anywhere]">
                        Strongest counter-argument: {a.counterArgument}
                      </p>
                    )}
                    {(a.obligations?.length ?? 0) > 0 && (
                      <div className="mt-2 flex flex-wrap items-center gap-1">
                        <span className="mr-1 text-2xs text-muted">Obligations touched</span>
                        {a.obligations!.map((o) => (
                          <Badge key={o} className="font-mono">
                            {o}
                          </Badge>
                        ))}
                      </div>
                    )}
                    {(a.staleFindings?.length ?? 0) > 0 && (
                      <div className="mt-1.5 flex flex-wrap items-center gap-1">
                        <Badge tone="warning" icon={<History />}>
                          {a.staleFindings!.length} finding{a.staleFindings!.length > 1 ? 's' : ''} marked
                          stale
                        </Badge>
                        {a.auditId && (
                          <Link
                            to={`/audits/${encodeURIComponent(a.auditId)}?view=findings`}
                            className="text-xs text-muted hover:text-text hover:underline"
                          >
                            in {a.auditId}
                          </Link>
                        )}
                      </div>
                    )}
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <Select
                        className="h-8 w-56 text-xs"
                        aria-label="Override the change judge"
                        value={eff}
                        onValueChange={(v) =>
                          override.mutate(
                            { id: c.id, systemId: a.systemId, decision: v as JudgeDecision },
                            {
                              onSuccess: () =>
                                toast.success(`${a.systemId}: ${JUDGE[v as JudgeDecision].label}`, {
                                  description: 'Override logged; it can become memory.',
                                }),
                            },
                          )
                        }
                        options={(Object.keys(JUDGE) as JudgeDecision[]).map((d) => ({
                          value: d,
                          label: JUDGE[d].label,
                        }))}
                      />
                      {a.rerunAuditId && (
                        <>
                          <Link
                            to={`/audits/${encodeURIComponent(a.rerunAuditId)}`}
                            className="text-sm text-primary hover:underline"
                          >
                            Re-run {a.rerunAuditId} →
                          </Link>
                          <Link
                            to={`/audits/${encodeURIComponent(a.rerunAuditId)}?view=findings`}
                            className="text-xs text-muted hover:text-text hover:underline"
                          >
                            delta report
                          </Link>
                        </>
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </motion.div>
          </div>
        ) : (
          c.judge !== 'running' && (
            <p className="text-sm text-muted">
              {c.status === 'proposed'
                ? 'Accept the change to run the impact index and the change judge.'
                : c.judge === 'done'
                  ? 'No system affected (the impact index found no linked obligation).'
                  : 'No judgement yet.'}
            </p>
          )
        )}

        {c.status === 'proposed' && (
          <div className="flex justify-end gap-2 border-t border-border pt-3">
            <Button
              variant="secondary"
              size="sm"
              leftIcon={<X />}
              loading={decide.isPending && decide.variables?.status === 'rejected'}
              onClick={() => decide.mutate({ id: c.id, status: 'rejected' })}
            >
              Reject change
            </Button>
            <Button
              size="sm"
              leftIcon={<Check />}
              loading={decide.isPending && decide.variables?.status === 'accepted'}
              onClick={() =>
                decide.mutate(
                  { id: c.id, status: 'accepted' },
                  {
                    onSuccess: () =>
                      toast.success(`kb_version ${c.candidateKbVersion} accepted`, {
                        description: 'Old decisions are marked stale, never rewritten.',
                      }),
                  },
                )
              }
            >
              Accept kb {c.candidateKbVersion}
            </Button>
          </div>
        )}
      </Card>
    </motion.div>
  );
}
