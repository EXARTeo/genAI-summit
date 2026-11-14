/**
 * A Markdown table in an answer (magenticx `shared/ui/ai-elements/markdown-table.tsx`): a
 * bordered card with copy and download buttons above it. Copy puts HTML + TSV on the clipboard
 * (a grid in Word, Outlook and Excel); download offers CSV (with a BOM, so Excel opens Greek
 * correctly) or Markdown. Rows are read from the rendered table at click time, so a table still
 * streaming in is taken as far as it has arrived.
 */
import { Check, Copy, Download, FileSpreadsheet, FileText } from 'lucide-react';
import { useEffect, useRef, useState, type ComponentProps } from 'react';
import { cn } from '@/shared/lib/utils';
import { DropdownMenu, IconButton } from '@/shared/ui';
import { copyTableRows, downloadTableCsv, downloadTableMarkdown, tableRows } from '../../lib/tableExport';

const COPIED_RESET_MS = 2000;
const ACTION = 'size-6 text-muted hover:bg-hover hover:text-text [&_svg]:size-3.5';

type TableProps = ComponentProps<'table'> & { node?: unknown };

export function MarkdownTable({ children, className, node: _node, ...props }: TableProps) {
  const tableRef = useRef<HTMLTableElement>(null);
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const rows = () => (tableRef.current ? tableRows(tableRef.current) : []);

  const copy = () => {
    void copyTableRows(rows()).then((ok) => {
      if (!ok) return;
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), COPIED_RESET_MS);
    });
  };
  const download = (format: 'csv' | 'md') => {
    const current = rows();
    if (!current.length) return;
    if (format === 'csv') downloadTableCsv(current);
    else downloadTableMarkdown(current);
  };

  return (
    <div className="chat-table flex flex-col gap-1" data-chat-table>
      <div className="flex items-center justify-end gap-0.5">
        <IconButton
          label={copied ? 'Table copied' : 'Copy table'}
          icon={copied ? <Check /> : <Copy />}
          className={ACTION}
          onClick={copy}
        />
        <DropdownMenu
          trigger={<IconButton label="Download table" icon={<Download />} className={ACTION} />}
          items={[
            { label: 'Download as CSV', icon: <FileSpreadsheet />, onSelect: () => download('csv') },
            { label: 'Download as Markdown', icon: <FileText />, onSelect: () => download('md') },
          ]}
        />
      </div>
      <div className="overflow-x-auto rounded-xl border border-border/70 bg-surface/40 shadow-sm">
        <table
          ref={tableRef}
          className={cn(
            'w-full border-collapse',
            '[&_td]:!px-4 [&_td]:!py-2.5 [&_th]:!px-4 [&_th]:!py-2.5',
            '[&_tbody_tr:last-child>td]:!border-b-0 [&_thead_th]:bg-surface-sunken/50',
            className,
          )}
          {...props}
        >
          {children}
        </table>
      </div>
    </div>
  );
}
