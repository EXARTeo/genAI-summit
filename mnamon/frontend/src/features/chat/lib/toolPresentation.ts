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
