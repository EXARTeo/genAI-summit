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
        status: 'active',
      };
      rules.push(current);
      continue;
    }
    if (current && /^\s{2,}\S/.test(raw)) current.text += ` ${line.trim()}`;
    else if (!line.trim()) current = null;
  }
  return rules;
}

export function slugify(s: string): string {
  return (
    s
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 48) || 'rule'
  );
}

/** The YAML stored as a memory proposal for a new business rule. */
export function ruleProposalYaml(v: {
  systemId: string;
  plugin: string;
  kind: string;
  text: string;
  rationale: string;
}): string {
  const q = (s: string) => JSON.stringify(s);
  return [
    `scope: system:${v.systemId}`,
    'kind: business_rule',
    `applies_to: {plugin: ${q(v.plugin)}}`,
    `rule_kind: ${v.kind}`,
    `rule: ${q(v.text)}`,
    `rationale: ${q(v.rationale)}`,
    'status: proposed',
    'author: user:ui',
    '',
  ].join('\n');
}
