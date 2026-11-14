import { Check, Copy } from 'lucide-react';
import { Fragment, useMemo, useState, type ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';

export type CodeLanguage = 'yaml' | 'json' | 'text' | 'csv' | 'markdown' | 'python';

export interface CodeBlockProps {
  code: string;
  language?: CodeLanguage;
  /** Shown in the header bar (e.g. a file name). */
  title?: ReactNode;
  showLineNumbers?: boolean;
  maxHeight?: string;
  className?: string;
}

// Tiny, dependency-free highlighters for the two formats we show most (YAML, JSON).
const TOKEN = {
  key: 'text-primary',
  string: 'text-success',
  number: 'text-warning',
  bool: 'text-accent',
  comment: 'text-muted italic',
  punct: 'text-muted',
};

function highlightYamlLine(line: string): ReactNode {
  const commentIdx = line.search(/(^|\s)#/);
  const code = commentIdx >= 0 ? line.slice(0, commentIdx) : line;
  const comment = commentIdx >= 0 ? line.slice(commentIdx) : '';
  const m = /^(\s*-?\s*)([\w.\-"' ]+?)(:)(\s|$)(.*)$/.exec(code);
  const parts: ReactNode[] = [];
  if (m) {
    parts.push(m[1], <span className={TOKEN.key}>{m[2]}</span>, <span className={TOKEN.punct}>{m[3]}</span>, m[4]);
    parts.push(highlightScalar(m[5]));
  } else {
    parts.push(highlightScalar(code));
  }
  if (comment) parts.push(<span className={TOKEN.comment}>{comment}</span>);
  return parts.map((p, i) => <Fragment key={i}>{p}</Fragment>);
}

function highlightScalar(v: string): ReactNode {
  const t = v.trim();
  if (!t) return v;
  if (/^-?\d+(\.\d+)?$/.test(t)) return <span className={TOKEN.number}>{v}</span>;
  if (/^(true|false|null|~)$/i.test(t)) return <span className={TOKEN.bool}>{v}</span>;
  if (/^["'].*["']$/.test(t)) return <span className={TOKEN.string}>{v}</span>;
  if (/^[[{>|]/.test(t)) return <span className={TOKEN.punct}>{v}</span>;
  return <span className={TOKEN.string}>{v}</span>;
}

function highlightJsonLine(line: string): ReactNode {
  const re = /("(?:\\.|[^"\\])*")(\s*:)?|\b(-?\d+(?:\.\d+)?(?:e[+-]?\d+)?)\b|\b(true|false|null)\b/gi;
  const out: ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(line))) {
    if (m.index > last) out.push(line.slice(last, m.index));
    if (m[1]) {
      out.push(<span className={m[2] ? TOKEN.key : TOKEN.string}>{m[1]}</span>);
      if (m[2]) out.push(<span className={TOKEN.punct}>{m[2]}</span>);
    } else if (m[3]) out.push(<span className={TOKEN.number}>{m[3]}</span>);
    else if (m[4]) out.push(<span className={TOKEN.bool}>{m[4]}</span>);
    last = re.lastIndex;
  }
  if (last < line.length) out.push(line.slice(last));
  return out.map((p, i) => <Fragment key={i}>{p}</Fragment>);
}

export function CodeBlock({
  code,
  language = 'text',
  title,
  showLineNumbers = true,
  maxHeight = '32rem',
  className,
}: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const lines = useMemo(() => code.replace(/\n$/, '').split('\n'), [code]);
  const render = language === 'yaml' ? highlightYamlLine : language === 'json' ? highlightJsonLine : (l: string) => l;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard blocked */
    }
  };

  return (
    <div className={cn('overflow-hidden rounded-xl border border-border bg-surface-muted/50', className)}>
      <div className="flex items-center justify-between gap-2 border-b border-border bg-surface/60 px-3 py-1.5">
        <span className="truncate font-mono text-xs text-muted">{title ?? language}</span>
        <button
          type="button"
          onClick={copy}
          className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted transition-colors hover:bg-surface-muted hover:text-text"
          aria-label="Copy code"
        >
          {copied ? <Check className="size-3.5 text-success" /> : <Copy className="size-3.5" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="overflow-auto p-3 font-mono text-[12.5px] leading-relaxed" style={{ maxHeight }}>
        <code>
          {lines.map((line, i) => (
            <div key={i} className="flex">
              {showLineNumbers && (
                <span className="mr-4 inline-block w-8 shrink-0 select-none text-right text-muted/60">{i + 1}</span>
              )}
              <span className="whitespace-pre">{render(line)}</span>
            </div>
          ))}
        </code>
      </pre>
    </div>
  );
}
