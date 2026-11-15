import { useId, useState } from 'react';
import { Button, Dialog, Field, Textarea, toast } from '@/shared/ui';

/**
 * Close (reason required) or reopen (reason optional) one register item. The reason goes into the
 * item's history and, for a close, is what later audits show as the accepted risk.
 */
export function ReasonDialog({
  open,
  onOpenChange,
  mode,
  label,
  onSubmit,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: 'close' | 'reopen';
  /** e.g. "Art. 10(2)(f) · Bias examination". */
  label: string;
  onSubmit: (reason: string) => Promise<unknown>;
}) {
  const id = useId();
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const closing = mode === 'close';
  const blank = reason.trim() === '';

  const submit = async () => {
    if (closing && blank) return;
    setBusy(true);
    try {
      await onSubmit(reason.trim());
      toast.success(closing ? 'Closed as an accepted risk' : 'Reopened');
      setReason('');
      onOpenChange(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not save');
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
      size="sm"
      title={closing ? 'Close with a reason' : 'Reopen'}
      description={label}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={submit} loading={busy} disabled={closing && blank}>
            {closing ? 'Close item' : 'Reopen item'}
          </Button>
        </>
      }
    >
      <Field
        label={closing ? 'Why is this acceptable?' : 'Why reopen it? (optional)'}
        htmlFor={id}
        hint={
          closing
            ? 'Recorded with your name in the history. Later audits keep it closed unless the verdict gets worse.'
            : 'The item is open again until it is fixed or closed.'
        }
      >
        <Textarea
          id={id}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          rows={4}
          maxLength={5000}
          placeholder={closing ? 'e.g. Mitigated by a human review of every rejected CV (process P-12).' : ''}
          autoFocus
        />
      </Field>
    </Dialog>
  );
}
