/**
 * What a tool step says about itself in the chain of thought (port of magenticx
 * `features/chat/lib/toolPresentation.ts`, condensed to the tools our agents use).
 *
 * A step is titled from its arguments where the tool is known ("Read selection_rates.csv",
 * "Run pytest -q"), else by its raw name, like magenticx. Pure functions only; the rendering
 * lives in `message_parts/ToolCallView.tsx`. Every parser is tolerant: anything not recognised
 * yields `null` / `undefined` and the caller falls back to the generic view.
 */

export type ToolArgs = Record<string, unknown>;

/** The parsed arguments as an object, or null while they stream / if malformed. */
export const asToolArgs = (args: unknown): ToolArgs | null =>
  args && typeof args === 'object' && !Array.isArray(args) ? (args as ToolArgs) : null;

const str = (args: ToolArgs | null, key: string): string =>
  typeof args?.[key] === 'string' ? (args[key] as string) : '';

/** Last path segment: `/systems/SYS-001/data/rates.csv` → `rates.csv`. */
export const basename = (path: string): string => {
  const trimmed = path.replace(/\/+$/, '');
  const name = trimmed.slice(trimmed.lastIndexOf('/') + 1);
  return name || path || '/';
};

/** A directory without its leading/trailing slashes; the root stays `/`. */
const displayDir = (path: string): string => path.replace(/^\/+|\/+$/g, '') || '/';

const clip = (text: string, max = 60): string => (text.length > max ? `${text.slice(0, max - 1)}…` : text);

/**
 * `general-purpose` → `general-purpose`, `research_agent` → `research`: the sub-agent's name as
 * it reads inside "the … sub-agent", without a trailing "agent" that would say it twice.
 */
export const subagentName = (type: string): string =>
  type
    .replace(/[_\s]+/g, ' ')
    .replace(/[-\s]?(sub[-\s]?)?agent$/i, '')
    .trim() || type;

const pathOf = (a: ToolArgs | null) => str(a, 'file_path') || str(a, 'path');
const systemOf = (a: ToolArgs | null) => str(a, 'system_id');

/** `AIA.10.2.f` → `Art. 10(2)(f)`; other ids unchanged. */
export const provisionLabel = (id: string): string => {
  const m = /^AIA\.(\d+[a-z]?)((?:\.[0-9a-z]+)*)$/i.exec(id.trim());
  if (!m) return id;
  const sub = m[2]
    ? m[2]
        .slice(1)
        .split('.')
        .map((p) => `(${p})`)
        .join('')
    : '';
  return `Art. ${m[1]}${sub}`;
};

const TITLES: Record<string, (args: ToolArgs | null) => string | null> = {
  read_file: (a) => (pathOf(a) ? `Read ${basename(pathOf(a))}` : null),
  read_system_file: (a) => (pathOf(a) ? `Read ${basename(pathOf(a))}` : null),
  ls: (a) => `List ${displayDir(str(a, 'path') || '/')}`,
  glob: (a) => (str(a, 'pattern') ? `Find ${str(a, 'pattern')}` : null),
  grep: (a) => {
    const pattern = str(a, 'pattern');
    if (!pattern) return null;
    const path = str(a, 'path');
    return `Search "${clip(pattern, 40)}"${path ? ` in ${displayDir(path)}` : ''}`;
  },
  write_file: (a) => (pathOf(a) ? `Write ${basename(pathOf(a))}` : null),
  edit_file: (a) => (pathOf(a) ? `Edit ${basename(pathOf(a))}` : null),
  write_finding_note: (a) => (pathOf(a) ? `Write ${basename(pathOf(a))}` : null),
  execute: (a) => (str(a, 'command') ? `Run ${clip(str(a, 'command'))}` : null),
  run_test: (a) => (str(a, 'test') ? `Run test ${clip(str(a, 'test'), 50)}` : null),
  search_regulation: (a) =>
    str(a, 'query') ? `Search the regulation for "${clip(str(a, 'query'), 50)}"` : null,
  lookup_provision: (a) =>
    str(a, 'provision_id') ? `Look up ${provisionLabel(str(a, 'provision_id'))}` : 'Look up a provision',
  list_systems: () => 'List systems',
  list_audits: (a) => (systemOf(a) ? `List the audits of ${systemOf(a)}` : 'List audits'),
  list_system_files: (a) => (systemOf(a) ? `List ${systemOf(a)}'s files` : "List the system's files"),
  read_audit: () => 'Open the audit',
  read_audit_artifact: () => 'Read an audit result',
  propose_system_note: (a) =>
    str(a, 'name') ? `Propose a note "${clip(str(a, 'name'), 40)}"` : 'Propose a note',
  start_audit: (a) => (systemOf(a) ? `Start an audit of ${systemOf(a)}` : 'Start an audit'),
  view_image: (a) => (pathOf(a) ? `View ${basename(pathOf(a))}` : 'View an image'),
  remember: (a) => (str(a, 'name') ? `Remembered "${str(a, 'name')}"` : null),
  forget: (a) => (str(a, 'name') ? `Forgot "${str(a, 'name')}"` : null),
  write_todos: () => 'Update the plan',
  task: (a) =>
    str(a, 'subagent_type') ? `Hand off to the ${subagentName(str(a, 'subagent_type'))} sub-agent` : null,
};

