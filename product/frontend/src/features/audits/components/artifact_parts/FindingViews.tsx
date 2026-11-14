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
import { TONE_CLASSES, ciCrosses, formatCI, trafficTone } from '../../lib/styling';
import type { CriticData, Finding, FindingsData, ReportData } from '../../lib/types';
import { CitationChip, ConfidenceBar, MemoryChips, SubHeading, VerdictPill } from './common';

/** Metric value with its CI on a small number line, threshold marked. */
function CIBar({ metric }: { metric: NonNullable<Finding['metric']> }) {
  const lo = Math.min(metric.ci[0], metric.threshold ?? metric.ci[0]);
  const hi = Math.max(metric.ci[1], metric.threshold ?? metric.ci[1]);
  const pad = (hi - lo) * 0.25 || 0.1;
  const min = lo - pad;
  const span = hi + pad - min;
  const pct = (v: number) => `${((v - min) / span) * 100}%`;
  const crosses = metric.threshold != null && ciCrosses(metric.ci, metric.threshold);
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="flex items-baseline justify-between gap-2 text-sm">
        <span className="text-muted">{metric.name}</span>
        <span className="font-mono font-semibold">{metric.value.toFixed(2)}</span>
      </div>
      <div className="relative my-3 h-2 rounded-full bg-surface-muted">
        <motion.div
          className={cn('absolute inset-y-0 rounded-full', crosses ? 'bg-warning/60' : 'bg-primary/50')}
          initial={{ left: pct(metric.value), right: `calc(100% - ${pct(metric.value)})` }}
          animate={{ left: pct(metric.ci[0]), right: `calc(100% - ${pct(metric.ci[1])})` }}
          transition={{ duration: 0.7, ease: [0.16, 1, 0.3, 1] }}
        />
        <span
          className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-surface bg-primary"
          style={{ left: pct(metric.value) }}
        />
        {metric.threshold != null && (
          <span
            className="absolute -top-1.5 h-5 w-0.5 bg-danger"
            style={{ left: pct(metric.threshold) }}
            title={`threshold ${metric.threshold}`}
          />
        )}
      </div>
      <div className="flex flex-wrap justify-between gap-2 text-xs text-muted">
        <span className="font-mono">{formatCI(metric.ci)}</span>
        {metric.threshold != null && (
          <span>
            threshold <span className="font-mono text-danger">{metric.threshold}</span> ·{' '}
            {metric.thresholdSource}
          </span>
        )}
      </div>
    </div>
  );
}

export function FindingCard({ f, defaultOpen }: { f: Finding; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(!!defaultOpen);
  return (
    <motion.div variants={listItem} className="rounded-xl border border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start gap-3 p-4 text-left"
      >
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs text-muted">{f.id}</span>
            <VerdictPill verdict={f.verdict} />
            {f.critic?.adjusted && (
              <Badge tone="warning" icon={<RotateCcw />}>
                critic: was {f.critic.originalVerdict}
              </Badge>
            )}
          </div>
          <div className="mt-1 font-medium">{f.title}</div>
          <div className="mt-1 flex flex-wrap items-center gap-3">
            <ConfidenceBar value={f.confidence} />
            <span className="font-mono text-[11px] text-muted">{f.requirement}</span>
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
          className="space-y-1 border-t border-border px-4 pb-4 pt-3"
        >
          {f.metric && <CIBar metric={f.metric} />}
          <SubHeading>Reasoning</SubHeading>
          <p className="text-sm">{f.reasoning}</p>
          <SubHeading>Evidence</SubHeading>
          <ul className="space-y-1.5 text-sm">
            {f.evidence.map((e) => (
              <li key={e.text} className="flex gap-2">
                <FlaskConical className="mt-0.5 size-4 shrink-0 text-primary" />
                <span>
                  {e.text}
                  {e.ci && <span className="ml-1 font-mono text-xs text-muted">{formatCI(e.ci, 3)}</span>}
                  {e.runId && <span className="ml-1 font-mono text-xs text-muted">· {e.runId}</span>}
                </span>
              </li>
            ))}
          </ul>
          <SubHeading>Counter-evidence</SubHeading>
          <ul className="space-y-1.5 text-sm">
            {f.counterEvidence.map((c) => (
              <li key={c} className="flex gap-2">
                <Swords className="mt-0.5 size-4 shrink-0 text-warning" />
                {c}
              </li>
            ))}
          </ul>
          <SubHeading>Would change if</SubHeading>
          <ul className="space-y-1.5 text-sm">
            {f.wouldChangeIf.map((c) => (
              <li key={c} className="flex gap-2">
                <ShieldQuestion className="mt-0.5 size-4 shrink-0 text-info" />
                {c}
              </li>
            ))}
          </ul>
          {f.critic && (
            <>
              <SubHeading>Critic</SubHeading>
              <p className="text-sm text-muted">{f.critic.note}</p>
            </>
          )}
          <SubHeading>Sources</SubHeading>
          <div className="flex flex-wrap gap-1.5">
            {f.citations.map((c) => (
              <CitationChip key={c.provision} c={c} />
            ))}
          </div>
          {f.memoryApplied && (
            <div className="pt-2">
              <MemoryChips ids={f.memoryApplied} />
            </div>
          )}
        </motion.div>
      )}
    </motion.div>
  );
}

