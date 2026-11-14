/**
 * Which catalog agents the chat may talk to. Workflows (the audit pipeline needs a system and an
 * audit, not a conversation) are never offered or auto-selected: the catalog marks them with
 * `chat: false` or `kind: "workflow"`; until every catalog does, `audit-pipeline` is excluded by slug.
 */
import type { AgentManifest } from './types';

const WORKFLOW_SLUGS = new Set(['audit-pipeline']);

export function isChatAgent(agent: AgentManifest | null | undefined): boolean {
  if (!agent) return false;
  if (agent.chat === false) return false;
  if (agent.kind === 'workflow') return false;
  if (WORKFLOW_SLUGS.has(agent.slug) && agent.chat !== true) return false;
  return true;
}

export const chatAgents = (agents: readonly AgentManifest[]): AgentManifest[] => agents.filter(isChatAgent);

/** The catalog's `default: true` chat agent, else the first chat agent, else none. */
export function defaultChatAgent(agents: readonly AgentManifest[]): AgentManifest | null {
  const usable = chatAgents(agents);
  return usable.find((a) => a.default) ?? usable[0] ?? null;
}
