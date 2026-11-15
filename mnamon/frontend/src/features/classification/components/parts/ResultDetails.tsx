import {
  AlertTriangle,
  BookOpen,
  CalendarClock,
  Check,
  CircleHelp,
  ListTodo,
  Minus,
  Scale,
  ShieldAlert,
  Swords,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';
import { Badge, Tooltip } from '@/shared/ui';
import {
  citationFlags,
  conditionLabel,
  irisLabel,
  pct,
  provisionLabel,
  riskLabel,
} from '../../lib/classification';
import type { ClassificationResult, Screening } from '../../lib/types';

/** A titled block of the proposal. */
export function Block({
  title,
  icon,
  children,
  className,
  aside,
}: {
  title: string;
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
  aside?: ReactNode;
}) {
  return (
    <section className={cn('min-w-0 rounded-lg border border-border p-4', className)}>
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <h4 className="flex items-center gap-1.5 text-2xs font-semibold uppercase tracking-wider text-muted [&_svg]:size-3.5">
          {icon}
          {title}
        </h4>
        {aside}
      </div>
      {children}
    </section>
  );
}

function Provision({ id }: { id: string }) {
  const label = provisionLabel(id);
  return (
    <span className="inline-flex min-w-0 flex-wrap items-baseline gap-x-1.5">
      <span className="font-medium">{label}</span>
      {label !== id && <span className="font-mono text-2xs text-muted [overflow-wrap:anywhere]">{id}</span>}
    </span>
  );
}

/** One screened provision: applies (✓) or not (–), and why. `danger`: applying is bad news. */
function ScreeningList({ items, empty, danger }: { items: Screening[]; empty: string; danger?: boolean }) {
  if (!items.length) return <p className="text-sm text-muted">{empty}</p>;
  return (
    <ul className="space-y-2.5">
      {items.map((s) => (
        <li key={s.provision_id} className="flex gap-2.5 text-sm">
          <span
            className={cn(
              'mt-0.5 grid size-4 shrink-0 place-items-center rounded-full [&_svg]:size-3',
              s.applies
                ? danger
                  ? 'bg-danger/15 text-danger'
                  : 'bg-primary/15 text-primary'
                : 'bg-surface-muted text-muted',
            )}
            aria-label={s.applies ? 'Applies' : 'Does not apply'}
            role="img"
          >
            {s.applies ? <Check /> : <Minus />}
          </span>
          <div className="min-w-0">
            <Provision id={s.provision_id} />
            {s.why && <p className="mt-0.5 text-xs leading-5 text-muted">{s.why}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

function Art63Block({ r }: { r: ClassificationResult }) {
  const a = r.art6_3;
  const verdict = !a?.considered
    ? { label: 'Not considered', tone: 'neutral' as const }
    : a.holds === true
      ? { label: 'Holds', tone: 'success' as const }
      : a.holds === false
        ? { label: 'Does not hold', tone: 'danger' as const }
        : { label: 'Open', tone: 'warning' as const };
  return (
    <Block
      title="Art. 6(3) derogation"
      icon={<Scale />}
      aside={<Badge tone={verdict.tone}>{verdict.label}</Badge>}
    >
      {a?.considered ? (
        <div className="space-y-2 text-sm">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
            <dt className="text-muted">Condition</dt>
            <dd>{conditionLabel(a.condition)}</dd>
            <dt className="text-muted">Profiling</dt>
            <dd className={cn(a.profiling === 'yes' && 'font-medium text-danger')}>
              {a.profiling === 'yes'
                ? 'Yes: the derogation can never apply'
                : a.profiling === 'no'
                  ? 'No'
                  : 'Not established'}
            </dd>
          </dl>
          {a.why && <p className="text-xs leading-5 text-muted">{a.why}</p>}
        </div>
      ) : (
        <p className="text-sm text-muted">Not an Annex III system, so the derogation does not arise.</p>
      )}
    </Block>
  );
}

function TransparencyBlock({ r }: { r: ClassificationResult }) {
  const t = r.transparency;
  const g = r.gpai;
  return (
    <Block title="Transparency and GPAI" icon={<BookOpen />}>
      <div className="space-y-2.5 text-sm">
        <div>
          <div className="text-xs text-muted">Art. 50 duties</div>
          {t?.provisions?.length ? (
            <div className="mt-1 flex flex-wrap gap-1">
              {t.provisions.map((p) => (
                <Badge key={p} tone="warning">
                  {provisionLabel(p)}
                </Badge>
              ))}
            </div>
          ) : (
            <div className="mt-0.5">None</div>
          )}
        </div>
        <div>
          <div className="text-xs text-muted">General-purpose AI</div>
          <div className="mt-0.5">
            {g?.is_gpai_model ? 'Is a GPAI model' : g?.built_on_gpai ? 'Built on a GPAI model' : 'No'}
            {g?.note && <span className="text-xs text-muted"> · {g.note}</span>}
          </div>
        </div>
      </div>
    </Block>
  );
}

/** The independent check: Iris's choice, its probability and whether it agrees. */
export function IrisLine({ r }: { r: ClassificationResult }) {
  if (!r.iris) {
    return (
      <span className="inline-flex items-center gap-1.5 text-sm text-muted">
        <Badge tone="warning">Unavailable</Badge>
        independent check not run
      </span>
    );
  }
  const p = r.iris.probabilities?.[r.iris.choice] ?? r.iris.confidence;
  const probs = Object.entries(r.iris.probabilities ?? {}).sort((a, b) => b[1] - a[1]);
  const line = (
    <span className="inline-flex flex-wrap items-center gap-1.5 text-sm">
      <Badge tone={r.agreement ? 'success' : 'danger'} icon={r.agreement ? <Check /> : <AlertTriangle />}>
        {r.agreement ? 'Agrees' : 'Disagrees'}
      </Badge>
      <span>{irisLabel(r.iris.choice)}</span>
      <span className="num text-xs text-muted">p {pct(p)}</span>
    </span>
  );
  if (!probs.length) return line;
  return (
    <Tooltip
      content={
        <span className="num block space-y-0.5 text-xs">
          {probs.map(([k, v]) => (
            <span key={k} className="flex justify-between gap-4">
              <span>{irisLabel(k)}</span>
              <span>{pct(v)}</span>
            </span>
          ))}
        </span>
      }
    >
      <span className="inline-flex cursor-help" tabIndex={0}>
        {line}
      </span>
    </Tooltip>
  );
}

const ASK_LABEL: Record<string, string> = {
  PM: 'Ask the PM',
  legal: 'Ask legal',
  engineer: 'Ask the engineer',
};

/** Everything the classifier returned, in reading order: why, what could overturn it, what to do. */
export function ResultDetails({ r }: { r: ClassificationResult }) {
  return (
    <div className="space-y-4">
      {r.reasoning && (
        <div>
          <h4 className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-muted">Reasoning</h4>
          <p className="max-w-3xl text-sm leading-relaxed">{r.reasoning}</p>
          {r.role_reasoning && (
            <p className="mt-2 max-w-3xl text-sm leading-relaxed text-muted">
              <span className="font-medium text-text">Role: </span>
              {r.role_reasoning}
            </p>
          )}
        </div>
      )}

      <div className="grid gap-3 lg:grid-cols-2">
        <Art63Block r={r} />
        <Block title="Annex III areas considered" icon={<ListTodo />}>
          <ScreeningList items={r.annex_iii_considered} empty="No Annex III area came up." />
        </Block>
        <Block title="Art. 5 screening" icon={<ShieldAlert />}>
          <ScreeningList items={r.art5_screening} empty="No prohibited practice flagged." danger />
        </Block>
        <TransparencyBlock r={r} />
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Block title="Counter-arguments" icon={<Swords />}>
          <ul className="space-y-2.5">
            {r.counter_arguments.map((c, i) => (
              <li key={i} className="text-sm">
                <p className="leading-5">{c.argument}</p>
                {c.would_change_to && (
                  <p className="mt-1 text-xs text-muted">
                    Would make it{' '}
                    <Badge tone={riskLabel(c.would_change_to).tone}>
                      {riskLabel(c.would_change_to).label}
                    </Badge>
                  </p>
                )}
              </li>
            ))}
            {r.counter_arguments.length === 0 && <li className="text-sm text-muted">None given.</li>}
          </ul>
          {r.would_change_if.length > 0 && (
            <>
              <h5 className="mb-1.5 mt-4 text-xs font-medium text-muted">The answer changes if</h5>
              <ul className="list-disc space-y-1 pl-4 text-sm marker:text-muted">
                {r.would_change_if.map((w, i) => (
                  <li key={i}>{w}</li>
                ))}
              </ul>
            </>
          )}
        </Block>

        <Block title="Open questions" icon={<CircleHelp />}>
          {r.uncertainties.length ? (
            <ul className="space-y-2.5">
              {r.uncertainties.map((u, i) => (
                <li key={i} className="text-sm">
                  <div className="flex items-start justify-between gap-2">
                    <p className="leading-5">{u.question}</p>
                    <Badge tone="info" className="shrink-0">
                      {ASK_LABEL[u.ask] ?? `Ask ${u.ask}`}
                    </Badge>
                  </div>
                  {u.why_it_matters && <p className="mt-0.5 text-xs text-muted">{u.why_it_matters}</p>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted">None: the dossier answered every question.</p>
          )}
        </Block>
      </div>

      {(r.next_steps.length > 0 || r.key_dates.length > 0) && (
        <div className="grid gap-3 lg:grid-cols-2">
          {r.next_steps.length > 0 && (
            <Block title="Next steps" icon={<ListTodo />}>
              <ol className="list-decimal space-y-1 pl-4 text-sm marker:text-muted">
                {r.next_steps.map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ol>
            </Block>
          )}
          {r.key_dates.length > 0 && (
            <Block title="Key dates" icon={<CalendarClock />}>
              <ul className="divide-y divide-border">
                {r.key_dates.map((d, i) => (
                  <li
                    key={i}
                    className="flex items-start justify-between gap-3 py-1.5 text-sm first:pt-0 last:pb-0"
                  >
                    <span className="min-w-0">
                      {d.what}
                      {d.amended_by && (
                        <span className="block text-2xs text-muted">
                          as amended by {provisionLabel(d.amended_by)}
                        </span>
                      )}
                    </span>
                    <span className="num shrink-0 font-mono text-xs">{d.date}</span>
                  </li>
                ))}
              </ul>
            </Block>
          )}
        </div>
      )}

      <Block title={`Citations (${r.citations.length})`} icon={<BookOpen />}>
        {r.citations.length ? (
          <ul className="space-y-3">
            {r.citations.map((c) => {
              const f = citationFlags(c);
              return (
                <li key={c.id} className="text-sm">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Provision id={c.id} />
                    {!f.binding && <Badge>Non-binding guidance</Badge>}
                    {f.draft && <Badge tone="warning">Draft</Badge>}
                    {c.kb_version && (
                      <span className="num font-mono text-2xs text-muted">kb {c.kb_version}</span>
                    )}
                  </div>
                  {c.quote && (
                    <blockquote className="mt-1 border-l-2 border-primary/40 pl-2.5 text-xs leading-5 text-muted">
                      {c.quote}
                    </blockquote>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-muted">No citations.</p>
        )}
      </Block>
    </div>
  );
}
