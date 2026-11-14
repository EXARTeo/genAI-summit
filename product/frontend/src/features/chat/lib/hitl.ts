/**
 * HITL interrupt parsing (port of magenticx `features/inference/hitl.ts`).
 *
 * A LangChain HITL interrupt arrives as `CUSTOM HITL_INTERRUPT` whose `value.interrupt` is
 * `{id, value: {action_requests: [{action|name, args, description}], review_configs}}`. An
 * `ask_user` interrupt is the agent asking questions: `{id, value: {type: 'ask_user', questions}}`.
 * Shapes vary across agents, so every access here is defensive.
 */

export interface HitlActionRequest {
  toolName?: string;
  args?: unknown;
  description?: string;
}

export interface AskUserQuestion {
  id: string;
  question: string;
  options: string[];
  multiple: boolean;
}

export interface AskUserAnswer {
  id: string;
  selected: string[];
  text: string;
}

export const ASK_USER_MAX_QUESTIONS = 3;
export const ASK_USER_MAX_OPTIONS = 6;

const GENERIC_DESCRIPTION_PREFIX = 'Tool execution requires approval';

/** LangChain's default description restates the tool and args the UI already shows: drop it. */
export function isGenericHitlDescription(description: string | undefined): boolean {
  const text = description?.trim() ?? '';
  if (!text) return true;
  if (!text.startsWith(GENERIC_DESCRIPTION_PREFIX)) return false;
  const rest = text.slice(GENERIC_DESCRIPTION_PREFIX.length).trim();
  return rest === '' || rest.startsWith('Tool:');
}

const asRecord = (v: unknown): Record<string, unknown> | null =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : null;

function interruptValue(content: unknown): Record<string, unknown> | null {
  const c = asRecord(content);
  if (!c) return null;
  return asRecord(c.value) ?? c;
}

/** The gated tool calls of an approval interrupt, in order (empty for anything else). */
export function hitlActionRequests(content: unknown): HitlActionRequest[] {
  const value = interruptValue(content);
  const requests = value?.action_requests;
  if (!Array.isArray(requests)) return [];
  return requests.map((request) => {
    const r = asRecord(request) ?? {};
    const toolName =
      typeof r.action === 'string' ? r.action : typeof r.name === 'string' ? r.name : undefined;
    const description = typeof r.description === 'string' ? r.description.trim() : undefined;
    return { toolName, args: r.args ?? undefined, description };
  });
}

export function isAskUserInterrupt(content: unknown): boolean {
  return interruptValue(content)?.type === 'ask_user';
}

const optionText = (o: unknown): string =>
  typeof o === 'string' ? o.trim() : typeof o === 'number' ? String(o) : '';

/** The questions of an `ask_user` interrupt: trimmed, deduped, capped, ids filled by position. */
export function askUserQuestions(content: unknown): AskUserQuestion[] {
  const value = interruptValue(content);
  if (value?.type !== 'ask_user' || !Array.isArray(value.questions)) return [];
  const out: AskUserQuestion[] = [];
  const ids = new Set<string>();
  for (const entry of value.questions) {
    if (out.length >= ASK_USER_MAX_QUESTIONS) break;
    const q = asRecord(entry);
    const question = typeof q?.question === 'string' ? q.question.trim() : '';
    if (!q || !question) continue;
    const rawOptions = Array.isArray(q.options) ? q.options : [];
    const options = [...new Set(rawOptions.map(optionText).filter(Boolean))].slice(0, ASK_USER_MAX_OPTIONS);
    const rawId = q.id == null ? '' : String(q.id).trim();
    const id = rawId && !ids.has(rawId) ? rawId : `q${out.length + 1}`;
    ids.add(id);
    out.push({ id, question, options, multiple: Boolean(q.multiple) && options.length > 0 });
  }
  return out;
}

/** `answers` echoed by `BRIDGE_HITL_RESOLVED` for an `ask_user` interrupt. */
export function askUserAnswers(raw: unknown): AskUserAnswer[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const out: AskUserAnswer[] = [];
  for (const entry of raw) {
    const a = asRecord(entry);
    if (!a || a.id == null) continue;
    out.push({
      id: String(a.id),
      selected: (Array.isArray(a.selected) ? a.selected : []).map(optionText).filter(Boolean),
      text: typeof a.text === 'string' ? a.text.trim() : '',
    });
  }
  return out.length ? out : undefined;
}

export const isAskUserAnswered = (a: AskUserAnswer | undefined) =>
  Boolean(a && (a.selected.length > 0 || a.text.trim()));

export function formatArgs(args: unknown): string {
  if (args === undefined || args === null) return '';
  if (typeof args === 'string') return args;
  try {
    return JSON.stringify(args, null, 2);
  } catch {
    return String(args);
  }
}

/** Human title for a tool name: `search_regulation` → `Search regulation`. */
export function humanizeToolName(name: string | undefined): string {
  if (!name) return 'Tool';
  const words = name
    .replace(/^mcp__[^_]+__/, '')
    .replace(/[_-]+/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .trim()
    .toLowerCase();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'Tool';
}

/** `research-analyst` → `Research Analyst`. */
export function toTitleCase(value?: string): string | undefined {
  if (!value) return undefined;
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((p) => p.charAt(0).toUpperCase() + p.slice(1))
    .join(' ');
}

/** One line for an approval card: "Approve 2 actions" / "Approve write_file". */
export function approvalHeadline(actions: HitlActionRequest[]): string {
  if (actions.length > 1) return `The agent wants to run ${actions.length} actions`;
  const name = actions[0]?.toolName;
  return name ? `The agent wants to run ${humanizeToolName(name).toLowerCase()}` : 'The agent needs your approval';
}
