import { motion } from 'framer-motion';
import {
  ArrowRight,
  ChevronDown,
  FlaskConical,
  Gavel,
  RotateCcw,
  ShieldQuestion,
  Swords,
} from 'lucide-react';
import { useState } from 'react';
import { listItem, staggerList } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import { Badge, KeyValue, Markdown } from '@/shared/ui';
import { TONE_CLASSES, ciCrosses, formatCI, trafficTone, verdictStyle } from '../../lib/styling';
import type { CriticData, Finding, FindingsData, ReportData } from '../../lib/types';
import { CitationChip, ConfidenceBar, DASH, SubHeading, VerdictPill, dash } from './common';

/** Metric value with its CI on a small number line, threshold marked. */
function CIBar({ metric: m }: { metric: NonNullable<Finding['metric']> }) {
  if (m.value == null) {
    return (
      <div className="rounded-lg border border-border bg-surface-muted/30 p-4 text-sm">
        <span className="text-xs text-muted">{m.name}</span> <span className="num">{DASH}</span>
        {m.thresholdText && (
          <span className="ml-2 font-mono text-xs text-muted">threshold {m.thresholdText}</span>
        )}
      </div>
    );
  }
  const metric = { ...m, value: m.value, ci: m.ci ?? ([m.value, m.value] as [number, number]) };
  const lo = Math.min(metric.ci[0], metric.threshold ?? metric.ci[0]);
  const hi = Math.max(metric.ci[1], metric.threshold ?? metric.ci[1]);
  const pad = (hi - lo) * 0.25 || 0.1;
  const min = lo - pad;
  const span = hi + pad - min;
  const pct = (v: number) => `${((v - min) / span) * 100}%`;
  const crosses = metric.threshold != null && ciCrosses(metric.ci, metric.threshold);
  return (
    <div className="rounded-lg border border-border bg-surface-muted/30 p-4">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs text-muted">{metric.name}</span>
        <span className="num text-xl font-semibold tracking-tight">{metric.value.toFixed(2)}</span>
      </div>
      <div className="relative my-4 h-1.5 rounded-full bg-border/60">
        <motion.div
          className={cn('absolute inset-y-0 rounded-full', crosses ? 'bg-warning/70' : 'bg-text/30')}
          initial={{ left: pct(metric.value), right: `calc(100% - ${pct(metric.value)})` }}
          animate={{ left: pct(metric.ci[0]), right: `calc(100% - ${pct(metric.ci[1])})` }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        />
        <span
          className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-text"
          style={{ left: pct(metric.value) }}
        />
        {metric.threshold != null && (
          <span
            className="absolute -top-2 h-[22px] w-0.5 rounded-full bg-danger"
            style={{ left: pct(metric.threshold) }}
            title={`threshold ${metric.threshold}`}
          />
        )}
      </div>
      <div className="num flex flex-wrap justify-between gap-2 text-2xs text-muted">
        <span>
          95% CI{' '}
          <span className="font-mono text-text">{m.ci ? formatCI(m.ci).replace(/^95% CI /, '') : DASH}</span>
        </span>
        {metric.threshold != null && (
          <span className="flex items-center gap-1.5">
            <span className="h-2.5 w-0.5 rounded-full bg-danger" />
            threshold <span className="font-mono text-text">{metric.thresholdText ?? metric.threshold}</span>
            {metric.thresholdSource && <> · {metric.thresholdSource}</>}
          </span>
        )}
      </div>
    </div>
  );
}

export function FindingCard({ f, defaultOpen }: { f: Finding; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <motion.div
      variants={listItem}
      className={cn(
        'overflow-hidden rounded-lg border bg-surface',
        open ? 'border-text/15' : 'border-border',
      )}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start gap-3 p-4 text-left transition-colors hover:bg-surface-muted/40"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="num font-mono text-2xs text-muted">{f.id}</span>
            <VerdictPill verdict={f.verdict} />
            {f.critic?.adjusted && (
              <Badge tone="warning" icon={<RotateCcw />}>
                critic: was {(f.critic.originalVerdict ?? DASH).replace(/_/g, ' ')}
              </Badge>
            )}
            {f.critic?.call && !f.critic.adjusted && <Badge>critic: {f.critic.call}</Badge>}
          </div>
          <div className="mt-1.5 text-sm font-medium">{dash(f.title)}</div>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1">
            <ConfidenceBar value={f.confidence} />
            <span className="font-mono text-2xs text-muted [overflow-wrap:anywhere]">
              {dash(f.requirement)}
            </span>
          </div>
        </div>
        <ChevronDown
          className={cn('mt-1 size-4 shrink-0 text-muted transition-transform', open && 'rotate-180')}
        />
      </button>
      {open && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: 'auto' }}
          className="border-t border-border px-4 pb-4 pt-4"
        >
          {f.metric && <CIBar metric={f.metric} />}
          <SubHeading>Reasoning</SubHeading>
          <p className="text-sm">{dash(f.reasoning)}</p>
          <SubHeading>Evidence</SubHeading>
          {f.evidence.length === 0 && <p className="text-sm text-muted">{DASH}</p>}
          <ul className="space-y-1.5 text-sm">
            {f.evidence.map((e) => (
              <li key={e.text} className="flex gap-2">
                <FlaskConical className="mt-0.5 size-3.5 shrink-0 text-muted" />
                <span className="min-w-0 break-words">
                  {e.text}
                  {e.ci && <span className="ml-1 font-mono text-xs text-muted">{formatCI(e.ci, 3)}</span>}
                  {e.runId && <span className="ml-1 text-xs text-muted">· MLflow run</span>}
                </span>
              </li>
            ))}
          </ul>
          <SubHeading>Counter-evidence</SubHeading>
          {f.counterEvidence.length === 0 && <p className="text-sm text-muted">{DASH}</p>}
          <ul className="space-y-1.5 text-sm">
            {f.counterEvidence.map((c) => (
              <li key={c} className="flex gap-2">
                <Swords className="mt-0.5 size-3.5 shrink-0 text-muted" />
                {c}
              </li>
            ))}
          </ul>
          <SubHeading>Would change if</SubHeading>
          {f.wouldChangeIf.length === 0 && <p className="text-sm text-muted">{DASH}</p>}
          <ul className="space-y-1.5 text-sm">
            {f.wouldChangeIf.map((c) => (
              <li key={c} className="flex gap-2">
                <ShieldQuestion className="mt-0.5 size-3.5 shrink-0 text-muted" />
                {c}
              </li>
            ))}
          </ul>
          {f.critic && (
            <>
              <SubHeading>Critic</SubHeading>
              <p className="text-sm text-muted">{dash(f.critic.note)}</p>
            </>
          )}
          {f.limitations && f.limitations.length > 0 && (
            <>
              <SubHeading>Limitations</SubHeading>
              <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
                {f.limitations.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
            </>
          )}
          <SubHeading>Sources</SubHeading>
          {f.citations.length === 0 && <p className="text-sm text-muted">{DASH}</p>}
          <div className="flex flex-wrap gap-1.5">
            {f.citations.map((c) => (
              <CitationChip key={c.provision} c={c} />
            ))}
          </div>
        </motion.div>
      )}
    </motion.div>
  );
}

