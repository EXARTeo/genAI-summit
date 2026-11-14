/**
 * Slash commands (port of magenticx `lib/slashCommands.ts`, mapped to what our backend can do).
 * Typing `/` at the start of the draft opens the menu; a command either runs an action
 * (`/rename Title`) or, for an agent command, picks the agent for the next message.
 */
export interface SlashCommand {
  name: string;
  description: string;
  /** Takes the rest of the line as its argument. */
  arg?: string;
  /** Needs an open conversation. */
  needsConversation?: boolean;
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { name: 'new', description: 'Start a new chat' },
  { name: 'rename', description: 'Rename this chat', arg: 'title', needsConversation: true },
  { name: 'pin', description: 'Pin or unpin this chat', needsConversation: true },
  { name: 'archive', description: 'Archive this chat', needsConversation: true },
  { name: 'retry', description: 'Ask again for the last answer', needsConversation: true },
  { name: 'stop', description: 'Stop the running answer', needsConversation: true },
  { name: 'agent', description: 'Talk to another agent', arg: 'agent' },
  { name: 'search', description: 'Search your chats', arg: 'query' },
];

/** `/ren` → the matching commands; null when the draft is not a command being typed. */
export function matchCommands(draft: string, hasConversation: boolean): SlashCommand[] | null {
  const m = /^\/(\w*)$/.exec(draft);
  if (!m) return null;
  const q = m[1].toLowerCase();
  return SLASH_COMMANDS.filter((c) => c.name.startsWith(q) && (hasConversation || !c.needsConversation));
}

/** A complete command in the draft (`/rename Better title`), or null. */
export function parseCommand(draft: string): { command: SlashCommand; arg: string } | null {
  const m = /^\/(\w+)(?:\s+([\s\S]*))?$/.exec(draft.trim());
  if (!m) return null;
  const command = SLASH_COMMANDS.find((c) => c.name === m[1].toLowerCase());
  return command ? { command, arg: (m[2] ?? '').trim() } : null;
}
