import { ChevronDown, ExternalLink, FileLock2, Gavel, History, Lock, Scale, ShieldAlert } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { formatRelative } from '@/shared/lib/format';
import { cn } from '@/shared/lib/utils';
import { Badge, Tooltip } from '@/shared/ui';
import {
  JUDGES,
  articleOf,
  judgeCall,
  judgesAgree,
  severityMeta,
  shortHash,
  textList,
  titleOf,
  type SealedFinding,
} from '../../lib/findings';
import { mlflowRunUrl } from '../../lib/mlflow';
import { TONE_CLASSES, verdictStyle } from '../../lib/styling';
import { DASH, SubHeading, VerdictPill } from '../artifact_parts/common';
import { AnnotationThread } from './AnnotationThread';

function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section>
      <SubHeading right={right}>{title}</SubHeading>
      {children}
    </section>
  );
}

function Bullets({ items }: { items: string[] }) {
  if (items.length === 0) return <p className="text-sm text-muted">{DASH}</p>;
  return (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {items.map((t, i) => (
        <li key={i} className="break-words">
          {t}
        </li>
      ))}
    </ul>
  );
}

/** The three judges side by side (rule, Gemini, Iris): the code compares them; disagreement = inconclusive. */
function Judges({ judges }: { judges: Record<string, unknown> }) {
  const agree = judgesAgree(judges);
  return (
    <Section
      title="Judges"
      right={
        agree == null ? null : agree ? (
          <Badge tone="success">Agree</Badge>
        ) : (
          <Badge tone="warning" icon={<ShieldAlert />}>
            Disagree · needs a human
          </Badge>
        )
      }
    >
      <div className="grid gap-2 sm:grid-cols-3">
        {JUDGES.map((j) => {
          const call = judgeCall(judges[j.key]);
          return (
            <div key={j.key} className="min-w-0 rounded-lg border border-border bg-surface-muted/30 p-3">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-muted">{j.label}</span>
                {call?.confidence != null && (
                  <span className="num font-mono text-2xs text-muted">
                    {Math.round(call.confidence * 100)}%
                  </span>
                )}
              </div>
              <div className="mt-1.5">
                {call?.verdict ? (
                  <VerdictPill verdict={call.verdict} />
                ) : (
                  <span className="text-xs text-muted">not called</span>
                )}
              </div>
              {call?.rationale && (
                <p className="mt-1.5 text-xs text-muted [overflow-wrap:anywhere]">{call.rationale}</p>
              )}
            </div>
          );
        })}
      </div>
    </Section>
  );
}