export function FindingsView({ data }: { data: FindingsData }) {
  if (data.findings.length === 0) return <p className="text-sm text-muted">No findings {DASH}</p>;
  const counts = data.findings.reduce<Record<string, number>>(
    (m, f) => ({ ...m, [f.verdict]: (m[f.verdict] ?? 0) + 1 }),
    {},
  );
  return (
    <div>
      <div className="mb-4 flex h-1.5 overflow-hidden rounded-full" aria-label="Verdict mix">
        {data.findings.map((f) => (
          <span
            key={f.id}
            title={`${f.id}: ${f.verdict.replace(/_/g, ' ')}`}
            className={cn(
              'h-full flex-1 border-r-2 border-surface last:border-r-0',
              TONE_CLASSES[verdictStyle(f.verdict).tone].bg,
            )}
          />
        ))}
      </div>
      <p className="sr-only">
        {Object.entries(counts)
          .map(([v, n]) => `${n} ${v.replace(/_/g, ' ')}`)
          .join(', ')}
      </p>
      <motion.div variants={staggerList(0.05)} initial="initial" animate="animate" className="space-y-2">
        {data.findings.map((f, i) => (
          <FindingCard key={f.id} f={f} defaultOpen={i === 0} />
        ))}
      </motion.div>
    </div>
  );
}

