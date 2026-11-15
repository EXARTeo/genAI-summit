import { AlertTriangle, FileDown, Scale } from 'lucide-react';
import { useRef, type ReactNode } from 'react';
import { formatDateTime } from '@/shared/lib/format';
import { cn } from '@/shared/lib/utils';
import { Badge, Button, Card, EmptyState, Markdown, Skeleton } from '@/shared/ui';
import { useAuditFindings } from '../hooks/useAudits';
import { panelFindings, severityMeta, shortHash } from '../lib/findings';
import { mlflowRunUrl } from '../lib/mlflow';
import { printElement } from '../lib/print';
import { reportModel } from '../lib/report';
import { TONE_CLASSES, trafficTone } from '../lib/styling';
import type { AuditDetail, ReportData } from '../lib/types';
import { SimpleTable, VerdictPill } from './artifact_parts/common';
import { AuditPins } from './AuditPins';

function ReportSection({
  id,
  title,
  children,
  note,
}: {
  id: string;
  title: string;
  children: ReactNode;
  note?: ReactNode;
}) {
  return (
    <section id={`report-${id}`} className="scroll-mt-20 break-inside-avoid">
      <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-border pb-2">
        <h2 className="text-base font-semibold tracking-tight">{title}</h2>
        {note && <span className="text-xs text-muted">{note}</span>}
      </div>
      {children}
    </section>
  );
}

