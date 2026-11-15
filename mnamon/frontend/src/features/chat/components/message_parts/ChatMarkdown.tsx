/**
 * The answer renderer (magenticx `shared/ui/ai-elements/response.tsx` + `code-block.tsx` +
 * `markdown-table.tsx`): GFM, no raw HTML, highlighted code blocks with a header (language,
 * download, copy), tables in a card with copy and download (CSV / Markdown), links in a new tab,
 * and a caret while streaming. An unclosed code fence mid-stream is closed so it never flashes as text.
 */
import '@/styles/chat.css';
import { Check, Copy, Download } from 'lucide-react';
import { memo, useEffect, useRef, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import remarkGfm from 'remark-gfm';
import { cn } from '@/shared/lib/utils';
import { IconButton } from '@/shared/ui';
import { codeFileName } from '../../lib/codeExport';
import { triggerBrowserDownload } from '../../lib/download';
import { plainMath } from '../../lib/mathText';
import { MarkdownTable } from './MarkdownTable';

const CODE_ACTION = 'size-6 text-muted hover:bg-hover hover:text-text [&_svg]:size-3.5';

function closeOpenFence(text: string): string {
  const fences = text.match(/^```/gm)?.length ?? 0;
  return fences % 2 === 1 ? `${text}\n\`\`\`` : text;
}

function textOf(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(textOf).join('');
  if (node && typeof node === 'object' && 'props' in node) {
    return textOf((node as { props: { children?: ReactNode } }).props.children);
  }
  return '';
}

function CodeFrame({ children }: { children: ReactNode }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );
  const child = Array.isArray(children) ? children[0] : children;
  const className = (child as { props?: { className?: string } })?.props?.className ?? '';
  const language = /language-([\w+-]+)/.exec(className)?.[1] ?? 'text';
  const code = () => textOf(children).replace(/\n$/, '');
  const copy = () => {
    void navigator.clipboard?.writeText(code());
    setCopied(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setCopied(false), 2000);
  };
  const download = () =>
    triggerBrowserDownload(
      new Blob([`${code()}\n`], { type: 'text/plain;charset=utf-8' }),
      codeFileName(language),
    );
  return (
    <div className="chat-code" data-language={language}>
      <div className="flex items-center justify-between bg-surface-sunken px-3 py-2 text-xs text-muted">
        <span className="ml-1 font-mono lowercase">{language}</span>
        <div className="flex items-center gap-0.5">
          <IconButton label="Download code" icon={<Download />} className={CODE_ACTION} onClick={download} />
          <IconButton
            label={copied ? 'Copied' : 'Copy code'}
            icon={copied ? <Check /> : <Copy />}
            className={CODE_ACTION}
            onClick={copy}
          />
        </div>
      </div>
      <div className="border-t border-border bg-surface">
        <pre>{children}</pre>
      </div>
    </div>
  );
}

export const ChatMarkdown = memo(function ChatMarkdown({
  text,
  streaming,
  className,
}: {
  text: string;
  streaming?: boolean;
  className?: string;
}) {
  return (
    <div className={cn('markdown', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[[rehypeHighlight, { detect: false }]]}
        components={{
          a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer noopener" />,
          pre: ({ children }) => <CodeFrame>{children}</CodeFrame>,
          table: MarkdownTable,
        }}
      >
        {plainMath(streaming ? closeOpenFence(text) : text)}
      </ReactMarkdown>
      {streaming && <span className="stream-caret" aria-hidden />}
    </div>
  );
});
