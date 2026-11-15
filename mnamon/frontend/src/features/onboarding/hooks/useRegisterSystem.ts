import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { systemKeys } from '@/features/systems/hooks/useSystems';
import { createSystem, uploadFile, writeTextFile } from '../handlers/onboarding';
import { buildCard, cardYaml, docPath, type WizardForm } from '../lib/wizard';

export interface RegisterProgress {
  done: number;
  total: number;
  label: string;
}

/**
 * Create the system (`status: draft`, card in `data.card`), then its `system-card.yaml` v1,
 * then one `docs/<name>` per document, in that order (plan 02 §5).
 */
export function useRegisterSystem() {
  const qc = useQueryClient();
  const [progress, setProgress] = useState<RegisterProgress | null>(null);
  // A retry after a failed upload must not create the system twice (409).
  const created = useRef<string | null>(null);
  const mutation = useMutation({
    mutationFn: async ({ form, files }: { form: WizardForm; files: File[] }) => {
      const card = buildCard(form);
      const id = String(card.id);
      const total = 2 + files.length;
      setProgress({ done: 0, total, label: 'Creating the system' });
      if (created.current !== id) {
        await createSystem({ id, name: String(card.name), status: 'draft', data: { card } });
        created.current = id;
      }
      setProgress({ done: 1, total, label: 'Writing the system card' });
      await writeTextFile(id, 'system-card.yaml', cardYaml(card), 'registered by the PM');
      for (const [i, f] of files.entries()) {
        setProgress({ done: 2 + i, total, label: `Uploading ${f.name}` });
        await uploadFile(id, docPath(f.name), f, 'uploaded at registration');
      }
      setProgress({ done: total, total, label: 'Done' });
      return id;
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: systemKeys.all });
    },
  });
  return { ...mutation, progress };
}
