/**
 * Demo fixtures are written against one fixed afternoon. `mockTime` shifts them so the
 * newest fixture timestamp (`ANCHOR`) lands a few minutes before the page loaded: every
 * mock event is in the past ("12 minutes ago"), with the original spacing kept.
 */
const ANCHOR = Date.parse('2026-11-14T18:10:00Z');
const OFFSET = Date.now() - 4 * 60_000 - ANCHOR;

export function mockTime(iso: string): string {
  return new Date(Date.parse(iso) + OFFSET).toISOString();
}
