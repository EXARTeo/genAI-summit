import { useCallback, useEffect, useState } from 'react';

export type FileBlobState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'ready'; blob: Blob }
  | { status: 'error'; error: unknown };

/**
 * A file's bytes, loaded once per `key` (magenticx `useAttachmentObjectUrl`, without the URL):
 * `load` is a fresh closure on every render, so the key names what it loads. `retry` loads again.
 * A null key (or load) is idle.
 */
export function useFileBlob(load: (() => Promise<Blob>) | null, key: string | null) {
  const [state, setState] = useState<FileBlobState>({ status: 'idle' });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!load || !key) {
      setState({ status: 'idle' });
      return;
    }
    let cancelled = false;
    setState({ status: 'loading' });
    load()
      .then((blob) => !cancelled && setState({ status: 'ready', blob }))
      .catch((error: unknown) => !cancelled && setState({ status: 'error', error }));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, retry } as FileBlobState & { retry: () => void };
}

/**
 * An object URL for a Blob, revoked when the blob changes or the component goes. `type` forces the
 * URL's MIME type (a PDF frame must never render bytes as HTML: a same-origin stored-XSS guard).
 */
export function useObjectUrl(blob: Blob | null | undefined, type?: string): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob) {
      setUrl(null);
      return;
    }
    const typed = type && blob.type !== type ? new Blob([blob], { type }) : blob;
    const next = URL.createObjectURL(typed);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob, type]);
  return url;
}
