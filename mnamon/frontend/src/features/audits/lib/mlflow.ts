// Links into the local MLflow UI (compose: host port 5500).
const BASE = (import.meta.env.VITE_MLFLOW_URL as string | undefined) ?? 'http://localhost:5500';

/** A run page; with the experiment id when known (MLflow redirects `#/runs/<id>` otherwise). */
export function mlflowRunUrl(runId?: string | null, experimentId?: string | null): string | null {
  if (!runId) return null;
  const root = BASE.replace(/\/$/, '');
  const id = encodeURIComponent(runId.replace(/^mlflow:\/?\/?(runs\/)?/, ''));
  return experimentId
    ? `${root}/#/experiments/${encodeURIComponent(experimentId)}/runs/${id}`
    : `${root}/#/runs/${id}`;
}
