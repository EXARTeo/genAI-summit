/**
 * The chain of thought's header title (port of magenticx `features/chat/lib/cotTitle.ts`).
 * Live, it names the latest step ("Checking the finding", "Read selection_rates.csv",
 * "Using fetch_weather"); finished, it keeps its last step's title with the time after it.
 */
import type { ThinkingItem } from './timeline';
import { humaniseName, parseToolArgs, titleFromArgs, toolTitle } from './toolPresentation';

/** Longest title before it is clipped with an ellipsis. */
const MAX_TITLE = 72;

const clipTitle = (text: string): string =>
  text.length > MAX_TITLE ? `${text.slice(0, MAX_TITLE - 1).trimEnd()}…` : text;

/**
 * A thought's headline: a reasoning summary's opening bold title (`**Weighing the sources**`),
 * else its first line without markdown markers. Empty when there is no text yet.
 */
export const thoughtTitle = (text: string): string => {
  const bold = /^\s*\*\*(.+?)\*\*/.exec(text);
  if (bold) return clipTitle(bold[1].trim());
  const firstLine = text.split('\n').find((line) => line.trim()) ?? '';
  return clipTitle(firstLine.replace(/[*_`#>]+/g, '').trim());
};

/** A thought's text without its opening bold title (the header already shows it). */
export const withoutThoughtTitle = (text: string): string =>
  text.replace(/^\s*\*\*.+?\*\*[ \t]*(?:\r?\n)*/, '');

/** The latest step's title, worded as in progress or (`done`) as done. */
function stepTitle(items: readonly ThinkingItem[], done: boolean): string | null {
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (item.kind === 'thought') {
      const title = thoughtTitle(item.text);
      if (title) return title;
      continue;
    }
    if (item.kind === 'tool') {
      const args = parseToolArgs(item.argsText);
      const known = titleFromArgs(item.name, args);
      if (known) return clipTitle(known);
      const label = toolTitle(item.name, args);
      const name = label === item.name ? humaniseName(item.name) : label;
      return clipTitle(`${done ? 'Used' : 'Using'} ${name}`);
    }
    return null; // an approval or a question: the caller has its own words for those
  }
  return null;
}

/** What a finished chain of thought keeps as its title; null → "Thought for Xs". */
export const finalCoTTitle = (items: readonly ThinkingItem[]): string | null => stepTitle(items, true);

/** What a live chain of thought says it is doing; null → "Thinking…". */
export const liveCoTTitle = (items: readonly ThinkingItem[]): string | null => stepTitle(items, false);
