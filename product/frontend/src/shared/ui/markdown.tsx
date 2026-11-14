import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { cn } from '@/shared/lib/utils';

export interface MarkdownProps {
  children: string;
  className?: string;
  /** Show a blinking caret at the end (streaming text). */
  streaming?: boolean;
}

/** GitHub-flavoured markdown, styled by src/styles/markdown.css. Raw HTML is not rendered. */
export function Markdown({ children, className, streaming }: MarkdownProps) {
  return (
    <div className={cn('markdown', className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noreferrer noopener" />,
        }}
      >
        {children}
      </ReactMarkdown>
      {streaming && <span className="stream-caret" aria-hidden />}
    </div>
  );
}
