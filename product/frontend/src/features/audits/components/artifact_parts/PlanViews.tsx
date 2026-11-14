import { CheckCircle2, CircleDashed, FileText, MinusCircle, Plus, RefreshCw } from 'lucide-react';
import { Badge, KeyValue } from '@/shared/ui';
import type { ContextData, ScenarioAnalysisData, ScenariosData } from '../../lib/types';
import { SimpleTable, SubHeading } from './common';

export function ContextView({ data }: { data: ContextData }) {
  return (
    <div>
      <KeyValue
        items={[
          { label: 'System', value: `${data.system.id} · ${data.system.name}` },
          { label: 'Risk class', value: data.system.annex },
          { label: 'Role', value: data.system.role },
          { label: 'Intended purpose', value: data.system.intendedPurpose },
        ]}
      />
      <SubHeading>Applicable requirements</SubHeading>
      <SimpleTable
        head={['Requirement', 'Provision', 'Testable']}
        rows={data.requirements.map((r) => [
          <div>
            <div className="font-medium">{r.title}</div>
            <div className="font-mono text-xs text-muted">{r.id}</div>
          </div>,
          r.provision,
          r.testable ? <Badge tone="success">test</Badge> : <Badge>document review</Badge>,
        ])}
      />
      <SubHeading>Plugins</SubHeading>
      <div className="flex flex-wrap gap-2">
        {data.plugins.map((p) => (
          <Badge key={p.name} tone="primary">
            {p.name} · {p.accessType}
          </Badge>
        ))}
      </div>
      <SubHeading>Files read (pinned versions)</SubHeading>
      <ul className="space-y-1 text-xs">
        {data.filesRead.map((f) => (
          <li key={f.path} className="flex items-center gap-2 font-mono">
            <FileText className="size-3 text-muted" />
            {f.path}
            <span className="text-muted">v{f.version}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

const PRIORITY = { high: 'danger', medium: 'warning', low: 'neutral' } as const;

export function ScenariosView({ data }: { data: ScenariosData }) {
  return (
    <SimpleTable
      head={['Test', 'Template', 'Groups', 'N', 'Why']}
      rows={data.scenarios.map((s) => [
        <div className="min-w-[12rem]">
          <div className="flex items-center gap-2">
            <span className="font-mono text-xs text-muted">{s.id}</span>
            <Badge tone={PRIORITY[s.priority]}>{s.priority}</Badge>
          </div>
          <div className="font-medium">{s.title}</div>
          <div className="font-mono text-2xs text-muted">{s.requirement}</div>
        </div>,
        <span className="font-mono text-xs">{s.template}</span>,
        s.groups.join(', ') || '–',
        s.n.toLocaleString(),
        <div className="text-muted">{s.rationale}</div>,
      ])}
    />
  );
}

const COVERAGE = {
  covered: { icon: <CheckCircle2 className="size-4 text-success" />, label: 'covered' },
  partial: { icon: <CircleDashed className="size-4 text-warning" />, label: 'partial' },
  not_testable: { icon: <MinusCircle className="size-4 text-muted" />, label: 'not testable' },
};

export function ScenarioAnalysisView({ data }: { data: ScenarioAnalysisData }) {
  return (
    <div>
      <p className="rounded-lg border border-border bg-surface-muted/60 p-3 text-sm">{data.summary}</p>
      <SubHeading>Coverage per requirement</SubHeading>
      <ul className="space-y-2">
        {data.coverage.map((c) => (
          <li key={c.requirement} className="flex items-start gap-2 text-sm">
            {COVERAGE[c.status].icon}
            <div className="min-w-0 flex-1">
              <div className="font-mono text-xs">{c.requirement}</div>
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
      <SubHeading>Risks</SubHeading>
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {data.risks.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      <SubHeading>Not assessable by testing</SubHeading>
      <ul className="space-y-1 text-sm">
        {data.notTestable.map((n) => (
          <li key={n.requirement}>
            <span className="font-mono text-xs">{n.requirement}</span>{' '}
            <span className="text-muted">· {n.why}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
