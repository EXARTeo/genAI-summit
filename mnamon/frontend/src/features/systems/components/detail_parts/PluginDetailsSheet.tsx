import { CheckCircle2, Settings2, TriangleAlert, XCircle } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';
import { Badge, Button, Sheet, type BadgeTone } from '@/shared/ui';
import { hintLabel, limitFacts, outputLabel, targetLabel } from '../../lib/plugins';
import { ACCESS_LABEL } from '../../lib/styles';
import type { PluginCard } from '../../lib/types';

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-3">
      <h3 className="font-heading text-lg leading-tight">{title}</h3>
      {children}
    </section>
  );
}

function Checklist({
  label,
  items,
  icon,
  cls,
}: {
  label: string;
  items?: string[];
  icon: ReactNode;
  cls: string;
}) {
  if (!items?.length) return null;
  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-muted">{label}</div>
      <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border">
        {items.map((t) => (
          <li key={t} className="flex items-start gap-3 px-3 py-2.5 text-sm">
            <span className={cn('mt-0.5 shrink-0 [&_svg]:size-4', cls)}>{icon}</span>
            <span>{t}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-baseline gap-3 py-2 text-sm sm:grid-cols-[8rem_minmax(0,1fr)]">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

function Chips({ label, items, tone }: { label: string; items?: string[]; tone?: BadgeTone }) {
  if (!items?.length) return null;
  return (
    <div className="space-y-1.5">
      <div className="text-xs font-medium text-muted">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {items.map((t) => (
          <Badge key={t} tone={tone} className="h-6 px-2 text-xs">
            {hintLabel(t)}
          </Badge>
        ))}
      </div>
    </div>
  );
}

/** Everything in plugin.yaml beyond the card face: behaviour checklist, connection, test hints. */
export function PluginDetailsSheet({
  plugin: p,
  open,
  onOpenChange,
  onConfigure,
}: {
  plugin: PluginCard;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfigure: () => void;
}) {
  const access = p.access ?? { type: 'unknown' };
  const exp = p.expected_behaviour ?? { task: '' };
  const target = targetLabel(access);
  const output = outputLabel(p.io);
  const facts = limitFacts(access.limits);
  const s = p.scenarios;
  const hasHints = !!(
    s?.personas?.length ||
    s?.edge_cases?.length ||
    s?.protected_attributes?.length ||
    s?.known_proxies?.length ||
    s?.metamorphic_relations?.length
  );

  return (
    <Sheet
      open={open}
      onOpenChange={onOpenChange}
      title={p.name}
      description={`${ACCESS_LABEL[access.type] ?? access.type} plugin`}
      footer={
        <Button variant="secondary" size="sm" onClick={onConfigure}>
          <Settings2 />
          Configure plugin
        </Button>
      }
    >
      <div className="space-y-8">
        <Block title="Expected behaviour">
          {exp.task && <p className="text-sm leading-relaxed">{exp.task}</p>}
          <Checklist label="Must" items={exp.must} icon={<CheckCircle2 />} cls="text-success" />
          <Checklist label="Must never" items={exp.must_not} icon={<XCircle />} cls="text-danger" />
          <Checklist
            label="Known limitations"
            items={exp.known_limitations}
            icon={<TriangleAlert />}
            cls="text-warning"
          />
        </Block>

        <Block title="Connection">
          <dl className="divide-y divide-border">
            <Row label="Access">{ACCESS_LABEL[access.type] ?? access.type}</Row>
            {access.environment && (
              <Row label="Environment">
                <Badge tone={access.environment === 'production' ? 'warning' : 'neutral'}>
                  {access.environment}
                </Badge>
              </Row>
            )}
            {target && (
              <Row label={access.uri ? 'Model' : 'Endpoint'}>
                <code className="block overflow-x-auto whitespace-nowrap font-mono text-xs">
                  {target.full}
                </code>
              </Row>
            )}
            {output && <Row label="Output">{output}</Row>}
            {p.io?.input_schema && (
              <Row label="Input fields">
                <code className="block overflow-x-auto whitespace-nowrap font-mono text-xs">
                  {p.io.input_schema}
                </code>
              </Row>
            )}
          </dl>
          {facts.length > 0 && (
            <div className="grid grid-cols-3 gap-2">
              {facts.map((f) => (
                <div key={f.label} className="rounded-lg bg-surface-muted/60 px-3 py-2">
                  <div className="font-heading text-xl tabular-nums leading-tight">
                    {f.value}
                    {f.unit && <span className="ml-0.5 text-sm text-muted">{f.unit}</span>}
                  </div>
                  <div className="text-2xs text-muted">{f.label}</div>
                </div>
              ))}
            </div>
          )}
        </Block>

        {hasHints && (
          <Block title="Test hints">
            <p className="text-xs text-muted">
              The agent uses these to plan scenarios and generate synthetic data.
            </p>
            <Chips label="Personas" items={s?.personas} />
            <Chips label="Edge cases" items={s?.edge_cases} />
            <Chips label="Protected attributes" items={s?.protected_attributes} tone="danger" />
            <Chips label="Known proxies" items={s?.known_proxies} tone="warning" />
            {s?.metamorphic_relations?.length ? (
              <div className="space-y-1.5">
                <div className="text-xs font-medium text-muted">Invariants to test</div>
                <ul className="space-y-1 text-sm">
                  {s.metamorphic_relations.map((r) => (
                    <li key={r} className="rounded-lg bg-surface-muted/60 px-3 py-2">
                      {r}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {s?.data_policy && (
              <p className="text-xs text-muted">
                Data policy: <span className="text-text">{hintLabel(s.data_policy)}</span>
              </p>
            )}
          </Block>
        )}
      </div>
    </Sheet>
  );
}
