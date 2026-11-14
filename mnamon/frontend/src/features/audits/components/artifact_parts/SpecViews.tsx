import { motion } from 'framer-motion';
import { AlertTriangle, ArrowRight, Check, ShieldAlert, X } from 'lucide-react';
import { useState } from 'react';
import { color } from '@/shared/lib/consts/ui';
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
  provenanceStyle,
} from '../../lib/styling';
import type { DatasetAnalysisData, DatasetData, GenerationSpecData, Provenance } from '../../lib/types';
import { DASH, SimpleTable, SubHeading, dash } from './common';

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
              p === 'business_rule' && 'border-info/60 bg-info/5',
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
  const llm = data.assumptions.filter((a) => a.provenance === 'llm_assumption');
  const sourced = data.assumptions.filter((a) => a.provenance !== 'llm_assumption');
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-2">
        {(Object.keys(PROVENANCE) as Provenance[]).map((p) => (
          <Badge key={p} tone={PROVENANCE[p].tone}>
            {PROVENANCE[p].label}
          </Badge>
        ))}
      </div>
      {data.problems && data.problems.length > 0 && (
        <div className="mb-4 rounded-lg border border-danger/40 bg-danger/[0.06] p-3 text-sm">
          <div className="mb-1 flex items-center gap-2 font-medium text-danger">
            <X className="size-4" /> Spec problems
          </div>
          <ul className="space-y-0.5 break-words">
            {data.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}
      {llm.length > 0 && (
        <div className="mb-4 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
          <div className="mb-1 flex items-center gap-2 font-medium text-warning">
            <AlertTriangle className="size-4" /> {llm.length} LLM assumption
            {llm.length > 1 ? 's' : ''} to check
          </div>
          <ul className="space-y-0.5">
            {llm.map((a) => (
              <li key={a.field} className="break-words">
                <span className="font-mono text-xs">{a.field}</span> · {dash(a.what)}
              </li>
            ))}
          </ul>
        </div>
      )}
      {sourced.length > 0 && (
        <>
          <SubHeading>Sourced values</SubHeading>
          <ul className="mb-4 space-y-1 text-sm">
            {sourced.map((a) => (
              <li key={a.field} className="flex flex-wrap items-center gap-2 break-words">
                <Badge tone={provenanceStyle(a.provenance).tone}>{provenanceStyle(a.provenance).label}</Badge>
                <span className="font-mono text-xs">{a.field}</span>
                <span className="text-muted">{dash(a.what)}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      {data.rationale && <p className="mb-4 text-sm text-muted">{data.rationale}</p>}
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
              <Badge tone={provenanceStyle(d.provenance).tone}>{provenanceStyle(d.provenance).label}</Badge>,
            ])}
          />
        </>
      )}
      <SubHeading>
        {data.testSpec ?? DASH} GenerationSpec{data.mode ? ` · ${data.mode}` : ''}
      </SubHeading>
      {data.yaml ? <ProvenanceYaml yaml={data.yaml} /> : <p className="text-sm text-muted">{DASH}</p>}
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
  if (coverage.rows.length === 0) return <p className="text-sm text-muted">{DASH}</p>;
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
                const n = coverage.counts[i]?.[j] ?? 0;
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
                        style={{ background: color('primary', 0.06 + 0.4 * (n / max)) }}
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
  const [picked, setMode] = useState<string | null>(null);
  const mode = picked ?? data.twinModes.find((t) => t.mode === 'b')?.mode ?? data.twinModes[0]?.mode ?? 'b';
  if (data.twinModes.length === 0 && data.twins.length === 0)
    return <p className="text-sm text-muted">{DASH}</p>;
  const pairs = data.twins.filter((t) => t.mode === mode);
  const m = data.twinModes.find((x) => x.mode === mode);
  return (
    <div>
      <div className="grid gap-2 sm:grid-cols-3">
        {data.twinModes.map((t) => {
          const strong = t.ci != null && (t.ci[1] < 0 || t.ci[0] > 0);
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
                {t.ci == null ? null : strong ? (
                  <Badge tone="danger">effect</Badge>
                ) : (
                  <Badge>no effect</Badge>
                )}
              </div>
              <div className="mt-1 text-sm font-medium">{t.label}</div>
              <div className="text-xs text-muted">{dash(t.description)}</div>
              {t.meanDelta != null || t.flipRate != null ? (
                <div className="num mt-3 flex items-baseline gap-3">
                  <span className={cn('text-lg font-semibold', strong && 'text-danger')}>
                    {t.meanDelta != null ? t.meanDelta.toFixed(3) : DASH}
                  </span>
                  <span className="text-xs text-muted">
                    Δ score · {t.flipRate != null ? `${Math.round(t.flipRate * 100)}%` : DASH} flip
                  </span>
                </div>
              ) : (
                <div className="num mt-3 flex items-baseline gap-3">
                  <span className="text-lg font-semibold">
                    {t.pairs != null ? t.pairs.toLocaleString() : DASH}
                  </span>
                  <span className="text-xs text-muted">
                    pairs{t.validShare != null && ` · ${Math.round(t.validShare * 100)}% valid`}
                  </span>
                </div>
              )}
              {t.ci && <div className="num font-mono text-2xs text-muted">{formatCI(t.ci, 3)}</div>}
            </button>
          );
        })}
      </div>
      <div className="mt-3 space-y-3">
        {pairs.length === 0 && (
          <p className="text-sm text-muted">
            {data.twins.length === 0
              ? 'Score deltas per pair come from the test run.'
              : 'No sample pairs shown for this mode.'}
          </p>
        )}
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
        <span className="num font-mono text-2xs text-muted [overflow-wrap:anywhere]">{dash(data.name)}</span>
        <Badge>{data.rows != null ? data.rows.toLocaleString() : DASH} rows</Badge>
        <Badge>{data.pairs != null ? data.pairs.toLocaleString() : DASH} pairs</Badge>
        <Badge tone={gateTone(overall)} icon={overall === 'fail' ? <ShieldAlert /> : undefined}>
          gates: {overall}
        </Badge>
      </div>
      <SubHeading>Validation gates</SubHeading>
      <GateCards gates={data.gates} />
      <SubHeading>Coverage{data.coverage.label ? `: ${data.coverage.label}` : ''}</SubHeading>
      <CoverageHeatmap coverage={data.coverage} />
      <SubHeading>Counterfactual twins</SubHeading>
      <TwinPairViewer data={data} />
      <SubHeading>Limitations</SubHeading>
      {data.limitations.length === 0 && <p className="text-sm text-muted">{DASH}</p>}
      <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
        {data.limitations.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </div>
  );
}

/** The generated dataset (generate_data): Data Card summary and a few sample rows. */
export function DatasetView({ data }: { data: DatasetData }) {
  return (
    <div>
      {data.problems.length > 0 && (
        <div className="mb-4 rounded-lg border border-danger/40 bg-danger/[0.06] p-3 text-sm text-danger">
          <div className="font-medium">{data.status ?? 'problems'}</div>
          <ul className="break-words">
            {data.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
        <span className="num font-mono text-2xs text-muted [overflow-wrap:anywhere]">{dash(data.name)}</span>
        <Badge>{data.rows != null ? data.rows.toLocaleString() : DASH} rows</Badge>
        {data.mode && <Badge>{data.mode}</Badge>}
        {data.method && <Badge>{data.method}</Badge>}
        {data.seed != null && <Badge>seed {data.seed}</Badge>}
      </div>
      <SubHeading>Composition</SubHeading>
      <div className="flex flex-wrap gap-1.5">
        {Object.keys(data.byTest).length === 0 && <span className="text-sm text-muted">{DASH}</span>}
        {Object.entries(data.byTest).map(([k, n]) => (
          <Badge key={k}>
            {k} · {n.toLocaleString()}
          </Badge>
        ))}
        {Object.entries(data.twinsByMode).map(([k, n]) => (
          <Badge key={k} tone="primary">
            twins {k.replace(/_/g, ' ')} · {n.toLocaleString()}
          </Badge>
        ))}
      </div>
      {data.population.length > 0 && (
        <>
          <SubHeading>Population vs training-data.md</SubHeading>
          <SimpleTable
            head={['Statistic', 'Stated', 'Observed', '']}
            rows={data.population.map((p) => [
              <span className="font-mono text-xs">{p.stat}</span>,
              <span className="num">{dash(p.stated)}</span>,
              <span className="num">{dash(p.observed)}</span>,
              p.ok == null ? (
                DASH
              ) : p.ok ? (
                <Badge tone="success">within tolerance</Badge>
              ) : (
                <Badge tone="warning">off</Badge>
              ),
            ])}
          />
        </>
      )}
      {data.sample.rows.length > 0 && (
        <>
          <SubHeading>Sample rows</SubHeading>
          <SimpleTable
            head={data.sample.columns}
            rows={data.sample.rows.map((r) =>
              data.sample.columns.map((c) => (
                <span className="whitespace-nowrap font-mono text-xs">{r[c]}</span>
              )),
            )}
          />
        </>
      )}
      <SubHeading>Limitations</SubHeading>
      {data.limitations.length === 0 && <p className="text-sm text-muted">{DASH}</p>}
      <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
        {data.limitations.map((l) => (
          <li key={l}>{l}</li>
        ))}
      </ul>
    </div>
  );
}
