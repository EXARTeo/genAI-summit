import { parse, stringify } from 'yaml';
import type {
  GraphComponent,
  GraphEdge,
  MlflowModelInfo,
  PluginCard,
  PluginDefaults,
  PluginGraph,
  PluginWriteResult,
} from '@/features/systems/lib/types';
import { mockSystems, writeFile } from '../fixtures/systems';
import { MockResponse, mockError, type MockRoute } from '../types';

const notFound = () => mockError(404, 'System not found');

async function bodyText(body: unknown): Promise<{ text: string; reason: string | null }> {
  if (body instanceof FormData) {
    const f = body.get('file');
    return {
      text: f instanceof Blob ? await f.text() : String(f ?? ''),
      reason: (body.get('reason') as string) ?? null,
    };
  }
  const b = (body ?? {}) as { content?: string; reason?: string };
  return { text: b.content ?? '', reason: b.reason ?? null };
}

// ---- plugins (mirrors mnamon/backend/utils/plugins.py) ---------------------------------

type Obj = Record<string, unknown>;
const PLUGIN_NAME = /^[a-z0-9][a-z0-9-]{0,62}$/;
const PLUGIN_FILE = /^plugins\/([^/]+)\/plugin\.ya?ml$/;
const MODEL_URI = /^models:\/([^@/]+)(?:@([\w-]+)|\/(\d+))?$/;
const ENV_REF = /^env:\/\/[A-Z_][A-Z0-9_]{0,63}$/;
const ACCESS_TYPES = ['mlflow_model', 'rest', 'llm_chat', 'batch_file', 'dataset_only'];

const isObj = (v: unknown): v is Obj => !!v && typeof v === 'object' && !Array.isArray(v);
const short = (id: string) => (id.includes('.') ? id.slice(id.indexOf('.') + 1) : id);
const humanize = (s: string) => {
  const w = s.replace(/[-_]+/g, ' ').trim();
  return w.slice(0, 1).toUpperCase() + w.slice(1);
};
const slug = (t: string) =>
  t
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 63);

function readYaml(systemId: string, path: string): Obj {
  const f = mockSystems.read(systemId, path);
  if (!f) return {};
  try {
    const data: unknown = parse(f.text);
    return isObj(data) ? data : {};
  } catch {
    return {};
  }
}

/** `plugins/cv-ranker` → `cv-ranker`. */
function pluginFolder(ref: unknown): string | null {
  if (!ref) return null;
  const parts = String(ref)
    .replace(/^\/+|\/+$/g, '')
    .split('/');
  return parts.length >= 2 && parts[0] === 'plugins' ? parts[1] : parts[parts.length - 1];
}

function readPlugins(systemId: string): Record<string, PluginCard> {
  const out: Record<string, PluginCard> = {};
  for (const f of mockSystems.tree(systemId, 'plugins')) {
    const m = PLUGIN_FILE.exec(f.path);
    if (m) out[m[1]] = readYaml(systemId, f.path) as PluginCard;
  }
  return out;
}

const uriOf = (card: PluginCard | null | undefined) =>
  (isObj(card?.access) ? card.access.uri : undefined) ?? null;

