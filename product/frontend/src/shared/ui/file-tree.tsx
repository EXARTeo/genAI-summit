import { AnimatePresence, motion } from 'framer-motion';
import { ChevronRight, File, FileCode2, FileSpreadsheet, FileText, Folder, FolderOpen } from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { collapse } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';

export interface FileTreeEntry {
  /** Slash-separated path, e.g. `plugins/cv-ranker/plugin.yaml`. */
  path: string;
  /** Right-aligned meta (version, size). */
  meta?: ReactNode;
}

interface Node {
  name: string;
  path: string;
  children: Map<string, Node>;
  entry?: FileTreeEntry;
}

export function buildTree(entries: FileTreeEntry[]): Node {
  const root: Node = { name: '', path: '', children: new Map() };
  for (const e of entries) {
    const parts = e.path.split('/').filter(Boolean);
    let cur = root;
    parts.forEach((part, i) => {
      const path = parts.slice(0, i + 1).join('/');
      if (!cur.children.has(part)) cur.children.set(part, { name: part, path, children: new Map() });
      cur = cur.children.get(part)!;
      if (i === parts.length - 1) cur.entry = e;
    });
  }
  return root;
}

export function fileIcon(name: string) {
  if (/\.(ya?ml|json|py|toml)$/i.test(name)) return <FileCode2 className="text-accent" />;
  if (/\.(csv|tsv|xlsx?)$/i.test(name)) return <FileSpreadsheet className="text-success" />;
  if (/\.(md|txt|pdf|docx?)$/i.test(name)) return <FileText className="text-info" />;
  return <File className="text-muted" />;
}

export interface FileTreeProps {
  entries: FileTreeEntry[];
  selected?: string | null;
  onSelect?: (path: string) => void;
  /** Folders open at first render; default: top level. */
  defaultExpanded?: string[];
  className?: string;
}

/** Folder tree built from flat paths. Folders first, then files, alphabetical. */
export function FileTree({ entries, selected, onSelect, defaultExpanded, className }: FileTreeProps) {
  const tree = useMemo(() => buildTree(entries), [entries]);
  const [open, setOpen] = useState<Set<string>>(
    () => new Set(defaultExpanded ?? [...tree.children.values()].filter((n) => n.children.size).map((n) => n.path)),
  );
  const toggle = (p: string) =>
    setOpen((s) => {
      const next = new Set(s);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });

  const render = (node: Node, depth: number): ReactNode => {
    const kids = [...node.children.values()].sort((a, b) => {
      const af = a.children.size > 0 && !a.entry;
      const bf = b.children.size > 0 && !b.entry;
      return af === bf ? a.name.localeCompare(b.name) : af ? -1 : 1;
    });
    return kids.map((n) => {
      const isFolder = n.children.size > 0 && !n.entry;
      const isOpen = open.has(n.path);
      const isSel = selected === n.path;
      return (
        <li key={n.path} role="treeitem" aria-expanded={isFolder ? isOpen : undefined} aria-selected={isSel}>
          <button
            type="button"
            onClick={() => (isFolder ? toggle(n.path) : onSelect?.(n.path))}
            style={{ paddingLeft: `${depth * 14 + 8}px` }}
            className={cn(
              'group flex w-full items-center gap-1.5 rounded-md py-1 pr-2 text-left text-sm transition-colors [&_svg]:size-4 [&_svg]:shrink-0',
              isSel ? 'bg-primary/10 text-primary' : 'hover:bg-surface-muted',
            )}
          >
            {isFolder ? (
              <>
                <ChevronRight className={cn('!size-3.5 text-muted transition-transform', isOpen && 'rotate-90')} />
                {isOpen ? <FolderOpen className="text-primary/80" /> : <Folder className="text-primary/80" />}
              </>
            ) : (
              <>
                <span className="w-3.5" />
                {fileIcon(n.name)}
              </>
            )}
            <span className="flex-1 truncate">{n.name}</span>
            {n.entry?.meta && <span className="shrink-0 text-[11px] text-muted">{n.entry.meta}</span>}
          </button>
          {isFolder && (
            <AnimatePresence initial={false}>
              {isOpen && (
                <motion.ul
                  role="group"
                  variants={collapse}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                  className="overflow-hidden"
                >
                  {render(n, depth + 1)}
                </motion.ul>
              )}
            </AnimatePresence>
          )}
        </li>
      );
    });
  };

  return (
    <ul role="tree" className={cn('space-y-0.5', className)}>
      {render(tree, 0)}
    </ul>
  );
}