/**
 * A step's arguments from its streamed `argsText`: the JSON args (or a `{name, args}` envelope's
 * `args`) once complete, the raw text while it still streams, null when empty.
 */
export const parseToolArgs = (argsText: string): unknown => {
  const trimmed = argsText.trim();
  if (!trimmed) return null;
  try {
    const parsed: unknown = JSON.parse(trimmed);
    const obj = asToolArgs(parsed);
    if (obj && 'args' in obj && 'name' in obj) return obj.args;
    return parsed;
  } catch {
    return trimmed;
  }
};

/** A title built from the call's arguments, for the tools we know; else null. */
export const titleFromArgs = (name: string, args: unknown): string | null =>
  TITLES[name]?.(asToolArgs(args)) || null;

/** The step's title: built from its arguments where we know the tool, else its raw name. */
export const toolTitle = (name: string, args: unknown): string => titleFromArgs(name, args) || name;

/** `fetch_weather` → `Fetch weather`, `maxResults` → `Max results`. */
export const humaniseName = (name: string): string => {
  const words = name
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[-_./]+/g, ' ')
    .trim()
    .toLowerCase();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : name;
};

/** Full path (or command) for the title's hover text, where the title shortened it. */
export const toolTitleHint = (name: string, args: unknown): string | undefined => {
  const a = asToolArgs(args);
  const path = pathOf(a);
  if (path) return path;
  if (name === 'execute') return str(a, 'command') || undefined;
  return undefined;
};

/** Shell-like tools read as a terminal (`$ command`, output, exit code). */
export const isShellTool = (name: string): boolean => name === 'execute' || name === 'shell';

/** `execute` output with its trailing `[Command … with exit code N]` split off. */
export const parseCommandOutput = (
  result: string | undefined,
): { output: string; exitCode?: number } | null => {
  if (result === undefined) return null;
  const match = /\n?\[Command (?:succeeded|failed) with exit code (-?\d+)\]\s*$/.exec(result);
  if (!match) return { output: result };
  return { output: result.slice(0, match.index), exitCode: Number(match[1]) };
};

const plural = (count: number, one: string, many = `${one}s`): string =>
  `${count} ${count === 1 ? one : many}`;

