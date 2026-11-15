import { FlaskConical } from 'lucide-react';
import { useState } from 'react';
import { Button, Dialog, Field, Textarea, toast } from '@/shared/ui';
import { useSimulateChange } from '../hooks/useRegulation';

/**
 * "Simulate change" (demo/admin): edit the mirrored Commission guideline page and re-check it at
 * once, so a real RegChange lands in the inbox. Nothing official is touched.
 */
export function SimulateChangeButton() {
  const [open, setOpen] = useState(false);
  const [find, setFind] = useState('');
  const [replace, setReplace] = useState('');
  const simulate = useSimulateChange();
  const valid = find.trim().length > 0 && replace.trim() !== find.trim();

  const submit = () =>
    simulate.mutate(
      { find, replace },
      {
        onSuccess: (r) => {
          setOpen(false);
          const id = r?.check?.release?.change_id;
          toast.success('Guideline page changed and checked', {
            description: id ? `${id} is in the change inbox.` : 'A new change appears in the inbox.',
          });
        },
        onError: (e) => toast.error('Could not simulate the change', { description: (e as Error).message }),
      },
    );

  return (
    <>
      <Button variant="secondary" leftIcon={<FlaskConical />} onClick={() => setOpen(true)}>
        Simulate change
      </Button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        size="lg"
        title="Simulate a regulation change"
        description="Edits the demo mirror of the Commission's Art. 6 guideline page (not an official source), then runs Check now on it. The change goes through the normal inbox: accept it to run the change judge."
        footer={
          <>
            <Button variant="secondary" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button onClick={submit} disabled={!valid} loading={simulate.isPending}>
              Change and check now
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field label="Find" htmlFor="sim-find" hint="Exact text on the mirrored page.">
            <Textarea id="sim-find" rows={3} value={find} onChange={(e) => setFind(e.target.value)} />
          </Field>
          <Field label="Replace with" htmlFor="sim-replace">
            <Textarea
              id="sim-replace"
              rows={4}
              value={replace}
              onChange={(e) => setReplace(e.target.value)}
            />
          </Field>
        </div>
      </Dialog>
    </>
  );
}
