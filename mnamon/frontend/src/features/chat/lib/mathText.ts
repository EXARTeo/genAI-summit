/**
 * Models sometimes answer with inline LaTeX (`$\le 0.02$`, `\(\ge 0.80\)`). The chat has no math
 * renderer, so simple inline math becomes plain Unicode text (`≤ 0.02`). Code spans and fences are
 * left alone; a `$` amount without a LaTeX command or sub/superscript (`$5`, `$1 to $2`) is not math.
 */

const SYMBOLS: Record<string, string> = {
  le: '≤',
  leq: '≤',
  ge: '≥',
  geq: '≥',
  ne: '≠',
  neq: '≠',
  approx: '≈',
  sim: '~',
  times: '×',
  cdot: '·',
  pm: '±',
  to: '→',
  rightarrow: '→',
  Rightarrow: '⇒',
  leftarrow: '←',
  infty: '∞',
  sum: 'Σ',
  Delta: 'Δ',
  delta: 'δ',
  alpha: 'α',
  beta: 'β',
  epsilon: 'ε',
  mu: 'μ',
  sigma: 'σ',
  lambda: 'λ',
  in: '∈',
  ldots: '…',
  dots: '…',
};

/** One inline math body (without the delimiters) as plain text. */
export function latexToText(body: string): string {
  let s = body;
  for (let i = 0; i < 3; i++) {
    s = s.replace(/\\frac\{([^{}]*)\}\{([^{}]*)\}/g, '$1/$2');
    s = s.replace(/\\(?:text|mathrm|mathbf|mathit|operatorname)\{([^{}]*)\}/g, '$1');
  }
  s = s.replace(/\\([%$&#_{}])/g, '$1');
  s = s.replace(/\\([A-Za-z]+)/g, (m, name: string) => SYMBOLS[name] ?? (name === 'quad' ? ' ' : m));
  s = s.replace(/\^\{([^{}]*)\}/g, '^$1').replace(/_\{([^{}]*)\}/g, '_$1');
  s = s.replace(/[{}]/g, '');
  return s.replace(/\s+/g, ' ').trim();
}

const looksLikeMath = (body: string) => /\\[A-Za-z%]|[\^_]\{/.test(body);

function convertProse(text: string): string {
  return text
    .replace(/\\\((.+?)\\\)/g, (_m, body: string) => latexToText(body))
    .replace(/\$\$([^$\n]+?)\$\$/g, (m, body: string) => (looksLikeMath(body) ? latexToText(body) : m))
    .replace(/\$([^$\n]+?)\$/g, (m, body: string) => (looksLikeMath(body) ? latexToText(body) : m));
}

/** The whole answer with inline math turned into text, outside code fences and code spans. */
export function plainMath(text: string): string {
  if (!text.includes('$') && !text.includes('\\(')) return text;
  return text
    .split(/(^```[\s\S]*?(?:^```|$(?![\s\S])))/m)
    .map((part, i) =>
      i % 2 === 1
        ? part
        : part
            .split(/(`[^`\n]*`)/)
            .map((seg, j) => (j % 2 === 1 ? seg : convertProse(seg)))
            .join(''),
    )
    .join('');
}