function systemGraph(systemId: string): PluginGraph {
  const arch = readYaml(systemId, 'architecture.yaml');
  const plugins = readPlugins(systemId);
  const byPluginId = Object.fromEntries(Object.entries(plugins).map(([n, c]) => [String(c.id ?? ''), n]));
  const components: GraphComponent[] = [];
  const linked = new Set<string>();
  for (const raw of Array.isArray(arch.components) ? arch.components : []) {
    if (!isObj(raw) || !raw.id) continue;
    const cid = String(raw.id);
    const folder = pluginFolder(raw.plugin) ?? byPluginId[cid] ?? null;
    const configured = !!folder && folder in plugins;
    if (configured) linked.add(folder);
    const card = configured ? plugins[folder] : undefined;
    components.push({
      id: cid,
      name: String(card?.name || humanize(short(cid))),
      kind: String(raw.kind ?? ''),
      model: (raw.model as string | undefined) ?? uriOf(card),
      note: (raw.note as string | undefined) ?? null,
      plugin: folder,
      configured,
      testable: !!(raw.model || raw.plugin || configured),
    });
  }
  for (const [folder, card] of Object.entries(plugins)) {
    if (linked.has(folder)) continue;
    components.push({
      id: String(card.id || `${systemId}.${folder}`),
      name: String(card.name || humanize(folder)),
      kind: 'plugin',
      model: uriOf(card),
      note: null,
      plugin: folder,
      configured: true,
      testable: true,
    });
  }
  const known = new Set(components.map((c) => c.id));
  const edges: GraphEdge[] = (Array.isArray(arch.edges) ? arch.edges : [])
    .filter((e): e is Obj => isObj(e) && known.has(String(e.from)) && known.has(String(e.to)))
    .map((e) => ({
      source: String(e.from),
      target: String(e.to),
      data: (e.data as string | undefined) ?? null,
    }));
  return {
    system: systemId,
    components,
    edges,
    entry: (arch.end_to_end_entry as string | undefined) ?? null,
    plugins,
  };
}

/** Components in pipeline order (longest path from a source, then file order). */
function pipelineOrder(graph: PluginGraph): string[] {
  const ids = graph.components.map((c) => c.id);
  const level: Record<string, number> = Object.fromEntries(ids.map((i) => [i, 0]));
  for (let n = 0; n < ids.length; n++)
    for (const e of graph.edges) level[e.target] = Math.max(level[e.target], level[e.source] + 1);
  return [...ids].sort((a, b) => level[a] - level[b] || ids.indexOf(a) - ids.indexOf(b));
}

function placement(graph: PluginGraph, componentId: string | null): PluginCard['placement'] {
  if (!componentId || !graph.components.some((c) => c.id === componentId)) return { kind: 'standalone' };
  const names = Object.fromEntries(graph.components.map((c) => [c.id, c.name]));
  const order = pipelineOrder(graph);
  return {
    kind: order.length > 1 ? 'pipeline_stage' : 'standalone',
    position: `${order.indexOf(componentId) + 1} of ${order.length}`,
    upstream: graph.edges.filter((e) => e.target === componentId).map((e) => e.source),
    downstream: graph.edges.filter((e) => e.source === componentId).map((e) => e.target),
    pipeline_summary: order.map((i) => names[i]).join(' → '),
    ...(graph.entry ? { end_to_end_entry: graph.entry } : {}),
  };
}

/** Input fields from the plugin's data dictionary (stands in for the MLflow signature). */
function dictionaryFields(systemId: string, name: string): { name: string; type: string }[] {
  const fields = readYaml(systemId, `plugins/${name}/data/data-dictionary.yaml`).fields;
  if (!isObj(fields)) return [];
  return Object.entries(fields)
    .filter(([, f]) => isObj(f) && f.role !== 'target' && f.role !== 'label')
    .map(([n, f]) => ({ name: n, type: String((f as Obj).type ?? '') }));
}

