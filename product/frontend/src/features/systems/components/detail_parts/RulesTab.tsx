import { AnimatePresence, motion } from 'framer-motion';
import { Plus, ScrollText } from 'lucide-react';
import { useMemo, useState } from 'react';
import { listItem, staggerList } from '@/shared/lib/motion';
import {
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  ErrorState,
  Field,
  Section,
  Select,
  SkeletonText,
  StatusPill,
  Textarea,
  toast,
  type BadgeTone,
} from '@/shared/ui';
import { useBusinessRules } from '../../hooks/useSystemFolder';
import { useProposeRule } from '../../hooks/useSystems';
import { ruleProposalYaml, slugify } from '../../lib/rules';
import type { BusinessRule } from '../../lib/types';

const KIND_TONE: Record<BusinessRule['kind'], BadgeTone> = {
  hard: 'danger',
  soft: 'info',
  policy: 'primary',
};

function AddRuleDialog({
  systemId,
  plugins,
  open,
  onOpenChange,
  onProposed,
}: {
  systemId: string;
  plugins: string[];
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onProposed: (r: BusinessRule) => void;
}) {
  const propose = useProposeRule(systemId);
  const [plugin, setPlugin] = useState(plugins[0] ?? '');
  const [kind, setKind] = useState<BusinessRule['kind']>('hard');
  const [text, setText] = useState('');
  const [rationale, setRationale] = useState('');
  const valid = text.trim().length >= 8 && rationale.trim().length >= 4 && !!plugin;

  const submit = async () => {
    const slug = `${slugify(text)}-${Date.now().toString(36)}`;
    try {
      await propose.mutateAsync({
        slug,
        yaml: ruleProposalYaml({ systemId, plugin, kind, text: text.trim(), rationale: rationale.trim() }),
        reason: rationale.trim(),
      });
      onProposed({
        id: slug,
        plugin,
        kind,
        text: text.trim(),
        title: 'Proposed in the UI',
        status: 'proposed',
      });
      toast.success('Rule proposed', {
        description: 'It becomes active after approval in the Approvals inbox.',
      });
      setText('');
      setRationale('');
      onOpenChange(false);
    } catch (e) {
      toast.error('Could not propose the rule', { description: e instanceof Error ? e.message : String(e) });
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Propose a business rule"
      description="Rules shape synthetic data and pass/fail checks. A proposal stays inactive until a human approves it."
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={submit} disabled={!valid} loading={propose.isPending}>
            Submit proposal
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Plugin">
            <Select
              aria-label="Plugin"
              value={plugin}
              onValueChange={setPlugin}
              options={plugins.map((p) => ({ value: p, label: p }))}
            />
          </Field>
          <Field label="Kind">
            <Select
              aria-label="Kind"
              value={kind}
              onValueChange={(v) => setKind(v as BusinessRule['kind'])}
              options={[
                { value: 'hard', label: 'Hard constraint', description: 'Data that breaks it is invalid' },
                { value: 'soft', label: 'Soft rule', description: 'Usually true; exceptions allowed' },
                { value: 'policy', label: 'Policy', description: 'How the system must behave' },
              ]}
            />
          </Field>
        </div>
        <Field
          label="Rule"
          htmlFor="rule-text"
          hint="One sentence, testable. E.g. “Applicants are 18 to 67 years old.”"
        >
          <Textarea id="rule-text" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
        </Field>
        <Field label="Why" htmlFor="rule-why" hint="Stored with the proposal and shown to the approver.">
          <Textarea id="rule-why" rows={2} value={rationale} onChange={(e) => setRationale(e.target.value)} />
        </Field>
      </div>
    </Dialog>
  );
}

export function RulesTab({ systemId }: { systemId: string }) {
  const { rules, plugins, isLoading, error, refetch } = useBusinessRules(systemId);
  const [proposed, setProposed] = useState<BusinessRule[]>([]);
  const [open, setOpen] = useState(false);

  const grouped = useMemo(() => {
    const g = new Map<string, BusinessRule[]>();
    for (const r of [...proposed, ...rules]) g.set(r.plugin, [...(g.get(r.plugin) ?? []), r]);
    return [...g.entries()];
  }, [rules, proposed]);

  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="max-w-2xl text-sm text-muted">
          Rules come from each plugin&apos;s{' '}
          <code className="font-mono text-text">data/business-rules.md</code>. The synthetic-data generator
          enforces hard rules; checks use policies.
        </p>
        <Button leftIcon={<Plus />} onClick={() => setOpen(true)} disabled={!plugins.length}>
          Add rule
        </Button>
      </div>

      {isLoading ? (
        <SkeletonText lines={8} />
      ) : grouped.length === 0 ? (
        <EmptyState
          icon={<ScrollText />}
          title="No business rules"
          description="Add data/business-rules.md to a plugin, or propose a rule."
        />
      ) : (
        grouped.map(([plugin, list]) => (
          <Section key={plugin} title={plugin} actions={<Badge>{list.length} rules</Badge>}>
            <motion.ul
              variants={staggerList(0.025)}
              initial="initial"
              animate="animate"
              className="space-y-2"
            >
              <AnimatePresence initial={false}>
                {list.map((r) => (
                  <motion.li key={r.id} variants={listItem} layout>
                    <Card
                      className={
                        r.status === 'proposed'
                          ? 'approval-pulse flex items-start gap-3 border-warning/40 bg-warning/5 p-3'
                          : 'flex items-start gap-3 p-3'
                      }
                    >
                      <Badge tone={KIND_TONE[r.kind]} className="mt-0.5 w-14 justify-center">
                        {r.kind}
                      </Badge>
                      <div className="min-w-0 flex-1">
                        <p className="text-sm">{r.text}</p>
                        <p className="mt-0.5 text-xs text-muted">{r.title}</p>
                      </div>
                      {r.status === 'proposed' && <StatusPill status="needs_approval" label="proposed" />}
                    </Card>
                  </motion.li>
                ))}
              </AnimatePresence>
            </motion.ul>
          </Section>
        ))
      )}

      {plugins.length > 0 && (
        <AddRuleDialog
          key={plugins.join(',')}
          systemId={systemId}
          plugins={plugins}
          open={open}
          onOpenChange={setOpen}
          onProposed={(r) => setProposed((p) => [r, ...p])}
        />
      )}
    </div>
  );
}
