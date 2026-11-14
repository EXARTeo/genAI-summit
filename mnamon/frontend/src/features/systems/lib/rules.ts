import type { BusinessRule } from './types';

/**
 * Turn a plugin's business-rules.md into rule items: every top-level bullet is a
 * rule; the `##` heading it sits under decides its kind ("valid" → hard, "polic" →
 * policy, anything else → soft). Wrapped bullet lines are joined.
 */
export function parseBusinessRules(markdown: string, plugin: string): BusinessRule[] {
  const rules: BusinessRule[] = [];
  let heading = '';
  let current: BusinessRule | null = null;
  const kindFor = (h: string): BusinessRule['kind'] =>
    /polic/i.test(h) ? 'policy' : /valid|must|constraint/i.test(h) ? 'hard' : 'soft';

  for (const raw of markdown.split('\n')) {
    const line = raw.trimEnd();
    const h = /^#{2,3}\s+(.*)$/.exec(line);
    if (h) {
      heading = h[1].trim();
      current = null;
      continue;
    }
    const bullet = /^[-*]\s+(.*)$/.exec(line);
    if (bullet && heading) {
      current = {
        id: `${plugin}-${rules.length + 1}`,
        plugin,
        title: heading,
        kind: kindFor(heading),
        text: bullet[1].trim(),
      };
      rules.push(current);
      continue;
    }
    if (current && /^\s{2,}\S/.test(raw)) current.text += ` ${line.trim()}`;
    else if (!line.trim()) current = null;
  }
  return rules;
}

const UI_HEADING: Record<BusinessRule['kind'], string> = {
  hard: 'Constraints added in the UI',
  soft: 'Soft rules added in the UI',
  policy: 'Policies added in the UI',
};

/** The plugin file a business rule lives in. */
export function businessRulesPath(plugin: string): string {
  return `plugins/${plugin}/data/business-rules.md`;
}

/**
 * Append a rule to a business-rules.md as a bullet under a "… added in the UI" heading
 * whose wording makes `parseBusinessRules` read it back with the same kind.
 */
export function appendRule(markdown: string, kind: BusinessRule['kind'], text: string): string {
  const heading = `## ${UI_HEADING[kind]}`;
  const bullet = `- ${text.replace(/\s+/g, ' ').trim()}`;
  const lines = markdown.replace(/\s+$/, '').split('\n');
  const at = lines.indexOf(heading);
  if (at < 0) return [...(markdown.trim() ? [...lines, ''] : []), heading, '', bullet, ''].join('\n');
  let end = at + 1;
  while (end < lines.length && !/^#{1,3}\s/.test(lines[end])) end++;
  while (end > at + 1 && !lines[end - 1].trim()) end--;
  lines.splice(end, 0, bullet);
  return `${lines.join('\n')}\n`;
}
