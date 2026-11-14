// The chain-of-thought header title (ported from magenticx tests/agentic_ui/cot-live-title.test.ts).
import { describe, expect, it } from 'vitest';
import { finalCoTTitle, liveCoTTitle, thoughtTitle, withoutThoughtTitle } from './cotTitle';
import type { ThinkingItem } from './timeline';

const thought = (text: string): ThinkingItem => ({ kind: 'thought', id: `t-${text}`, text });
const tool = (name: string, args: unknown = {}): ThinkingItem => ({
  kind: 'tool',
  id: `tool-${name}`,
  name,
  argsText: JSON.stringify(args),
  state: 'input-available',
});

describe('thoughtTitle', () => {
  it("takes a reasoning summary's bold headline", () => {
    expect(thoughtTitle('**Weighing the sources**\n\nI need to compare…')).toBe('Weighing the sources');
  });

  it('falls back to the first line without markdown', () => {
    expect(thoughtTitle('\n## Planning the *search*\nmore')).toBe('Planning the search');
  });

  it('clips a long line', () => {
    const title = thoughtTitle('x'.repeat(200));
    expect(title.length).toBeLessThanOrEqual(72);
    expect(title.endsWith('…')).toBe(true);
  });

  it('drops the headline from the body', () => {
    expect(withoutThoughtTitle('**Title**\n\nBody')).toBe('Body');
    expect(withoutThoughtTitle('No title')).toBe('No title');
  });
});

describe('liveCoTTitle', () => {
  it('names the latest thought', () => {
    expect(liveCoTTitle([thought('**One**\n\na'), thought('**Two**\n\nb')])).toBe('Two');
  });

  it('names a known tool by its step title', () => {
    expect(liveCoTTitle([thought('**One**'), tool('read_file', { file_path: '/docs/report.pdf' })])).toBe(
      'Read report.pdf',
    );
  });

  it('says which tool is in use otherwise', () => {
    expect(liveCoTTitle([tool('fetch_weather')])).toBe('Using Fetch weather');
  });

  it('reads the {name, args} envelope too', () => {
    const item: ThinkingItem = {
      kind: 'tool',
      id: 'x',
      name: 'execute',
      argsText: JSON.stringify({ name: 'execute', args: { command: 'pytest -q' } }),
      state: 'input-available',
    };
    expect(liveCoTTitle([item])).toBe('Run pytest -q');
  });

  it('skips an empty thought and has nothing to say for an empty block', () => {
    expect(liveCoTTitle([thought('**Found it**'), thought('')])).toBe('Found it');
    expect(liveCoTTitle([])).toBeNull();
  });
});

describe('finalCoTTitle', () => {
  it("is the last thought's headline when the block ends on a thought", () => {
    expect(finalCoTTitle([tool('read_file', { file_path: '/a.pdf' }), thought('**Settled**\n\nx')])).toBe(
      'Settled',
    );
  });

  it('says what a tool did when the block ends on a tool', () => {
    expect(finalCoTTitle([thought('**Planning**'), tool('read_file', { file_path: '/a.pdf' })])).toBe(
      'Read a.pdf',
    );
    expect(finalCoTTitle([thought('**Planning**'), tool('fetch_weather')])).toBe('Used Fetch weather');
    expect(finalCoTTitle([tool('task', { subagent_type: 'evidence-checker' })])).toBe(
      'Hand off to the evidence-checker sub-agent',
    );
  });

  it('is null when an approval closes the block', () => {
    expect(
      finalCoTTitle([{ kind: 'hitl', id: 'h', threadId: 't', content: {}, status: 'approved' }]),
    ).toBeNull();
  });
});