export function FindingsView({ data }: { data: FindingsData }) {
  const counts = data.findings.reduce<Record<string, number>>(
    (m, f) => ({ ...m, [f.verdict]: (m[f.verdict] ?? 0) + 1 }),
    {},
  );
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        {Object.entries(counts).map(([v, n]) => (
          <span key={v} className="inline-flex items-center gap-1.5">
            <VerdictPill verdict={v} />
            <span className="text-sm font-semibold">×{n}</span>
          </span>
        ))}
      </div>
      <motion.div variants={staggerList(0.07)} initial="initial" animate="animate" className="space-y-3">
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
      <p className="mb-3 flex gap-2 rounded-lg border border-border bg-surface-muted/60 p-3 text-sm">
        <Gavel className="mt-0.5 size-4 shrink-0 text-primary" />
        {data.summary}
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
              <Badge tone={OUTCOME[r.outcome]}>{r.outcome}</Badge>
              {r.newVerdict && (
                <span className="inline-flex items-center gap-1 text-xs">
                  <ArrowRight className="size-3" /> <VerdictPill verdict={r.newVerdict} />
                </span>
              )}
              <span className="ml-auto font-mono text-xs text-muted">
                confidence {r.confidenceDelta > 0 ? '+' : ''}
                {Math.round(r.confidenceDelta * 100)} pts
              </span>
            </div>
            <div className="mt-1 font-medium">{r.challenge}</div>
            <div className="text-muted">{r.attempt}</div>
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
                <span className={cn('relative size-4 shrink-0 rounded-full', tone.bg)}>
                  {t.light === 'red' && (
                    <span className={cn('absolute inset-0 animate-ping rounded-full opacity-50', tone.bg)} />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">
                    {t.title} <span className="font-mono text-xs text-muted">{t.requirement}</span>
                  </div>
                  <div className="text-xs text-muted">{t.note}</div>
                </div>
                <span className={cn('text-xs font-semibold uppercase', tone.text)}>{t.light}</span>
              </motion.div>
            );
          })}
        </motion.div>
      )}
      <Markdown>{data.markdown}</Markdown>
      {data.reproducibility && (
        <>
          <SubHeading>Reproducibility</SubHeading>
          <KeyValue
            items={[
              { label: 'kb_version', value: data.reproducibility.kbVersion, mono: true },
              { label: 'card_version', value: String(data.reproducibility.cardVersion), mono: true },
              { label: 'Seeds', value: data.reproducibility.seeds.join(', '), mono: true },
              { label: 'MLflow runs', value: data.reproducibility.mlflowRuns.join(', '), mono: true },
            ]}
          />
        </>
      )}
    </div>
  );
}
