// LLM reports write thresholds as LaTeX (`$\le 0.05$`, `$\ge 0.8$`). We render no math, so
// turn those spans into plain symbols. Only `$…$` spans holding a `\command` are touched, so
// prices like "$500" stay as they are.

const SYMBOLS: Record<string, string> = {
  le: '≤',
  leq: '≤',
  ge: '≥',
  geq: '≥',
  lt: '<',
  gt: '>',
  neq: '≠',
  ne: '≠',
  approx: '≈',
  pm: '±',
  times: '×',
  cdot: '·',
  to: '→',
  rightarrow: '→',
  infty: '∞',
  alpha: 'α',
  beta: 'β',
  sigma: 'σ',
  mu: 'μ',
  Delta: 'Δ',
  delta: 'δ',
  '%': '%',
};

function symbolise(tex: string): string {
  return tex
    .replace(/\\([A-Za-z]+|%)/g, (m, name: string) => SYMBOLS[name] ?? m)
    .replace(/\\text\{([^}]*)\}/g, '$1')
    .replace(/[{}]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/** `threshold $\le 0.05$` → `threshold ≤ 0.05`. */
export function plainMath(text: string): string {
  return text.replace(/\$([^$\n]{1,80})\$/g, (whole, inner: string) =>
    /\\[A-Za-z%]/.test(inner) ? symbolise(inner) : whole,
  );
}