/** Small key/value view of `metrics_ref` (primitive fields only; a path shows as a file). */
function Metrics({ value }: { value: unknown }) {
  if (value == null) return null;
  if (typeof value !== 'object')
    return <p className="font-mono text-xs [overflow-wrap:anywhere]">{String(value)}</p>;
  const entries = Object.entries(value as Record<string, unknown>).filter(
    ([, v]) => v != null && (typeof v !== 'object' || Array.isArray(v)),
  );
  if (entries.length === 0) return null;
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs">
      {entries.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k.replace(/_/g, ' ')}</dt>
          <dd className="num font-mono [overflow-wrap:anywhere]">
            {Array.isArray(v)
              ? v
                  .map((x) => (typeof x === 'number' ? x.toFixed(3) : String(x)))
                  .join(v.length === 2 && v.every((x) => typeof x === 'number') ? ' – ' : ', ')
              : typeof v === 'number'
                ? String(Number(v.toFixed(4)))
                : String(v)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

export function SealedFindingCard({ f, defaultOpen }: { f: SealedFinding; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(!!defaultOpen);
  const sev = severityMeta(f.severity);
  const article = articleOf(f);
  const title = titleOf(f);
  const tone = verdictStyle(f.verdict).tone;
  const critic = f.critic ?? {};
  const objection = typeof critic.objection === 'string' ? critic.objection : null;

  return (
    <article
      className={cn(
        'break-inside-avoid overflow-hidden rounded-lg border bg-surface',
        open ? 'border-text/15' : 'border-border',
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-start gap-3 p-4 text-left transition-colors hover:bg-surface-muted/40"
      >
        <span className={cn('mt-0.5 h-10 w-1 shrink-0 rounded-full', TONE_CLASSES[tone].bg)} aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5">
            <VerdictPill verdict={f.verdict} />
            {sev && <Badge tone={sev.tone}>{sev.label}</Badge>}
            {f.gap_id && <Badge tone="danger">{f.gap_id}</Badge>}
            {f.sealed ? (
              <Tooltip content={`Sealed · hash ${shortHash(f.hash, 16)}`}>
                <span className="inline-flex">
                  <Badge tone="primary" icon={<Lock />}>
                    Sealed
                  </Badge>
                </span>
              </Tooltip>
            ) : (
              <Tooltip content="An older audit: this finding is an artifact, not a sealed record.">
                <span className="inline-flex">
                  <Badge>Not sealed</Badge>
                </span>
              </Tooltip>
            )}
            {f.stale && (
              <Badge tone="warning" icon={<History />}>
                Stale
              </Badge>
            )}
            {f.status === 'superseded' && <Badge icon={<History />}>Superseded</Badge>}
            {f.annotations.length > 0 && (
              <span className="text-2xs text-muted">
                · {f.annotations.length} note{f.annotations.length > 1 ? 's' : ''}
              </span>
            )}
          </div>
          <div className="mt-1.5 text-sm font-medium">
            {article && <span>{article}</span>}
            {article && title && <span className="text-muted"> · </span>}
            {title && <span>{title}</span>}
            {!article && !title && <span>{f.obligation_id}</span>}
          </div>
          <div className="mt-0.5 font-mono text-2xs text-muted [overflow-wrap:anywhere]">
            {f.obligation_id}
          </div>
        </div>
        <ChevronDown
          className={cn(
            'mt-1 size-4 shrink-0 text-muted transition-transform print:hidden',
            open && 'rotate-180',
          )}
        />
      </button>

      {open && (
        <div className="space-y-5 border-t border-border px-4 pb-4 pt-4">
          <Section title="Reasoning">
            <p className="whitespace-pre-wrap break-words text-sm">{f.reasoning || DASH}</p>
          </Section>

          {Object.keys(f.judges ?? {}).length > 0 && <Judges judges={f.judges} />}

          {(objection || critic.upheld != null) && (
            <Section title="Critic">
              <div className="flex gap-2 rounded-lg border border-border bg-surface-muted/30 p-3 text-sm">
                <Gavel className="mt-0.5 size-4 shrink-0 text-muted" />
                <div className="min-w-0">
                  {critic.upheld != null && (
                    <Badge tone={critic.upheld ? 'success' : 'warning'} className="mb-1">
                      {critic.upheld ? 'Verdict upheld' : 'Objection stands'}
                    </Badge>
                  )}
                  <p className="break-words">{objection ?? DASH}</p>
                </div>
              </div>
            </Section>
          )}

          <div className="grid gap-x-6 gap-y-5 sm:grid-cols-2">
            <Section title="Counter-arguments">
              <Bullets items={textList(f.counter_arguments)} />
            </Section>
            <Section title="Would change if">
              <Bullets items={textList(f.would_change_if)} />
            </Section>
          </div>

          {f.metrics_ref != null && (
            <Section title="Metrics">
              <Metrics value={f.metrics_ref} />
            </Section>
          )}

          <Section title="Evidence">
            {f.evidence_refs.length === 0 ? (
              <p className="text-sm text-muted">{DASH}</p>
            ) : (
              <ul className="space-y-1.5">
                {f.evidence_refs.map((e, i) => {
                  const run = mlflowRunUrl(e.mlflow_run_id, e.experiment_id);
                  return (
                    <li
                      key={`${e.path}-${i}`}
                      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border px-3 py-2 text-xs"
                    >
                      <FileLock2 className="size-3.5 shrink-0 text-muted" />
                      <span className="min-w-0 flex-1 font-mono [overflow-wrap:anywhere]">{e.path}</span>
                      {e.sha256 && (
                        <Tooltip content={`sha256 ${e.sha256}`}>
                          <span className="num font-mono text-muted">sha256 {shortHash(e.sha256)}</span>
                        </Tooltip>
                      )}
                      {run && (
                        <a
                          href={run}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-primary hover:underline"
                        >
                          MLflow run <ExternalLink className="size-3" />
                        </a>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </Section>

          <Section title="Citations">
            {f.citations.length === 0 ? (
              <p className="text-sm text-muted">{DASH}</p>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {f.citations.map((c, i) => (
                  <Badge key={`${c.provision_id}-${i}`} icon={<Scale />}>
                    {c.provision_id}
                    {c.kb_version && <span className="font-mono text-muted"> · kb {c.kb_version}</span>}
                  </Badge>
                ))}
              </div>
            )}
          </Section>

          <Section title={`Annotations${f.annotations.length ? ` (${f.annotations.length})` : ''}`}>
            <AnnotationThread
              auditId={f.audit_id}
              findingId={f.id}
              annotations={f.annotations}
              canAnnotate={f.sealed}
            />
          </Section>

          {f.sealed && (
            <div className="num mt-4 flex flex-wrap gap-x-4 gap-y-1 border-t border-border pt-3 font-mono text-2xs text-muted">
              <span>hash {shortHash(f.hash, 16)}</span>
              <span>prev {shortHash(f.prev_hash, 16)}</span>
              {f.kb_version && <span>kb {f.kb_version}</span>}
              {f.created_at && <span className="font-sans">sealed {formatRelative(f.created_at)}</span>}
              <span className="font-sans">by {f.created_by}</span>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
