import { Check, X } from 'lucide-react';
import { useEffect, useId, useState } from 'react';
import { Badge, Button, Dialog, Field, Textarea, toast } from '@/shared/ui';
import { REASON_MAX, riskLabel, routeLabel } from '../../lib/classification';
import type { ClassificationResult } from '../../lib/types';

/** Card keys an approval writes (plan 02 §7.3), shown so the approver knows what changes. */
function approveEffects(r: ClassificationResult): string[] {
  const out = [`risk_class: ${r.risk_class}`, `annex_basis: ${r.annex_basis ?? 'none'}`, `role: ${r.role}`];
  if (r.art6_3?.holds) out.push(`art_6_3_claim: condition (${r.art6_3.condition ?? '?'})`);
  if (r.transparency?.features?.length) out.push(`features: ${r.transparency.features.join(', ')}`);
  return out;
}

/**
 * Approve (note optional) or reject (reason required) a proposed classification. A rejection's
 * reason rides into the next run as feedback; an approval writes the system card.
 */
export function DecisionDialog({
  open,
  onOpenChange,
  mode,
  classificationId,
  result,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: 'approve' | 'reject';
  classificationId: string;
  result: ClassificationResult;
  onSubmit: (reason: string) => Promise<unknown>;
}) {
  const id = useId();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);
  const rejecting = mode === 'reject';
  const blank = reason.trim() === '';
  const risk = riskLabel(result.risk_class);

  useEffect(() => {
    if (open) {
      setReason('');
      setTouched(false);
    }
  }, [open, mode]);

  const submit = async () => {
    setTouched(true);
    if (rejecting && blank) return;
    setBusy(true);
    try {
      await onSubmit(reason.trim());
      toast.success(
        rejecting
          ? 'Rejected. Re-classify to run again with your reason.'
          : 'Approved. The system card is updated.',
      );
      onOpenChange(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save the decision');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => {
        if (!busy) onOpenChange(o);
      }}
      size="md"
      title={rejecting ? 'Reject the proposal' : 'Approve the classification'}
      description={<span className="font-mono text-xs">{classificationId}</span>}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant={rejecting ? 'danger' : 'primary'}
            leftIcon={rejecting ? <X /> : <Check />}
            onClick={submit}
            loading={busy}
          >
            {rejecting ? 'Reject' : 'Approve'}
          </Button>
        </>
      }
    >
      <div className="space-y-4 pt-1">
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface-muted/40 px-3 py-2.5 text-sm">
          <Badge tone={risk.tone}>{risk.label}</Badge>
          <span className="text-muted">{routeLabel(result.route, result.art6_3?.condition)}</span>
        </div>

        {!rejecting && (
          <div className="text-sm">
            <p className="text-muted">Approving writes a new version of the system card:</p>
            <ul className="mt-2 space-y-1 font-mono text-xs">
              {approveEffects(result).map((e) => (
                <li key={e} className="rounded-md bg-surface-muted/60 px-2 py-1 [overflow-wrap:anywhere]">
                  {e}
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-muted">
              The obligations that follow are previewed on the Obligations tab. You are recorded as the
              approver.
            </p>
          </div>
        )}

        <Field
          label={rejecting ? 'Why is it wrong?' : 'Note (optional)'}
          htmlFor={id}
          error={rejecting && touched && blank ? 'A reason is required: the next run reads it.' : undefined}
          hint={
            rejecting
              ? 'The next run gets this as feedback. Point at the fact it missed (e.g. "It also ranks candidates, see spec §3").'
              : 'Kept in the classification history.'
          }
        >
          <Textarea
            id={id}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={rejecting ? 4 : 2}
            maxLength={REASON_MAX}
            invalid={rejecting && touched && blank}
            placeholder={rejecting ? 'e.g. It also ranks candidates, see spec §3.' : ''}
            autoFocus
          />
        </Field>
      </div>
    </Dialog>
  );
}