function pluginDefaults(systemId: string, query: URLSearchParams): PluginDefaults | MockResponse {
  const graph = systemGraph(systemId);
  const componentId = query.get('component');
  const model = query.get('model');
  const component = graph.components.find((c) => c.id === componentId) ?? null;
  if (componentId && !component) return mockError(404, 'Component not found in architecture.yaml.');
  let name = query.get('name') || component?.plugin || null;
  if (!name && component) name = slug(short(component.id));
  if (!name && model) {
    const m = MODEL_URI.exec(model);
    name = m ? slug(m[1]) : null;
  }
  if (!name || !PLUGIN_NAME.test(name)) return mockError(422, 'Give a component, a model or a plugin name.');
  const existing = graph.plugins[name] ?? null;
  const modelUri = model || component?.model || uriOf(existing);
  const modelName = modelUri ? (MODEL_URI.exec(modelUri)?.[1] ?? null) : null;
  const inputs = dictionaryFields(systemId, name);
  const mlflow: MlflowModelInfo = modelName
    ? {
        status: 'ok',
        name: modelName,
        alias: 'champion',
        version: '1',
        run_id: null,
        description: null,
        tags: {},
        inputs,
        outputs: [],
        error: null,
      }
    : { status: 'not_mlflow', tags: {}, inputs: [], outputs: [] };
  const access: PluginCard['access'] = { type: modelUri ? 'mlflow_model' : 'rest' };
  if (modelUri) access.uri = modelUri;
  if (modelName) access.rest_url = `/v1/models/${modelName}/predict`;
  Object.assign(access, {
    environment: 'staging',
    auth: { type: 'bearer', secret_ref: 'env://MODEL_GATEWAY_TOKEN' },
    limits: { rps: 5, max_requests: 500, timeout_s: 10 },
  });
  const existingOutput = isObj(existing?.io) ? existing.io.output : undefined;
  const defaults: PluginCard = {
    id: component?.id ?? `${systemId}.${name}`,
    system: systemId,
    name: component?.name ?? humanize(name),
    card_version: 1,
    placement: placement(graph, component?.id ?? null),
    access,
    io: {
      input_schema: 'data/data-dictionary.yaml',
      output: existingOutput ?? {
        type: 'binary_classification',
        positive_label: 1,
        label_field: 'label',
        score_field: 'score',
      },
      ...(inputs.length ? { input_fields: inputs } : {}),
    },
    expected_behaviour: {
      task: existing?.expected_behaviour?.task ?? '',
      must: [],
      must_not: [],
      known_limitations: [],
    },
    scenarios: { data_policy: 'synthetic_only', generation: { mode: 'zero_shot', seed: 42 } },
  };
  return { name, component: component?.id ?? null, defaults, existing, mlflow };
}

function validateCard(card: Obj): string[] {
  const access = card.access;
  if (!isObj(access)) return ['access: missing'];
  const errors: string[] = [];
  if (!ACCESS_TYPES.includes(String(access.type)))
    errors.push(`access.type: one of ${ACCESS_TYPES.join(', ')}`);
  if (access.type === 'mlflow_model' && !MODEL_URI.test(String(access.uri ?? '')))
    errors.push('access.uri: an MLflow model URI, models:/<name>@<alias> or /<version>');
  if ((access.type === 'rest' || access.type === 'llm_chat') && !access.url)
    errors.push('access.url: the endpoint (a /v1/... path joins MODEL_GATEWAY_URL)');
  const ref = isObj(access.auth) ? access.auth.secret_ref : undefined;
  if (ref && !ENV_REF.test(String(ref)))
    errors.push("access.auth.secret_ref: env://NAME (the runner's environment)");
  if (!String(card.name ?? '').trim()) errors.push('name: required');
  return errors;
}

/** Point the component at `plugins/<name>` in architecture.yaml (add it when missing). */
function linkComponent(systemId: string, name: string, card: Obj, componentId: string | null): boolean {
  const arch = readYaml(systemId, 'architecture.yaml');
  if (!Array.isArray(arch.components)) arch.components = [];
  arch.system ??= systemId;
  const components = arch.components as Obj[];
  const ref = `plugins/${name}`;
  const uri = isObj(card.access) ? (card.access.uri as string | undefined) : undefined;
  const target = componentId ?? String(card.id);
  const comp = components.find((c) => isObj(c) && c.id === target);
  if (comp) {
    if (comp.plugin === ref && (!uri || comp.model === uri)) return false;
    comp.plugin = ref;
    if (uri) comp.model = uri;
  } else {
    if (components.some((c) => isObj(c) && pluginFolder(c.plugin) === name)) return false;
    components.push({ id: target, plugin: ref, kind: 'ml_model', ...(uri ? { model: uri } : {}) });
  }
  writeFile(
    systemId,
    'architecture.yaml',
    `# System graph: components, their plugins and the data between them.\n${stringify(arch)}`,
    'user:demo',
    `plugin ${name} linked`,
  );
  return true;
}

