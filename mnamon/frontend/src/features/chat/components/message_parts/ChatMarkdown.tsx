/**
 * The answer renderer (magenticx `shared/ui/ai-elements/response.tsx` + `code-block.tsx`): GFM,
 * no raw HTML, highlighted code blocks with a language label and copy, links in a new tab, and a
 * caret while streaming. An unclosed code fence mid-stream is closed so it never flashes as text.
 */
import '@/styles/chat.css';
import { Check, Copy } from 'lucide-react';
import { memo, useState, type ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import remarkGfm from 'remark-gfm';
import { cn } from '@/shared/lib/utils';

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
  const child = Array.isArray(children) ? children[0] : children;
  const className = (child as { props?: { className?: string } })?.props?.className ?? '';
  const language = /language-([\w+-]+)/.exec(className)?.[1] ?? 'text';
  const copy = () => {
    void navigator.clipboard?.writeText(textOf(children).replace(/\n$/, ''));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="chat-code">
      <div className="flex h-8 items-center justify-between border-b border-border px-3 text-2xs text-muted">
        <span className="font-mono">{language}</span>
        <button
          type="button"
          onClick={copy}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 hover:bg-surface hover:text-text"
          aria-label="Copy code"
        >
          {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre>{children}</pre>
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
          table: ({ node: _node, ...props }) => (
            <div className="overflow-x-auto">
              <table {...props} />
            </div>
          ),
        }}
      >
        {streaming ? closeOpenFence(text) : text}
      </ReactMarkdown>
      {streaming && <span className="stream-caret" aria-hidden />}
    </div>
  );
});