const OUTCOME = { upheld: 'success', weakened: 'warning', overturned: 'danger' } as const;

export function CriticView({ data }: { data: CriticData }) {
  return (
    <div>
      <p className="mb-4 flex gap-2 rounded-lg border border-border bg-surface-muted/40 p-3 text-sm">
        <Gavel className="mt-0.5 size-4 shrink-0 text-muted" />
        {dash(data.summary)}
      </p>
      <motion.ul variants={staggerList(0.07)} initial="initial" animate="animate" className="space-y-2">
        {data.reviews.map((r) => (
          <motion.li
            key={r.findingId}
            variants={listItem}
            className="rounded-lg border border-border p-3 text-sm"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-xs text-muted">{r.findingId}</span>
              <Badge tone={OUTCOME[r.outcome as keyof typeof OUTCOME] ?? 'neutral'}>{r.outcome}</Badge>
              {r.newVerdict && (
                <span className="inline-flex items-center gap-1 text-xs">
                  <ArrowRight className="size-3" /> <VerdictPill verdict={r.newVerdict} />
                </span>
              )}
              <span className="ml-auto font-mono text-xs text-muted">
                {r.confidenceDelta != null
                  ? `confidence ${r.confidenceDelta > 0 ? '+' : ''}${Math.round(r.confidenceDelta * 100)} pts`
                  : `confidence ${r.newConfidence != null ? `${Math.round(r.newConfidence * 100)}%` : DASH}`}
              </span>
            </div>
            <div className="mt-1 font-medium">{dash(r.challenge)}</div>
            {r.attempt && <div className="break-words text-muted">{r.attempt}</div>}
          </motion.li>
        ))}
      </motion.ul>
    </div>
  );
}

export function ReportView({ data }: { data: ReportData }) {
  return (
    <div>
      {data.traffic && (
        <motion.div
          variants={staggerList(0.06)}
          initial="initial"
          animate="animate"
          className="mb-4 grid gap-2"
        >
          {data.traffic.map((t) => {
            const tone = TONE_CLASSES[trafficTone(t.light)];
            return (
              <motion.div
                key={t.requirement}
                variants={listItem}
                className="flex items-center gap-3 rounded-lg border border-border p-3"
              >
                <span className={cn('size-2.5 shrink-0 rounded-full', tone.bg)} />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">
                    {t.title && <>{t.title} </>}
                    <span className="font-mono text-xs text-muted [overflow-wrap:anywhere]">
                      {t.requirement}
                    </span>
                  </div>
                  <div className="text-xs text-muted">{dash(t.note)}</div>
                </div>
                <span className={cn('text-xs font-semibold uppercase', tone.text)}>{t.light}</span>
              </motion.div>
            );
          })}
        </motion.div>
      )}
      {data.audience === 'management' && data.title && (
        <p className="mb-4 text-base font-semibold">{data.title}</p>
      )}
      {data.markdown ? (
        <Markdown>{data.markdown}</Markdown>
      ) : (
        !data.traffic && <p className="text-sm text-muted">{DASH}</p>
      )}
      {data.decisions && data.decisions.length > 0 && (
        <>
          <SubHeading>Decisions needed</SubHeading>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {data.decisions.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </>
      )}
      {data.nextSteps && data.nextSteps.length > 0 && (
        <>
          <SubHeading>Next steps</SubHeading>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {data.nextSteps.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </>
      )}
      {data.reproducibility && (
        <>
          <SubHeading>Reproducibility</SubHeading>
          <KeyValue
            items={[
              { label: 'kb_version', value: data.reproducibility.kbVersion, mono: true },
              { label: 'card_version', value: String(data.reproducibility.cardVersion), mono: true },
              { label: 'Seeds', value: data.reproducibility.seeds.join(', '), mono: true },
              { label: 'MLflow runs', value: `${data.reproducibility.mlflowRuns.length} runs` },
            ]}
          />
        </>
      )}
    </div>
  );
}
