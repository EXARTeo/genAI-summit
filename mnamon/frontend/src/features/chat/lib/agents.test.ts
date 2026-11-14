import { describe, expect, it } from 'vitest';
import { chatAgents, defaultChatAgent, isChatAgent } from './agents';

const pipeline = { slug: 'audit-pipeline', name: 'Audit pipeline', default: false };
const mnamon = { slug: 'mnamon', name: 'Mnamon', default: true };
const other = { slug: 'helper', name: 'Helper' };

describe('chat agents', () => {
  it('never offers a workflow', () => {
    expect(isChatAgent(pipeline)).toBe(false);
    expect(isChatAgent({ ...other, chat: false })).toBe(false);
    expect(isChatAgent({ ...other, kind: 'workflow' })).toBe(false);
    expect(isChatAgent(other)).toBe(true);
    expect(chatAgents([pipeline, other])).toEqual([other]);
  });

  it('picks the default chat agent, else the first one, else none', () => {
    expect(defaultChatAgent([pipeline, other, mnamon])).toBe(mnamon);
    expect(defaultChatAgent([pipeline, other])).toBe(other);
    expect(defaultChatAgent([{ ...pipeline, default: true }])).toBeNull();
    expect(defaultChatAgent([])).toBeNull();
  });
});