function savePlugin(systemId: string, name: string, body: unknown): PluginWriteResult | MockResponse {
  if (!PLUGIN_NAME.test(name)) return mockError(422, "Plugin name: lowercase letters, digits, '-'.");
  const b = (isObj(body) ? body : {}) as {
    card?: unknown;
    component?: string | null;
    reason?: string | null;
  };
  if (!isObj(b.card)) return mockError(422, 'card: required');
  const card: Obj = Object.fromEntries(
    Object.entries(b.card).filter(([, v]) => v !== null && v !== undefined),
  );
  card.system = systemId;
  card.id ??= b.component || `${systemId}.${name}`;
  const errors = validateCard(card);
  if (errors.length) return mockError(422, `Invalid plugin: ${errors.join('; ')}`);
  const text =
    '# Plugin: how the audit agent reaches this model (written by the Plugins tab).\n' +
    '# Secrets are only named (auth.secret_ref: env://NAME), never stored here.\n' +
    stringify(card);
  const { file, changed } = writeFile(
    systemId,
    `plugins/${name}/plugin.yaml`,
    text,
    'user:demo',
    b.reason || 'plugin configured in the Plugins tab',
  );
  const linked = linkComponent(systemId, name, card, b.component ?? null);
  return {
    name,
    path: file.path,
    version: file.version,
    changed,
    card: card as PluginCard,
    architecture_updated: linked,
  };
}

const pluginRoutes: MockRoute[] = [
  {
    method: 'GET',
    path: '/v1/systems/:systemId/plugins',
    handler: ({ params }) => (mockSystems.get(params.systemId) ? systemGraph(params.systemId) : notFound()),
  },
  {
    method: 'GET',
    path: '/v1/systems/:systemId/plugins/defaults',
    handler: ({ params, query }) =>
      mockSystems.get(params.systemId) ? pluginDefaults(params.systemId, query) : notFound(),
  },
  {
    method: 'PUT',
    path: '/v1/systems/:systemId/plugins/:name',
    handler: ({ params, body }) =>
      mockSystems.get(params.systemId) ? savePlugin(params.systemId, params.name, body) : notFound(),
  },
];

export const routes: MockRoute[] = [
  ...pluginRoutes,
  { method: 'GET', path: '/v1/systems', handler: () => mockSystems.list() },
  {
    method: 'GET',
    path: '/v1/systems/:systemId',
    handler: ({ params }) => mockSystems.get(params.systemId) ?? notFound(),
  },
  {
    method: 'GET',
    path: '/v1/systems/:systemId/files',
    handler: ({ params, query }) =>
      mockSystems.get(params.systemId) ? mockSystems.tree(params.systemId, query.get('prefix')) : notFound(),
  },
  {
    method: 'GET',
    path: '/v1/systems/:systemId/events',
    handler: ({ params }) => mockSystems.events(params.systemId),
  },
  {
    method: 'GET',
    path: '/v1/systems/:systemId/files/*path/versions',
    handler: ({ params }) => {
      const v = mockSystems.versions(params.systemId, params.path);
      return v.length ? v : mockError(404, 'File not found');
    },
  },
  {
    method: 'GET',
    path: '/v1/systems/:systemId/files/*path',
    handler: ({ params, query }) => {
      const version = query.get('version');
      const f = mockSystems.read(params.systemId, params.path, version ? Number(version) : undefined);
      if (!f) return mockError(404, 'File not found');
      return query.get('format') === 'json' ? f : new MockResponse(200, f.text, f.contentType);
    },
  },
  {
    method: 'PUT',
    path: '/v1/systems/:systemId/files/*path',
    handler: async ({ params, body }) => {
      if (!mockSystems.get(params.systemId)) return notFound();
      const { text, reason } = await bodyText(body);
      return writeFile(params.systemId, params.path, text, 'user:demo', reason);
    },
  },
];
