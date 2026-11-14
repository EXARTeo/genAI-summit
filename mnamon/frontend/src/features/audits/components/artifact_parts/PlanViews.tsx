import {
  Brain,
  CheckCircle2,
  CircleDashed,
  Database,
  ExternalLink,
  FileText,
  MinusCircle,
  Plus,
  RefreshCw,
  Star,
} from 'lucide-react';
import { cn } from '@/shared/lib/utils';
import { Badge, KeyValue, Tooltip } from '@/shared/ui';
import type {
  ContextData,
  PublicCandidatesData,
  ScenarioAnalysisData,
  ScenarioReview,
  ScenariosData,
  TestResultsData,
} from '../../lib/types';
import { formatCI } from '../../lib/styling';
import { DASH, SimpleTable, SubHeading, dash } from './common';

export function ContextView({ data }: { data: ContextData }) {
  const s = data.system;
  return (
    <div>
      <KeyValue
        items={[
          { label: 'System', value: [s.id, s.name].filter(Boolean).join(' · ') || DASH },
          { label: 'Risk class', value: [s.riskClass, s.annex].filter(Boolean).join(' · ') || DASH },
          { label: 'Role', value: dash(s.role) },
          { label: 'Intended purpose', value: dash(s.intendedPurpose) },
          ...(data.target ? [{ label: 'Target', value: data.target, mono: true }] : []),
          ...(data.kbVersion ? [{ label: 'kb_version', value: data.kbVersion, mono: true }] : []),
        ]}
      />
      <SubHeading>Applicable requirements ({data.requirements.length})</SubHeading>
      {data.requirements.length === 0 ? (
        <p className="text-sm text-muted">{DASH}</p>
      ) : (
        <SimpleTable
          head={['Requirement', 'Provision', 'Testable']}
          rows={data.requirements.map((r) => [
            <div className="min-w-[14rem]">
              <div className="font-medium">{dash(r.title)}</div>
              <div className="font-mono text-xs text-muted [overflow-wrap:anywhere]">{r.id}</div>
            </div>,
            <span className="whitespace-nowrap font-mono text-xs">{dash(r.provision)}</span>,
            r.testable ? <Badge tone="success">test</Badge> : <Badge>document review</Badge>,
          ])}
        />
      )}
      <SubHeading>Plugins</SubHeading>
      <div className="flex flex-wrap gap-2">
        {data.plugins.length === 0 && <span className="text-sm text-muted">{DASH}</span>}
        {data.plugins.map((p) => (
          <Badge key={p.name} tone="primary">
            {p.name}
            {p.accessType && ` · ${p.accessType}`}
          </Badge>
        ))}
      </div>
      <SubHeading>Files read (pinned versions)</SubHeading>
      {data.filesRead.length === 0 ? (
        <p className="text-sm text-muted">{DASH}</p>
      ) : (
        <ul className="space-y-1 text-xs">
          {data.filesRead.map((f) => (
            <li key={f.path} className="flex min-w-0 items-center gap-2 font-mono">
              <FileText className="size-3 shrink-0 text-muted" />
              <span className="truncate">{f.path}</span>
              <span className="text-muted">{f.version != null ? `v${f.version}` : DASH}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const PRIORITY = { high: 'danger', medium: 'warning', low: 'neutral' } as const;

const REVIEW_TONE = { relevant: 'success', needs_change: 'warning', not_relevant: 'danger' } as const;
const REVIEW_LABEL = {
  relevant: 'relevant',
  needs_change: 'needs change',
  not_relevant: 'not relevant',
} as const;

export function reviewerLabel(model: string): string {
  return model === 'iris' ? 'Iris (Oumi)' : model === 'gemini' ? 'Gemini' : model;
}

/** The scenario judge's verdict: "Reviewed by Iris (Oumi) · needs change". */
export function ReviewBadge({ review, compact }: { review: ScenarioReview; compact?: boolean }) {
  return (
    <Badge tone={REVIEW_TONE[review.verdict]}>
      {compact ? '' : `Reviewed by ${reviewerLabel(review.model)} · `}
      {REVIEW_LABEL[review.verdict]}
      {review.confidence != null && ` · ${Math.round(review.confidence * 100)}%`}
    </Badge>
  );
}

/** Verdict badge plus the rationale and any suggested change. */
export function ReviewNote({ review }: { review: ScenarioReview }) {
  return (
    <div className="space-y-1">
      <ReviewBadge review={review} />
      {review.verdict !== 'relevant' && review.rationale && <div className="text-xs">{review.rationale}</div>}
      {review.suggestedChange && (
        <div className="text-xs text-muted">
          <span className="font-medium text-text">Suggested:</span> {review.suggestedChange}
        </div>
      )}
    </div>
  );
}

/** "Learned from memory": the memory entries a scenario follows. */
export function MemoryCitation({ paths }: { paths: string[] }) {
  if (!paths.length) return null;
  return (
    <Tooltip content={<span className="block max-w-xs font-mono text-2xs">{paths.join('\n')}</span>}>
      <span className="inline-flex">
        <Badge tone="info" icon={<Brain />}>
          learned from memory{paths.length > 1 ? ` (${paths.length})` : ''}
        </Badge>
      </span>
    </Tooltip>
  );
}

export function ScenariosView({ data }: { data: ScenariosData }) {
  return (
    <div>
      {data.scenarios.length === 0 ? (
        <p className="text-sm text-muted">No scenarios {DASH}</p>
      ) : (
        <SimpleTable
          head={['Test', 'Groups', 'N', 'Why']}
          rows={data.scenarios.map((s) => [
            <div className="min-w-[13rem] max-w-[22rem]">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-xs text-muted">{s.id}</span>
                {s.priority && <Badge tone={PRIORITY[s.priority]}>{s.priority}</Badge>}
                {s.metric && <span className="font-mono text-2xs text-muted">{s.metric}</span>}
              </div>
              <div className="font-medium">{dash(s.title)}</div>
              <div className="font-mono text-2xs text-muted [overflow-wrap:anywhere]">
                {dash(s.requirement)}
              </div>
              <div className="font-mono text-2xs text-muted">{dash(s.template)}</div>
            </div>,
            <span className="text-xs">{s.groups.join(', ') || DASH}</span>,
            s.n != null ? s.n.toLocaleString() : DASH,
            <div className="min-w-[11rem] space-y-1.5">
              <div className="text-muted">{dash(s.rationale)}</div>
              {s.review && <ReviewNote review={s.review} />}
              <MemoryCitation paths={s.memoryApplied ?? []} />
              {s.memoryApplied && s.memoryApplied.length > 0 && (
                <ul className="space-y-0.5">
                  {s.memoryApplied.map((m) => (
                    <li key={m} className="font-mono text-2xs text-muted [overflow-wrap:anywhere]">
                      {m}
                    </li>
                  ))}
                </ul>
              )}
            </div>,
          ])}
        />
      )}
      {data.notTestable && data.notTestable.length > 0 && (
        <>
          <SubHeading>Not testable (document review)</SubHeading>
          <div className="flex flex-wrap gap-1.5">
            {data.notTestable.map((r) => (
              <Badge key={r}>
                <span className="font-mono">{r}</span>
              </Badge>
            ))}
          </div>
        </>
      )}
      {data.assumptions && data.assumptions.length > 0 && (
        <>
          <SubHeading>Assumptions</SubHeading>
          <ul className="list-disc space-y-1 pl-5 text-sm text-muted">
            {data.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

const COVERAGE = {
  covered: { icon: <CheckCircle2 className="size-4 shrink-0 text-success" />, label: 'covered' },
  partial: { icon: <CircleDashed className="size-4 shrink-0 text-warning" />, label: 'partial' },
  not_testable: { icon: <MinusCircle className="size-4 shrink-0 text-muted" />, label: 'not testable' },
};

export function ScenarioAnalysisView({ data }: { data: ScenarioAnalysisData }) {
  return (
    <div>
      <p className="rounded-lg border border-border bg-surface-muted/60 p-3 text-sm">{dash(data.summary)}</p>
      {data.attributeCoverage && data.attributeCoverage.length > 0 && (
        <>
          <SubHeading>Attributes covered</SubHeading>
          <div className="flex flex-wrap gap-1.5">
            {data.attributeCoverage.map((a) => (
              <Badge key={`${a.kind}-${a.name}`} tone={a.covered ? 'success' : 'danger'}>
                <span className="font-mono">{a.name}</span> · {a.kind}
              </Badge>
            ))}
          </div>
        </>
      )}
      <SubHeading>Coverage per requirement</SubHeading>
      {data.coverage.length === 0 && <p className="text-sm text-muted">{DASH}</p>}
      <ul className="space-y-2">
        {data.coverage.map((c) => (
          <li key={c.requirement} className="flex items-start gap-2 text-sm">
            {COVERAGE[c.status].icon}
            <div className="min-w-0 flex-1">
              <div className="font-mono text-xs [overflow-wrap:anywhere]">{c.requirement}</div>
              <div className="text-xs text-muted">
                {COVERAGE[c.status].label}
                {c.scenarios.length > 0 && ` · ${c.scenarios.join(', ')}`}
              </div>
            </div>
          </li>
        ))}
      </ul>
      {data.diff && (
        <>
          <SubHeading>Changes vs the last approved plan</SubHeading>
          <ul className="space-y-1 text-sm">
            {data.diff.added.map((d) => (
              <li key={d} className="flex items-center gap-2 text-success">
                <Plus className="size-3.5" /> added {d}
              </li>
            ))}
            {data.diff.removed.map((d) => (
              <li key={d} className="flex items-center gap-2 text-danger">
                <MinusCircle className="size-3.5" /> removed {d}
              </li>
            ))}
            {data.diff.changed.map((d) => (
              <li key={d} className="flex items-center gap-2 text-warning">
                <RefreshCw className="size-3.5" /> {d}
              </li>
            ))}
          </ul>
        </>
      )}
      <SubHeading>Risks and gaps</SubHeading>
      {data.risks.length === 0 ? (
        <p className="text-sm text-muted">{DASH}</p>
      ) : (
        <ul className="list-disc space-y-1 pl-5 text-sm">
          {data.risks.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      {data.notTestable.length > 0 && (
        <>
          <SubHeading>Not assessable by testing</SubHeading>
          <ul className="space-y-1 text-sm">
            {data.notTestable.map((n) => (
              <li key={n.requirement}>
                <span className="font-mono text-xs">{n.requirement}</span>
                {n.why && <span className="text-muted"> · {n.why}</span>}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/** Public dataset candidates; `selected` / `onSelect` turn the list into a picker (gate). */
export function PublicCandidatesView({
  data,
  selected,
  onSelect,
}: {
  data: PublicCandidatesData;
  selected?: string | null;
  onSelect?: (id: string | null) => void;
}) {
  const rec = data.recommendation;
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-start gap-2 rounded-lg border border-border bg-surface-muted/60 p-3 text-sm">
        <Database className="mt-0.5 size-4 shrink-0 text-muted" />
        <div className="min-w-0 flex-1">
          <div className="font-medium">
            Recommendation: {rec.mode === 'reference_sample' ? 'use a reference sample' : dash(rec.mode)}
            {rec.candidate && <span className="font-mono text-xs text-muted"> · {rec.candidate}</span>}
          </div>
          <div className="text-xs text-muted">{dash(rec.reason)}</div>
        </div>
      </div>
      {data.sources.length > 0 && (
        <div className="mb-4 flex flex-wrap gap-1.5">
          {data.sources.map((s) => (
            <Tooltip key={s.name} content={s.error ?? `${s.found ?? 0} found`}>
              <span className="inline-flex">
                <Badge tone={s.ok ? 'neutral' : 'warning'}>
                  {s.name} · {s.ok ? (s.found ?? DASH) : 'skipped'}
                </Badge>
              </span>
            </Tooltip>
          ))}
        </div>
      )}
      {onSelect && (
        <button
          type="button"
          role="radio"
          aria-checked={selected == null}
          onClick={() => onSelect(null)}
          className={cn(
            'mb-2 w-full rounded-lg border p-3 text-left text-sm transition-colors',
            selected == null
              ? 'border-primary/60 bg-primary/[0.04] ring-1 ring-primary/30'
              : 'border-border hover:border-text/25',
          )}
        >
          <div className="font-medium">None: generate zero-shot from the data dictionary</div>
          <div className="text-xs text-muted">No public data is fetched.</div>
        </button>
      )}
      {data.candidates.length === 0 && <p className="text-sm text-muted">No candidates found.</p>}
      <ul className="space-y-2" role={onSelect ? 'radiogroup' : undefined}>
        {data.candidates.map((c) => {
          const on = selected === c.id;
          const body = (
            <>
              <div className="flex flex-wrap items-center gap-2">
                {c.id === rec.candidate && <Star className="size-3.5 text-warning" />}
                <span className="min-w-0 break-words font-medium">{c.name}</span>
                {c.source && <Badge>{c.source}</Badge>}
                {c.licence && (
                  <Badge tone={c.licenceStatus === 'allowed' ? 'success' : 'warning'}>{c.licence}</Badge>
                )}
                {!c.fetchable && <Badge tone="warning">not fetchable</Badge>}
                <span className="num ml-auto font-mono text-xs">
                  score {c.score != null ? c.score.toFixed(2) : DASH}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted">
                <span className="num">
                  {c.rows != null ? `${c.rows.toLocaleString()} rows` : `rows ${DASH}`}
                </span>
                {c.task && <span>task {c.task}</span>}
                <span>mapped: {c.mapped.join(', ') || DASH}</span>
                {c.missingProtected.length > 0 && (
                  <span>missing protected: {c.missingProtected.join(', ')}</span>
                )}
              </div>
              {c.description && <p className="mt-1 line-clamp-2 text-xs text-muted">{c.description}</p>}
              {c.url && (
                <a
                  href={c.url}
                  target="_blank"
                  rel="noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="mt-1 inline-flex items-center gap-1 text-xs text-muted hover:text-primary"
                >
                  {c.id} <ExternalLink className="size-3" />
                </a>
              )}
            </>
          );
          return (
            <li key={c.id}>
              {onSelect ? (
                <div
                  role="radio"
                  tabIndex={0}
                  aria-checked={on}
                  aria-disabled={!c.fetchable}
                  onClick={() => c.fetchable && onSelect(c.id)}
                  onKeyDown={(e) => {
                    if ((e.key === 'Enter' || e.key === ' ') && c.fetchable) {
                      e.preventDefault();
                      onSelect(c.id);
                    }
                  }}
                  className={cn(
                    'cursor-pointer rounded-lg border p-3 text-sm transition-colors',
                    on
                      ? 'border-primary/60 bg-primary/[0.04] ring-1 ring-primary/30'
                      : 'border-border hover:border-text/25',
                    !c.fetchable && 'cursor-not-allowed opacity-60',
                  )}
                >
                  {body}
                </div>
              ) : (
                <div className="rounded-lg border border-border p-3 text-sm">{body}</div>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export function TestResultsView({ data }: { data: TestResultsData }) {
  return (
    <div>
      {data.error && (
        <p className="mb-3 rounded-lg border border-danger/40 bg-danger/[0.06] p-3 text-sm text-danger">
          {data.error}
        </p>
      )}
      {data.summary && (
        <div className="mb-3 flex flex-wrap gap-2">
          <Badge>{dash(data.summary.runs)} runs</Badge>
          <Badge tone="success">{dash(data.summary.passed)} passed</Badge>
          <Badge tone={data.summary.failed ? 'danger' : 'neutral'}>{dash(data.summary.failed)} failed</Badge>
        </div>
      )}
      {data.tests.length === 0 && !data.summary && <p className="text-sm text-muted">No test rows {DASH}</p>}
      {data.tests.length > 0 && (
        <SimpleTable
          head={['Test', 'Metric', 'Value', 'Threshold', 'Status']}
          rows={data.tests.map((t) => [
            <div className="min-w-[10rem]">
              <div className="font-mono text-xs">{dash(t.testId ?? t.id)}</div>
              <div className="font-mono text-2xs text-muted [overflow-wrap:anywhere]">
                {dash(t.requirement)}
              </div>
            </div>,
            <span className="font-mono text-xs">{dash(t.metric)}</span>,
            <div className="num whitespace-nowrap">
              {t.value != null ? t.value.toFixed(3) : DASH}
              {t.ci && <div className="font-mono text-2xs text-muted">{formatCI(t.ci, 3)}</div>}
            </div>,
            <span className="font-mono text-xs">{dash(t.threshold)}</span>,
            <Badge tone={t.passed === true ? 'success' : t.passed === false ? 'danger' : 'neutral'}>
              {dash(t.status)}
            </Badge>,
          ])}
        />
      )}
    </div>
  );
}
