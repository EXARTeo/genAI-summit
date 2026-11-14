// Links into the self-hosted Langfuse (compose: host port 3400, project id `product`).
const BASE = (import.meta.env.VITE_LANGFUSE_URL as string | undefined) ?? 'http://localhost:3400';
const PROJECT = (import.meta.env.VITE_LANGFUSE_PROJECT_ID as string | undefined) ?? 'product';

export function traceUrl(traceId?: string | null): string | null {
  if (!traceId) return null;
  const id = traceId.replace(/^langfuse:/, '');
  return `${BASE.replace(/\/$/, '')}/project/${PROJECT}/traces/${encodeURIComponent(id)}`;
}