function Management({ data, derived }: { data: ReportData; derived: boolean }) {
  return (
    <div className="space-y-4">
      {data.title && <p className="text-base font-medium">{data.title}</p>}
      {data.traffic && data.traffic.length > 0 && (
        <div className="grid gap-2 sm:grid-cols-2">
          {data.traffic.map((t) => {
            const tone = TONE_CLASSES[trafficTone(t.light)];
            return (
              <div key={t.requirement} className="flex items-start gap-3 rounded-lg border border-border p-3">
                <span className={cn('mt-1 size-3 shrink-0 rounded-full', tone.bg)} aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium [overflow-wrap:anywhere]">
                      {t.title ?? t.requirement}
                    </span>
                    <span className={cn('text-2xs font-semibold uppercase', tone.text)}>{t.light}</span>
                  </div>
                  {t.note && (
                    <div className="mt-0.5 text-xs text-muted [overflow-wrap:anywhere]">{t.note}</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
      {derived && (
        <p className="text-xs text-muted">
          Traffic lights derived from the sealed findings (worst verdict per article).
        </p>
      )}
      {data.markdown && <Markdown>{data.markdown}</Markdown>}
      {(data.decisions?.length ?? 0) > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-semibold">Decisions needed</h3>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {data.decisions!.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </div>
      )}
      {(data.nextSteps?.length ?? 0) > 0 && (
        <div>
          <h3 className="mb-1 text-sm font-semibold">Next steps</h3>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {data.nextSteps!.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/**
 * The audit's report (plan 01 §8): management summary, engineer report, bias & fairness,
 * gap list, evidence register, or the incomplete-audit report. "Export PDF" prints it.
 */
export function ReportPanel({ audit }: { audit: AuditDetail }) {
  const ref = useRef<HTMLDivElement>(null);
  const { data, isLoading } = useAuditFindings(audit.id);
  const findings = panelFindings(data, audit.artifacts, audit.id, audit.systemId);
  const m = reportModel(audit, findings);
  const title = `${audit.data.systemName ?? audit.systemId} · audit ${audit.id}`;

  if (isLoading) return <Skeleton className="h-96 rounded-xl" />;
  const empty = !m.hasReport && !m.incomplete && findings.length === 0;
  if (empty) {
    return (
      <Card className="p-2">
        <EmptyState
          title="No report yet"
          description="Every audit ends with a report: the full report when it completes, an incomplete-audit report when it fails."
        />
      </Card>
    );
  }

  const toc = [
    m.incomplete && ['incomplete', 'Incomplete audit'],
    m.management && ['management', 'Management summary'],
    m.engineer && ['engineer', 'Engineer report'],
    m.bias && ['bias', 'Bias & fairness'],
    ...m.extra.map((e) => [e.id, e.title]),
    ['gaps', 'Gap list'],
    ['evidence', 'Evidence register'],
  ].filter(Boolean) as [string, string][];

  return (
    <div className="space-y-4">
      <div className="flex flex-col-reverse items-start gap-2 sm:flex-row sm:items-center" data-print="hide">
        <nav aria-label="Report sections" className="flex min-w-0 flex-1 flex-wrap gap-1.5">
          {toc.map(([id, label]) => (
            <a
              key={id}
              href={`#report-${id}`}
              onClick={(e) => {
                e.preventDefault();
                document
                  .getElementById(`report-${id}`)
                  ?.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }}
              className="rounded-full border border-border bg-surface px-2.5 py-1 text-xs text-muted transition-colors hover:text-text"
            >
              {label}
            </a>
          ))}
        </nav>
        <Button
          variant="secondary"
          leftIcon={<FileDown />}
          onClick={() => ref.current && printElement(ref.current, `Mnamon report · ${title}`)}
        >
          Export PDF
        </Button>
      </div>

      <Card className="p-5 sm:p-8">
        <div ref={ref} className="space-y-8">
          <header className="space-y-2">
            <div className="text-xs font-medium uppercase tracking-wider text-muted">
              Mnamon · AI Act audit report
            </div>
            <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{title}</h1>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
              <span>{formatDateTime(audit.updatedAt)}</span>
              {m.incomplete ? (
                <Badge tone="warning" icon={<AlertTriangle />}>
                  Incomplete
                </Badge>
              ) : audit.status === 'done' ? (
                <Badge tone="success">Complete</Badge>
              ) : (
                <Badge>In progress</Badge>
              )}
              {m.pdfSha256 && <span className="font-mono">pdf sha256 {shortHash(m.pdfSha256, 16)}</span>}
            </div>
            <AuditPins audit={audit} />
          </header>

          {m.incomplete && (
            <ReportSection
              id="incomplete"
              title="Incomplete audit"
              note="No verdicts for obligations that were not tested"
            >
              <div className="space-y-3 text-sm">
                {m.incomplete.reason && (
                  <p className="rounded-lg border border-warning/30 bg-warning/10 p-3 [overflow-wrap:anywhere]">
                    {m.incomplete.reason}
                  </p>
                )}
                <div className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <h3 className="mb-1 text-sm font-semibold">What ran</h3>
                    <ul className="list-disc space-y-0.5 pl-5">
                      {(m.incomplete.ran.length ? m.incomplete.ran : ['Nothing']).map((s) => (
                        <li key={s}>{s}</li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <h3 className="mb-1 text-sm font-semibold">What did not run</h3>
                    <ul className="list-disc space-y-0.5 pl-5 text-muted">
                      {(m.incomplete.notRun.length ? m.incomplete.notRun : ['–']).map((s) => (
                        <li key={s}>{s}</li>
                      ))}
                    </ul>
                  </div>
                </div>
                {m.incomplete.markdown && <Markdown>{m.incomplete.markdown}</Markdown>}
              </div>
            </ReportSection>
          )}

          {m.management && (
            <ReportSection id="management" title="Management summary">
              <Management data={m.management} derived={m.managementDerived} />
            </ReportSection>
          )}

          {m.engineer && (
            <ReportSection id="engineer" title="Engineer report">
              <Markdown>{m.engineer.markdown}</Markdown>
            </ReportSection>
          )}

          {m.bias && (
            <ReportSection
              id="bias"
              title="Bias & fairness"
              note="Thresholds are the organisation's, not the law's"
            >
              <Markdown>{m.bias}</Markdown>
            </ReportSection>
          )}

          {m.extra.map((e) => (
            <ReportSection key={e.id} id={e.id} title={e.title}>
              <Markdown>{e.markdown}</Markdown>
            </ReportSection>
          ))}

          <ReportSection
            id="gaps"
            title="Gap list"
            note={`${m.gaps.length} gap${m.gaps.length === 1 ? '' : 's'}`}
          >
            {m.gaps.length === 0 ? (
              <p className="text-sm text-muted">No gaps.</p>
            ) : (
              <SimpleTable
                head={['Gap', 'Obligation', 'Severity', 'Verdict', 'In force', 'Remediation']}
                rows={m.gaps.map((g) => {
                  const sev = severityMeta(g.severity);
                  return [
                    <span key="g" className="whitespace-nowrap font-mono text-xs">
                      {g.gapId}
                    </span>,
                    <span key="o" className="block min-w-[9rem]">
                      {g.article && <span className="block text-sm">{g.article}</span>}
                      <span className="font-mono text-2xs text-muted [overflow-wrap:anywhere]">
                        {g.obligationId}
                      </span>
                    </span>,
                    sev ? (
                      <Badge key="s" tone={sev.tone}>
                        {sev.label}
                      </Badge>
                    ) : (
                      '–'
                    ),
                    <VerdictPill key="v" verdict={g.verdict} />,
                    <span key="d" className="num whitespace-nowrap font-mono text-xs">
                      {g.inForce ?? '–'}
                    </span>,
                    <span key="r" className="block min-w-[12rem] text-xs">
                      {g.remediation ?? '–'}
                    </span>,
                  ];
                })}
              />
            )}
          </ReportSection>

          <ReportSection
            id="evidence"
            title="Evidence register"
            note="Every verdict → evidence files (sha256), MLflow runs, provisions at the pinned kb"
          >
            {m.evidence.length === 0 ? (
              <p className="text-sm text-muted">No sealed verdicts yet.</p>
            ) : (
              <SimpleTable
                head={['Obligation', 'Verdict', 'Evidence', 'Provisions', 'Seal']}
                rows={m.evidence.map((r) => [
                  <span key="o" className="font-mono text-xs [overflow-wrap:anywhere]">
                    {r.obligationId}
                  </span>,
                  <VerdictPill key="v" verdict={r.verdict} />,
                  <ul key="e" className="min-w-[14rem] space-y-1 text-xs">
                    {r.evidence.length === 0 && <li className="text-muted">–</li>}
                    {r.evidence.map((e, i) => {
                      const run = mlflowRunUrl(e.mlflow_run_id, e.experiment_id);
                      return (
                        <li key={i} className="[overflow-wrap:anywhere]">
                          <span className="font-mono">{e.path}</span>
                          {e.sha256 && <span className="font-mono text-muted"> · {shortHash(e.sha256)}</span>}
                          {run && (
                            <>
                              {' · '}
                              <a
                                href={run}
                                target="_blank"
                                rel="noreferrer"
                                className="text-primary hover:underline"
                              >
                                MLflow
                              </a>
                            </>
                          )}
                        </li>
                      );
                    })}
                  </ul>,
                  <div key="c" className="flex min-w-[10rem] flex-wrap gap-1">
                    {r.citations.length === 0 && <span className="text-xs text-muted">–</span>}
                    {r.citations.map((c, i) => (
                      <Badge key={i} icon={<Scale />}>
                        {c.provision_id}
                        {c.kb_version && <span className="font-mono text-muted"> · {c.kb_version}</span>}
                      </Badge>
                    ))}
                  </div>,
                  <span key="h" className="num font-mono text-2xs text-muted">
                    {r.hash ? shortHash(r.hash) : 'not sealed'}
                  </span>,
                ])}
              />
            )}
          </ReportSection>
        </div>
      </Card>
    </div>
  );
}
