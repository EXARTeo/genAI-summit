import {
  CircleCheck,
  CircleX,
  ExternalLink,
  FileLock2,
  FlaskConical,
  Gavel,
  Lock,
  Scale,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { formatRelative } from '@/shared/lib/format';
import { cn } from '@/shared/lib/utils';
import { Badge, Tooltip } from '@/shared/ui';
import {
  JUDGES,
  articleLabel,
  chapterOf,
  dossierEvidence,
  judgeCall,
  judgesAgree,
  metricRows,
  severityMeta,
  shortHash,
  textList,
  titleOf,
  type SealedFinding,
} from '../../lib/findings';
import { mlflowRunUrl } from '../../lib/mlflow';
import { TONE_CLASSES, verdictStyle } from '../../lib/styling';
import { DASH } from '../artifact_parts/common';
import { AnnotationThread } from './AnnotationThread';
import { SeverityMark } from './FindingRow';

function Block({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <section className="border-t border-border pt-4">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="text-2xs font-semibold uppercase tracking-wider text-muted">{title}</h4>
        {right}
      </div>
      {children}
    </section>
  );
}

function Bullets({ items, empty = DASH }: { items: string[]; empty?: string }) {
  if (items.length === 0) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <ul className="space-y-1.5 text-sm">
      {items.map((t, i) => (
        <li key={i} className="flex gap-2 break-words">
          <span className="mt-2 size-1 shrink-0 rounded-full bg-muted" />
          <span className="min-w-0">{t}</span>
        </li>
      ))}
    </ul>
  );
}

function VerdictText({ verdict, className }: { verdict: string; className?: string }) {
  const v = verdictStyle(verdict);
  return (
    <span
      className={cn('inline-flex items-center gap-1.5 font-medium', TONE_CLASSES[v.tone].text, className)}
    >
      <span className={cn('size-1.5 rounded-full', TONE_CLASSES[v.tone].dot)} />
      {v.label}
    </span>
  );
}

/** Primitive `metrics_ref` fields (not the test-row list, not internal ids). */
function metricEntries(value: unknown): [string, string][] {
  if (value == null || typeof value !== 'object' || Array.isArray(value)) return [];
  return Object.entries(value as Record<string, unknown>)
    .filter(([k, v]) => k !== 'rows' && k !== 'artifact_id' && v != null)
    .filter(([, v]) => typeof v !== 'object' || Array.isArray(v))
    .map(([k, v]) => [
      k.replace(/_/g, ' '),
      Array.isArray(v)
        ? v
            .map((x) => (typeof x === 'number' ? x.toFixed(3) : String(x)))
            .join(v.length === 2 && v.every((x) => typeof x === 'number') ? ' – ' : ', ')
        : typeof v === 'number'
          ? String(Number(v.toFixed(4)))
          : String(v),
    ]);
}

