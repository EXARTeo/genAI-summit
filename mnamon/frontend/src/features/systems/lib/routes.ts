export const SYSTEM_TABS = ['overview', 'status', 'obligations', 'folder', 'plugins', 'rules'] as const;
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
  audits: (id: string) => `/v1/systems/${encodeURIComponent(id)}/audits`,
  plugins: (id: string) => `/v1/systems/${encodeURIComponent(id)}/plugins`,
  pluginDefaults: (id: string) => `/v1/systems/${encodeURIComponent(id)}/plugins/defaults`,
  components: (id: string) => `/v1/systems/${encodeURIComponent(id)}/plugins/components`,
  component: (id: string, componentId: string) =>
    `/v1/systems/${encodeURIComponent(id)}/plugins/components/${encodeURIComponent(componentId)}`,
  plugin: (id: string, name: string) =>
    `/v1/systems/${encodeURIComponent(id)}/plugins/${encodeURIComponent(name)}`,
};

function encodePath(path: string): string {
  return path.split('/').map(encodeURIComponent).join('/');
}
