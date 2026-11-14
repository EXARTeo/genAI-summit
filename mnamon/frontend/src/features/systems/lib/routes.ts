export const SYSTEM_TABS = ['overview', 'folder', 'plugins', 'rules'] as const;
export type SystemTab = (typeof SYSTEM_TABS)[number];

export const systemRoutes = {
  list: () => '/systems',
  detail: (id: string, tab?: SystemTab) =>
    `/systems/${encodeURIComponent(id)}${tab && tab !== 'overview' ? `/${tab}` : ''}`,
};

/** Backend paths (behind /api). */
export const systemApi = {
  list: () => '/v1/systems',
  get: (id: string) => `/v1/systems/${encodeURIComponent(id)}`,
  files: (id: string) => `/v1/systems/${encodeURIComponent(id)}/files`,
  file: (id: string, path: string) => `/v1/systems/${encodeURIComponent(id)}/files/${encodePath(path)}`,
  versions: (id: string, path: string) =>
    `/v1/systems/${encodeURIComponent(id)}/files/${encodePath(path)}/versions`,
  events: (id: string) => `/v1/systems/${encodeURIComponent(id)}/events`,
};

function encodePath(path: string): string {
  return path.split('/').map(encodeURIComponent).join('/');
}