/** Everything about one finding: why, tests, judges, critic, evidence, citations, notes, seal. */
export function FindingDetail({ f }: { f: SealedFinding }) {
  const v = verdictStyle(f.verdict);
  const sev = severityMeta(f.severity);
  const article = articleLabel(f);
  const title = titleOf(f);
  const critic = f.critic ?? {};
  const objection = typeof critic.objection === 'string' && critic.objection ? critic.objection : null;
  const grounds = typeof critic.grounds === 'string' && critic.grounds ? critic.grounds : null;
  const tests = metricRows(f.metrics_ref);
  const metrics = metricEntries(f.metrics_ref);
  const dossier = dossierEvidence(f.data);
  const mode = typeof f.data.verification_mode === 'string' ? f.data.verification_mode : null;
  const inForce = typeof f.data.in_force_date === 'string' ? f.data.in_force_date : null;
  const judges = f.judges ?? {};
  const hasJudges = Object.keys(judges).length > 0;
  const agree = judgesAgree(judges);
  const counter = textList(f.counter_arguments);
  const changeIf = textList(f.would_change_if);

  return (
    <div className="space-y-4">
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
          <VerdictText verdict={f.verdict} />
          {sev && (
            <span className="inline-flex items-center gap-1.5 text-muted">
              <SeverityMark severity={f.severity} />
              {sev.label}
            </span>
          )}
          {f.stale && <Badge tone="warning">Stale</Badge>}
          {f.status === 'superseded' && <Badge>Superseded</Badge>}
        </div>
        <div>
          <div className="text-2xs text-muted">{chapterOf(f)}</div>
          <h3 className="font-heading text-2xl font-semibold leading-tight">{article ?? f.obligation_id}</h3>
          {title && <p className="mt-1 text-sm text-text/85">{title}</p>}
        </div>
        <dl className="flex flex-wrap gap-x-4 gap-y-1 text-2xs text-muted">
          <div className="flex gap-1">
            <dt>Obligation</dt>
            <dd className="font-mono text-text/80 [overflow-wrap:anywhere]">{f.obligation_id}</dd>
          </div>
          {f.gap_id && (
            <div className="flex gap-1">
              <dt>Gap</dt>
              <dd className="font-mono text-text/80">{f.gap_id}</dd>
            </div>
          )}
          {mode && (
            <div className="flex gap-1">
              <dt>Mode</dt>
              <dd className="text-text/80">{mode.replace(/_/g, ' ')}</dd>
            </div>
          )}
          {inForce && (
            <div className="flex gap-1">
              <dt>In force</dt>
              <dd className="num text-text/80">{inForce}</dd>
            </div>
          )}
        </dl>
      </header>

      <Block title="Reasoning">
        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">{f.reasoning || DASH}</p>
      </Block>

      {(tests.length > 0 || metrics.length > 0) && (
        <Block title="Tests and metrics">
          {tests.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {tests.map((t) => (
                <span
                  key={t}
                  className="inline-flex items-center gap-1 rounded-md border border-border bg-surface-sunken/60 px-1.5 py-0.5 font-mono text-2xs"
                >
                  <FlaskConical className="size-3 text-muted" />
                  {t}
                </span>
              ))}
            </div>
          )}
          {metrics.length > 0 && (
            <dl
              className={cn('grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-xs', tests.length > 0 && 'mt-3')}
            >
              {metrics.map(([k, val]) => (
                <div key={k} className="contents">
                  <dt className="text-muted">{k}</dt>
                  <dd className="num font-mono [overflow-wrap:anywhere]">{val}</dd>
                </div>
              ))}
            </dl>
          )}
        </Block>
      )}

      {(dossier.present.length > 0 || dossier.missing.length > 0) && (
        <Block title="Dossier evidence">
          <ul className="space-y-1 text-xs">
            {dossier.missing.map((m) => (
              <li key={`m-${m}`} className="flex items-start gap-2">
                <CircleX className="mt-px size-3.5 shrink-0 text-danger" />
                <span className="min-w-0">
                  <span className="text-muted">Missing </span>
                  <span className="font-mono [overflow-wrap:anywhere]">{m}</span>
                </span>
              </li>
            ))}
            {dossier.present.map((p) => (
              <li key={`p-${p}`} className="flex items-start gap-2">
                <CircleCheck className="mt-px size-3.5 shrink-0 text-success" />
                <span className="min-w-0 font-mono [overflow-wrap:anywhere]">{p}</span>
              </li>
            ))}
          </ul>
        </Block>
      )}

      {hasJudges && (
        <Block
          title="Judges"
          right={
            agree == null ? null : agree ? (
              <span className="text-2xs text-success">All agree</span>
            ) : (
              <span className="text-2xs text-warning">Disagree · needs a human</span>
            )
          }
        >
          <ul className="divide-y divide-border rounded-lg border border-border">
            {JUDGES.map((j) => {
              const call = judgeCall(judges[j.key]);
              const why = call?.rationale ?? (typeof call?.why === 'string' ? call.why : null);
              return (
                <li key={j.key} className="px-3 py-2">
                  <div className="flex items-center gap-3 text-xs">
                    <span className="w-20 shrink-0 text-muted">{j.label}</span>
                    {call?.verdict ? (
                      <VerdictText verdict={call.verdict} />
                    ) : (
                      <span className="text-muted">not called</span>
                    )}
                    {call?.confidence != null && (
                      <span className="num ml-auto font-mono text-2xs text-muted">
                        {Math.round(call.confidence * 100)}%
                      </span>
                    )}
                  </div>
                  {why && <p className="mt-1 text-2xs text-muted [overflow-wrap:anywhere]">{why}</p>}
                </li>
              );
            })}
          </ul>
        </Block>
      )}

      {(objection || grounds || critic.upheld != null) && (
        <Block
          title="Critic"
          right={
            critic.upheld != null && (
              <span className={cn('text-2xs', critic.upheld ? 'text-success' : 'text-warning')}>
                {critic.upheld ? 'Verdict upheld' : 'Objection stands'}
              </span>
            )
          }
        >
          <div className="flex gap-2.5 text-sm">
            <Gavel className="mt-0.5 size-4 shrink-0 text-muted" />
            <div className="min-w-0 space-y-1.5">
              {objection && <p className="break-words italic">“{objection}”</p>}
              {grounds && <p className="break-words text-xs text-muted">{grounds}</p>}
              {!objection && !grounds && <p className="text-muted">No objection raised.</p>}
            </div>
          </div>
        </Block>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <Block title="Counter-arguments">
          <Bullets items={counter} empty="None recorded." />
        </Block>
        <Block title="Would change if">
          <Bullets items={changeIf} empty="None recorded." />
        </Block>
      </div>

      <Block title="Evidence files">
        {f.evidence_refs.length === 0 ? (
          <p className="text-sm text-muted">None.</p>
        ) : (
          <ul className="space-y-1">
            {f.evidence_refs.map((e, i) => {
              const run = mlflowRunUrl(e.mlflow_run_id, e.experiment_id);
              return (
                <li key={`${e.path}-${i}`} className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
                  <FileLock2 className="size-3.5 shrink-0 text-muted" />
                  <span className="min-w-0 flex-1 font-mono [overflow-wrap:anywhere]">{e.path}</span>
                  {e.sha256 && (
                    <Tooltip content={`sha256 ${e.sha256}`}>
                      <span className="num font-mono text-2xs text-muted">{shortHash(e.sha256, 8)}</span>
                    </Tooltip>
                  )}
                  {run && (
                    <a
                      href={run}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1 text-2xs text-primary hover:underline"
                    >
                      MLflow <ExternalLink className="size-3" />
                    </a>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Block>

      {f.citations.length > 0 && (
        <Block title="Citations">
          <div className="flex flex-wrap gap-1.5">
            {f.citations.map((c, i) => (
              <Badge key={`${c.provision_id}-${i}`} icon={<Scale />}>
                {c.provision_id}
              </Badge>
            ))}
          </div>
        </Block>
      )}

      <Block title={`Annotations${f.annotations.length ? ` · ${f.annotations.length}` : ''}`}>
        <AnnotationThread
          auditId={f.audit_id}
          findingId={f.id}
          annotations={f.annotations}
          canAnnotate={f.sealed}
        />
      </Block>

      {f.sealed && (
        <footer className="num flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border pt-3 font-mono text-2xs text-muted">
          <Lock className="size-3" aria-label="Sealed" />
          <Tooltip content={f.hash}>
            <span>hash {shortHash(f.hash, 12)}</span>
          </Tooltip>
          <span>prev {shortHash(f.prev_hash, 12)}</span>
          {f.kb_version && <span>kb {f.kb_version}</span>}
          {f.created_at && <span className="font-sans">sealed {formatRelative(f.created_at)}</span>}
          <span className="font-sans">by {f.created_by}</span>
          <span className="sr-only">Verdict {v.label}</span>
        </footer>
      )}
    </div>
  );
}
