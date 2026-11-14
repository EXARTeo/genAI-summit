/**
 * Composer state (port of magenticx `hooks/useComposer.ts`): the draft and the attached files.
 * Files are read to base64 as soon as they are added, with progress, so sending never waits on a
 * big read; a file that fails or breaks a limit is refused with a toast.
 */
import { useCallback, useRef, useState } from 'react';
import { toast } from '@/shared/ui';
import { checkFiles, mimeOf, readAsBase64, type PendingAttachment } from '../lib/attachments';

let seq = 0;

export function useComposer() {
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const current = useRef<PendingAttachment[]>([]);
  current.current = attachments;

  const update = (key: string, patch: Partial<PendingAttachment>) =>
    setAttachments((list) => list.map((a) => (a.key === key ? { ...a, ...patch } : a)));

  const addFiles = useCallback((input: FileList | File[]) => {
    const files = Array.from(input);
    if (!files.length) return;
    const problem = checkFiles(files, current.current);
    if (problem) {
      toast.error(problem);
      return;
    }
    const added: PendingAttachment[] = files.map((file) => ({
      key: `f${++seq}`,
      file,
      name: file.name || `pasted-${seq}.png`,
      mime: mimeOf(file),
      size: file.size,
      progress: 0,
    }));
    setAttachments((list) => [...list, ...added]);
    for (const a of added) {
      readAsBase64(a.file, (p) => update(a.key, { progress: p }))
        .then((dataB64) => update(a.key, { dataB64, progress: 1 }))
        .catch(() => {
          toast.error(`Could not read ${a.name}`);
          setAttachments((list) => list.filter((x) => x.key !== a.key));
        });
    }
  }, []);

  const remove = useCallback(
    (key: string) => setAttachments((list) => list.filter((a) => a.key !== key)),
    [],
  );
  const reset = useCallback(() => {
    setDraft('');
    setAttachments([]);
  }, []);

  const reading = attachments.some((a) => !a.dataB64);
  const canSend = (draft.trim().length > 0 || attachments.length > 0) && !reading;

  return { draft, setDraft, attachments, addFiles, remove, reset, reading, canSend };
}

export type Composer = ReturnType<typeof useComposer>;