/** Short facts for the title row (exit code, item count, sources found). */
export const toolMeta = (name: string, result: string | undefined, sources?: number): string | undefined => {
  if (sources) return plural(sources, 'source');
  if (result === undefined) return undefined;
  if (isShellTool(name)) {
    const out = parseCommandOutput(result);
    return out?.exitCode !== undefined ? `exit ${out.exitCode}` : undefined;
  }
  if (name === 'ls' || name === 'glob') {
    const text = result.trim();
    if (!text.startsWith('[')) return undefined;
    const count = (text.match(/['"]\//g) ?? []).length;
    return plural(count, name === 'ls' ? 'item' : 'file');
  }
  return undefined;
};

/**
 * Read, list and search tools: the step shows a one-line summary of what came back instead of
 * expandable Parameters / Result panes (view_image shows the image itself).
 */
const QUIET_TOOLS = new Set([
  'read_file',
  'read_system_file',
  'read_audit',
  'read_audit_artifact',
  'ls',
  'glob',
  'grep',
  'list_systems',
  'list_audits',
  'list_system_files',
  'search_regulation',
  'lookup_provision',
  'view_image',
]);

export const isQuietTool = (name: string): boolean => QUIET_TOOLS.has(name);

const parseJson = (text: string): unknown => {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
};

const listPreview = (labels: string[], max = 3): string =>
  labels.length > max ? `${labels.slice(0, max).join(', ')}, …` : labels.join(', ');

const countLines = (text: string): number => text.split('\n').filter((l) => l.trim()).length;

/** One line saying what a quiet tool brought back, e.g. "4 systems: SYS-001 CV Screener, …". */
export const toolSummary = (name: string, result: string | undefined): string | undefined => {
  if (result === undefined) return undefined;
  const text = result.trim();
  if (!text) return 'Nothing returned';
  if (/^(Could not|Search failed|No audit given|No system)/.test(text)) return clip(text, 140);
  const data = parseJson(text);
  const rec = (v: unknown) => (v && typeof v === 'object' ? (v as Record<string, unknown>) : null);
  switch (name) {
    case 'list_systems': {
      if (!Array.isArray(data)) break;
      const names = data.map((s) => [rec(s)?.id, rec(s)?.name].filter(Boolean).join(' '));
      return `${plural(data.length, 'system')}: ${listPreview(names)}`;
    }
    case 'list_audits':
      return Array.isArray(data) ? plural(data.length, 'audit') : undefined;
    case 'list_system_files': {
      const files = text
        .split('\n')
        .slice(1)
        .filter((l) => l.trim() && l.trim() !== '(no files)');
      return plural(files.length, 'file');
    }
    case 'read_system_file':
    case 'read_file': {
      const body = typeof data === 'string' ? data : text;
      return `${plural(countLines(body), 'line')} read`;
    }
    case 'read_audit': {
      const a = rec(data);
      if (!a) break;
      const parts = [a.stage && `stage ${String(a.stage)}`, a.status && String(a.status)].filter(Boolean);
      return parts.length ? `Audit ${parts.join(' · ')}` : 'Audit opened';
    }
    case 'read_audit_artifact': {
      const a = rec(data);
      return a?.kind
        ? `${String(a.kind).replace(/_/g, ' ')}${a.version ? ` v${String(a.version)}` : ''}`
        : 'Result read';
    }
    case 'lookup_provision': {
      const p = rec(data);
      if (!p) break;
      const label = provisionLabel(String(p.id ?? ''));
      return p.title ? `${label}: ${String(p.title)}` : label;
    }
    case 'search_regulation': {
      const items = rec(data)?.items;
      if (!Array.isArray(items)) break;
      if (!items.length) return 'No provisions found';
      const labels = items.map((i) => {
        const r = rec(i);
        const label = String(r?.label ?? provisionLabel(String(r?.id ?? '')));
        return r?.title ? `${label} ${String(r.title)}` : label;
      });
      return `${plural(items.length, 'provision')}: ${listPreview(labels)}`;
    }
    case 'grep':
      return /no matches/i.test(text) ? 'No matches' : plural(countLines(text), 'match', 'matches');
    case 'ls':
    case 'glob':
      return toolMeta(name, result);
    case 'view_image':
      return undefined;
  }
  return undefined;
};

/**
 * A failed quiet tool's one line: the error without the "Tool 'x' failed:" prefix or a
 * Python exception class, e.g. "Couldn't read it (AttributeError)" → "Couldn't complete this step".
 */
export const toolFailureLine = (result: string | undefined): string => {
  const text = (result ?? '').trim().replace(/^Tool '[^']+' failed:\s*/i, '');
  if (!text || /^[A-Z]\w*(Error|Exception)\b/.test(text)) return "Couldn't complete this step";
  return clip(text, 140);
};

/** Image thumbnails a tool result carries (`preview_base64` blocks, e.g. view_image). */
export const toolImages = (result: string | undefined): { src: string; alt: string }[] => {
  if (!result || !result.includes('preview_base64')) return [];
  const out: { src: string; alt: string }[] = [];
  const walk = (v: unknown) => {
    if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') {
      const r = v as Record<string, unknown>;
      if (typeof r.preview_base64 === 'string') {
        const mime = typeof r.mime_type === 'string' ? r.mime_type : 'image/png';
        out.push({ src: `data:${mime};base64,${r.preview_base64}`, alt: String(r.name ?? 'Image') });
      }
      Object.values(r).forEach(walk);
    }
  };
  walk(parseJson(result));
  return out;
};

/** A tool's run time: `850ms`, `2.9s`, `12s`. */
export const toolDurationLabel = (startedAt?: number, endedAt?: number): string | undefined => {
  if (typeof startedAt !== 'number' || typeof endedAt !== 'number') return undefined;
  const ms = endedAt - startedAt;
  if (ms < 0) return undefined;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)}s`;
};

/** A chain of thought's time: `7s`, `1m 4s`. */
export const formatThinkingDuration = (startedAt?: number, endedAt?: number): string | null => {
  if (typeof startedAt !== 'number' || typeof endedAt !== 'number' || endedAt < startedAt) return null;
  const seconds = (endedAt - startedAt) / 1000;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return minutes > 0 ? `${minutes}m ${rest}s` : `${rest}s`;
};

/** How long a settled sub-agent worked: `<1s`, `42s`, `3m 05s`. */
export const formatSubagentDuration = (startedAt?: number, endedAt?: number): string | null => {
  if (typeof startedAt !== 'number' || typeof endedAt !== 'number' || endedAt < startedAt) return null;
  const seconds = Math.round((endedAt - startedAt) / 1000);
  if (seconds < 1) return '<1s';
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${String(seconds % 60).padStart(2, '0')}s`;
};
