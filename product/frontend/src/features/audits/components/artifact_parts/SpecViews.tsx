import { motion } from 'framer-motion';
import { AlertTriangle, ArrowRight, Check, ShieldAlert, X } from 'lucide-react';
import { useState } from 'react';
import { listItem, staggerList } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';
import { Badge, Tooltip } from '@/shared/ui';
import {
  GATE_LABELS,
  GATE_ORDER,
  PROVENANCE,
  TONE_CLASSES,
  formatCI,
  gateTone,
  overallGateStatus,
  provenanceOfLine,
} from '../../lib/styling';
import type { DatasetAnalysisData, GenerationSpecData, Provenance } from '../../lib/types';
import { MemoryChips, SimpleTable, SubHeading } from './common';

/** YAML with each `provenance:` block tinted; llm_assumption blocks in amber. */
export function ProvenanceYaml({ yaml }: { yaml: string }) {
  const lines = yaml.replace(/\n$/, '').split('\n');
  // A node's provenance tag sits at the end of its block: tint the whole block (same indent run).
  const tags: (Provenance | null)[] = lines.map(() => null);
  for (let i = 0; i < lines.length; i++) {
    const p = provenanceOfLine(lines[i]);
    if (!p) continue;
    const indent = lines[i].search(/\S/);
    let j = i;
    while (j > 0 && lines[j - 1].search(/\S/) >= indent) j--;
    if (j > 0) j--; // include the node key line
    for (let k = j; k <= i; k++) tags[k] = p;
  }
  return (
    <div className="overflow-x-auto rounded-lg border border-border bg-surface-muted/40 py-2 font-mono text-xs leading-5">
      {lines.map((l, i) => {
        const p = tags[i];
        const comment = l.indexOf('#');
        return (
          <div
            key={i}
            className={cn(
              'flex whitespace-pre border-l-2 border-transparent pl-2 pr-3',
              p === 'llm_assumption' && 'border-warning bg-warning/10',
              p === 'memory' && 'border-info/60 bg-info/5',
            )}
          >
            <span className="mr-3 w-6 shrink-0 select-none text-right text-muted/60">{i + 1}</span>
            {comment >= 0 ? (
              <>
                <span>{l.slice(0, comment)}</span>
                <span className="italic text-muted">{l.slice(comment)}</span>
              </>
            ) : (
              <span>{l}</span>
            )}
            {provenanceOfLine(l) && (
              <span className="ml-auto pl-3">
                <Badge tone={PROVENANCE[provenanceOfLine(l)!].tone}>
                  {PROVENANCE[provenanceOfLine(l)!].label}
                </Badge>
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}

export function GenerationSpecView({ data }: { data: GenerationSpecData }) {
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        {(Object.keys(PROVENANCE) as Provenance[]).map((p) => (
          <Badge key={p} tone={PROVENANCE[p].tone}>
            {PROVENANCE[p].label}
          </Badge>
        ))}
      </div>
      {data.assumptions.length > 0 && (
        <div className="mb-4 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
          <div className="mb-1 flex items-center gap-2 font-medium text-warning">
            <AlertTriangle className="size-4" /> {data.assumptions.length} LLM assumption
            {data.assumptions.length > 1 ? 's' : ''} to check
          </div>
          <ul className="space-y-0.5">
            {data.assumptions.map((a) => (
              <li key={a.field}>
                <span className="font-mono text-xs">{a.field}</span> · {a.what}
              </li>
            ))}
          </ul>
        </div>
      )}
      {data.diff && data.diff.length > 0 && (
        <>
          <SubHeading>Diff vs the last approved spec</SubHeading>
          <SimpleTable
            className="mb-4"
            head={['Field', 'Change', 'Source']}
            rows={data.diff.map((d) => [
              <span className="font-mono text-xs">{d.field}</span>,
              <span className="flex flex-wrap items-center gap-1.5 font-mono text-xs">
                <span className="text-danger line-through">{d.before}</span>
                <ArrowRight className="size-3 text-muted" />
                <span className="text-success">{d.after}</span>
              </span>,
              <Badge tone={PROVENANCE[d.provenance].tone}>{PROVENANCE[d.provenance].label}</Badge>,
            ])}
          />
        </>
      )}
      <SubHeading>{data.testSpec} GenerationSpec</SubHeading>
      <ProvenanceYaml yaml={data.yaml} />
    </div>
  );
}

const GATE_ICON = { pass: Check, warn: AlertTriangle, fail: X };

export function GateCards({ gates }: { gates: DatasetAnalysisData['gates'] }) {
  return (
    <motion.div
      variants={staggerList(0.09)}
      initial="initial"
      animate="animate"
      className="grid grid-cols-2 gap-2 sm:grid-cols-5"
    >
      {GATE_ORDER.map((g) => {
        const r = gates[g];
        const status = r?.status ?? 'fail';
        const tone = TONE_CLASSES[gateTone(status)];
        const Icon = GATE_ICON[status];
        return (
          <motion.div key={g} variants={listItem}>
            <Tooltip
              content={
                <div className="max-w-xs space-y-1 text-xs">
                  <div>{GATE_LABELS[g].checks}</div>
                  {r?.metrics &&
                    Object.entries(r.metrics).map(([k, v]) => (
                      <div key={k} className="font-mono">
                        {k}: {String(v)}
                      </div>
                    ))}
                  {r?.note && <div className="italic">{r.note}</div>}
                  <div className="text-muted">On fail: {GATE_LABELS[g].failAction}</div>
                </div>
              }
            >
              <div
                className={cn(
                  'flex h-full flex-col gap-2 rounded-lg border bg-surface p-3',
                  status === 'pass'
                    ? 'border-border'
                    : status === 'warn'
                      ? 'border-warning/50'
                      : 'border-danger/50',
                  status === 'warn' && 'bg-warning/[0.04]',
                  status === 'fail' && 'bg-danger/[0.04]',
                )}
              >
                <div className="flex items-center justify-between">
                  <motion.span
                    initial={{ scale: 0.6, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    transition={{
                      duration: 0.22,
                      ease: [0.16, 1, 0.3, 1],
                      delay: 0.1 + GATE_ORDER.indexOf(g) * 0.06,
                    }}
                    className={cn('grid size-5 place-items-center rounded-full', tone.pill)}
                  >
                    <Icon className="size-3" strokeWidth={2.5} />
                  </motion.span>
                  <span className={cn('text-2xs font-semibold uppercase tracking-wide', tone.text)}>
                    {status}
                  </span>
                </div>
                <div>
                  <div className="text-sm font-medium">{GATE_LABELS[g].label}</div>
                  <div className="mt-0.5 line-clamp-2 text-2xs text-muted">
                    {r?.note ?? GATE_LABELS[g].checks}
                  </div>
                </div>
              </div>
            </Tooltip>
          </motion.div>
        );
      })}
    </motion.div>
  );
}

/** Group × stratum counts; one hue, opacity by count; cells under min_per_cell flagged. */
export function CoverageHeatmap({ coverage }: { coverage: DatasetAnalysisData['coverage'] }) {
  const max = Math.max(...coverage.counts.flat(), 1);
  return (
    <div className="overflow-x-auto">
      <table className="text-xs">
        <thead>
          <tr>
            <th />
            {coverage.cols.map((c) => (
              <th key={c} className="px-1 pb-1.5 text-left font-mono text-2xs font-normal text-muted">
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {coverage.rows.map((r, i) => (
            <tr key={r}>
              <th className="pr-3 text-right font-mono text-2xs font-normal text-muted">{r}</th>
              {coverage.cols.map((c, j) => {
                const n = coverage.counts[i][j];
                const low = n < coverage.minPerCell;
                return (
                  <td key={c} className="p-0.5">
                    <Tooltip
                      content={`${r} × ${c}: ${n} rows${low ? ` (below min ${coverage.minPerCell})` : ''}`}
                    >
                      <motion.div
                        initial={{ opacity: 0, scale: 0.8 }}
                        animate={{ opacity: 1, scale: 1 }}
                        transition={{ delay: (i * coverage.cols.length + j) * 0.03 }}
                        className={cn(
                          'num grid h-9 w-20 place-items-center rounded-md text-xs font-medium',
                          low && 'ring-2 ring-danger',
                        )}
                        style={{ background: `rgb(var(--rgb-primary) / ${0.06 + 0.4 * (n / max)})` }}
                      >
                        {n}
                      </motion.div>
                    </Tooltip>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-2xs text-muted">
        Rows per cell · stronger tint = more rows · cells under min_per_cell ({coverage.minPerCell}) are
        ringed red.
      </p>
    </div>
  );
}

export function TwinPairViewer({ data }: { data: DatasetAnalysisData }) {
  const [mode, setMode] = useState<'a' | 'b' | 'c'>('b');
  const pairs = data.twins.filter((t) => t.mode === mode);
  const m = data.twinModes.find((x) => x.mode === mode);
  return (
    <div>
      <div className="grid gap-2 sm:grid-cols-3">
        {data.twinModes.map((t) => {
          const strong = t.ci[1] < 0 || t.ci[0] > 0;
          return (
            <button
              key={t.mode}
              type="button"
              onClick={() => setMode(t.mode)}
              className={cn(
                'rounded-lg border p-3 text-left transition-colors duration-150',
                mode === t.mode
                  ? 'border-primary/60 bg-primary/[0.04] ring-1 ring-primary/30'
                  : 'border-border hover:border-text/20',
              )}
            >
              <div className="flex items-center justify-between">
                <span className="text-2xs font-medium text-muted">Mode {t.mode}</span>
                {strong ? <Badge tone="danger">effect</Badge> : <Badge>no effect</Badge>}
              </div>
              <div className="mt-1 text-sm font-medium">{t.label}</div>
              <div className="text-xs text-muted">{t.description}</div>
              <div className="num mt-3 flex items-baseline gap-3">
                <span className={cn('text-lg font-semibold', strong && 'text-danger')}>
                  {t.meanDelta.toFixed(3)}
                </span>
                <span className="text-xs text-muted">Δ score · {Math.round(t.flipRate * 100)}% flip</span>
              </div>
              <div className="num font-mono text-2xs text-muted">{formatCI(t.ci, 3)}</div>
            </button>
          );
        })}
      </div>
      <div className="mt-3 space-y-3">
        {pairs.length === 0 && <p className="text-sm text-muted">No sample pairs for mode {mode}.</p>}
        {pairs.map((p) => {
          const keys = Object.keys(p.base);
          return (
            <motion.div
              key={p.pairId}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              className="rounded-lg border border-border"
            >
              <div className="flex items-center justify-between border-b border-border px-3 py-1.5 text-xs text-muted">
                <span className="font-mono">{p.pairId}</span>
                <span>{m?.label}</span>
              </div>
              <div className="grid grid-cols-[auto_1fr_1fr] gap-x-3 gap-y-0.5 px-3 py-2 text-xs">
                <span />
                <span className="font-semibold">Base</span>
                <span className="font-semibold">Twin</span>
                {keys.map((k) => {
                  const changed = p.changed.includes(k) || p.base[k] !== p.twin[k];
                  return [
                    <span key={`${k}-k`} className="font-mono text-muted">
                      {k}
                    </span>,
                    <span key={`${k}-b`} className={cn(changed && 'font-semibold')}>
                      {String(p.base[k])}
                    </span>,
                    <span
                      key={`${k}-t`}
                      className={cn(changed && 'rounded bg-warning/15 px-1 font-semibold text-warning')}
                    >
                      {String(p.twin[k])}
                    </span>,
                  ];
                })}
                <span className="pt-1 font-mono text-muted">score</span>
                <span className="pt-1 font-mono">{p.scoreBase.toFixed(2)}</span>
                <span
                  className={cn(
                    'pt-1 font-mono font-semibold',
                    p.scoreTwin < p.scoreBase - 0.02 ? 'text-danger' : 'text-success',
                  )}
                >
                  {p.scoreTwin.toFixed(2)} (
                  {(p.scoreTwin - p.scoreBase >= 0 ? '+' : '') + (p.scoreTwin - p.scoreBase).toFixed(2)})
                </span>
              </div>
            </motion.div>
          );
        })}
      </div>
    </div>
  );
}

export function DatasetAnalysisView({ data }: { data: DatasetAnalysisData }) {
  const overall = overallGateStatus(data.gates);
  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center gap-2 text-sm">
        <span className="num font-mono text-2xs text-muted">{data.datasetId}</span>
        <Badge>{data.rows.toLocaleString()} rows</Badge>
        <Badge>{data.pairs.toLocaleString()} pairs</Badge>
        <Badge tone={gateTone(overall)} icon={overall === 'fail' ? <ShieldAlert /> : undefined}>
          gates: {overall}
        </Badge>
      </div>
      <SubHeading>Validation gates</SubHeading>
      <GateCards gates={data.gates} />
      <SubHeading>Coverage: nationality × postcode_region</SubHeading>
      <CoverageHeatmap coverage={data.coverage} />
      <SubHeading>Counterfactual twins</SubHeading>
      <TwinPairViewer data={data} />
      <SubHeading>Limitations</SubHeading>
      <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
        {data.limitations.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
      {data.memoryApplied && (
        <>
          <SubHeading>Memory applied</SubHeading>
          <MemoryChips ids={data.memoryApplied} />
        </>
      )}
    </div>
  );
}
