import { AnimatePresence, motion } from 'framer-motion';
import {
  ChevronRight,
  File,
  FileCode2,
  FileSpreadsheet,
  FileText,
  Folder,
  FolderOpen,
  Loader2,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type DragEvent, type ReactNode } from 'react';
import { collapse } from '@/shared/lib/motion';
import { cn } from '@/shared/lib/utils';

export interface FileTreeEntry {
  /** Slash-separated path, e.g. `plugins/cv-ranker/plugin.yaml`. */
  path: string;
  /** Right-aligned meta (version, size). The row is a Tailwind `group`, so `group-hover:` works here. */
  meta?: ReactNode;
  /** Native tooltip for the row (e.g. "v3 · 1.2 KB · by agent"). */
  title?: string;
}

interface Node {
  name: string;
  path: string;
  children: Map<string, Node>;
  entry?: FileTreeEntry;
  /** Number of files at or below this node. */
  count: number;
}

export function buildTree(entries: FileTreeEntry[]): Node {
  const root: Node = { name: '', path: '', children: new Map(), count: 0 };
  for (const e of entries) {
    const parts = e.path.split('/').filter(Boolean);
    let cur = root;
    root.count++;
    parts.forEach((part, i) => {
      const path = parts.slice(0, i + 1).join('/');
      if (!cur.children.has(part))
        cur.children.set(part, { name: part, path, children: new Map(), count: 0 });
      cur = cur.children.get(part)!;
      cur.count++;
      if (i === parts.length - 1) cur.entry = e;
    });
  }
  return root;
}

export function fileIcon(name: string) {
  if (/\.(ya?ml|json|py|toml)$/i.test(name)) return <FileCode2 className="text-muted" />;
  if (/\.(csv|tsv|xlsx?)$/i.test(name)) return <FileSpreadsheet className="text-success" />;
  if (/\.(md|txt|pdf|docx?)$/i.test(name)) return <FileText className="text-info" />;
  return <File className="text-muted" />;
}

const parentOf = (p: string) => p.split('/').slice(0, -1).join('/');
const hasFiles = (e: DragEvent) => Array.from(e.dataTransfer.types).includes('Files');

export interface FileTreeProps {
  entries: FileTreeEntry[];
  selected?: string | null;
  onSelect?: (path: string) => void;
  /** Folders open at first render; default: top level. Ancestors of `selected` always open. */
  defaultExpanded?: string[];
  /** Show a root row (folder path `''`) with this label above the tree. */
  rootLabel?: ReactNode;
  /** Show the number of files under each folder. */
  showCounts?: boolean;
  /** Per-folder action (path `''` = root), revealed on row hover / keyboard focus. */
  folderAction?: (folder: string) => ReactNode;
  /** Enables dropping files on a folder row (a file row targets its folder, empty space the root). */
  onDropFiles?: (folder: string, files: File[]) => void;
  /** Folder showing a busy spinner (e.g. an upload in flight). */
  busyFolder?: string | null;
  className?: string;
}

/** Folder tree built from flat paths. Folders first, then files, alphabetical. */
export function FileTree({
  entries,
  selected,
  onSelect,
  defaultExpanded,
  rootLabel,
  showCounts,
  folderAction,
  onDropFiles,
  busyFolder,
  className,
}: FileTreeProps) {
  const tree = useMemo(() => buildTree(entries), [entries]);
  const [open, setOpen] = useState<Set<string>>(
    () =>
      new Set(
        defaultExpanded ?? [...tree.children.values()].filter((n) => n.children.size).map((n) => n.path),
      ),
  );
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const hoverTimer = useRef<ReturnType<typeof setTimeout>>();

  // Reveal the selected file: open every folder above it.
  useEffect(() => {
    if (!selected) return;
    const parts = selected.split('/').slice(0, -1);
    if (!parts.length) return;
    setOpen((s) => {
      const ancestors = parts.map((_, i) => parts.slice(0, i + 1).join('/'));
      if (ancestors.every((a) => s.has(a))) return s;
      return new Set([...s, ...ancestors]);
    });
  }, [selected]);

  useEffect(() => () => clearTimeout(hoverTimer.current), []);

  const toggle = (p: string) =>
    setOpen((s) => {
      const next = new Set(s);
      if (next.has(p)) next.delete(p);
      else next.add(p);
      return next;
    });

  const dragTo = (folder: string) => {
    if (dropTarget === folder) return;
    setDropTarget(folder);
    clearTimeout(hoverTimer.current);
    // Hovering a closed folder while dragging opens it, so deeper folders are reachable.
    if (folder && !open.has(folder)) {
      hoverTimer.current = setTimeout(() => setOpen((s) => new Set([...s, folder])), 700);
    }
  };
  const endDrag = () => {
    clearTimeout(hoverTimer.current);
    setDropTarget(null);
  };

  const dnd = (folder: string) =>
    onDropFiles
      ? {
          onDragOver: (e: DragEvent) => {
            if (!hasFiles(e)) return;
            e.preventDefault();
            e.stopPropagation();
            e.dataTransfer.dropEffect = 'copy';
            dragTo(folder);
          },
          onDrop: (e: DragEvent) => {
            if (!hasFiles(e)) return;
            e.preventDefault();
            e.stopPropagation();
            endDrag();
            const files = Array.from(e.dataTransfer.files);
            if (files.length) onDropFiles(folder, files);
          },
        }
      : {};

  const row = (n: Node, depth: number, isRoot = false): ReactNode => {
    const isFolder = isRoot || (n.children.size > 0 && !n.entry);
    const isOpen = isRoot || open.has(n.path);
    const isSel = !isFolder && selected === n.path;
    const target = isFolder ? n.path : parentOf(n.path);
    const isDrop = isFolder && dropTarget === n.path;
    const busy = isFolder && busyFolder === n.path;
    const action = isFolder && !busy ? folderAction?.(n.path) : null;
    const trailing = isFolder ? (showCounts ? n.count : null) : n.entry?.meta;

    return (
      <div
        className={cn(
          'group relative flex items-center rounded-md transition-colors',
          isSel ? 'bg-primary/10 text-primary' : 'hover:bg-surface-muted',
          isDrop && 'bg-primary/10 ring-1 ring-inset ring-primary/50',
        )}
        title={n.entry?.title}
        {...dnd(target)}
      >
        <button
          type="button"
          onClick={() => (isRoot ? undefined : isFolder ? toggle(n.path) : onSelect?.(n.path))}
          style={{ paddingLeft: `${depth * 14 + 8}px` }}
          className={cn(
            'flex min-w-0 flex-1 items-center gap-1.5 rounded-md py-1 pr-2 text-left text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-4 [&_svg]:shrink-0',
            isRoot && 'cursor-default font-medium',
          )}
        >
          {isFolder ? (
            <>
              {isRoot ? (
                <span className="w-3.5" />
              ) : (
                <ChevronRight
                  className={cn('!size-3.5 text-muted transition-transform', isOpen && 'rotate-90')}
                />
              )}
              {isOpen || isDrop ? (
                <FolderOpen className="text-primary/80" />
              ) : (
                <Folder className="text-primary/80" />
              )}
            </>
          ) : (
            <>
              <span className="w-3.5" />
              {fileIcon(n.name)}
            </>
          )}
          <span className="flex-1 truncate">{isRoot ? rootLabel : n.name}</span>
          {trailing != null && (
            <span
              className={cn(
                'shrink-0 text-[11px] tabular-nums text-muted transition-opacity',
                action && 'group-focus-within:opacity-0 group-hover:opacity-0 [@media(hover:none)]:opacity-0',
              )}
            >
              {trailing}
            </span>
          )}
          {busy && <Loader2 className="!size-3.5 animate-spin text-primary" aria-label="Uploading" />}
        </button>
        {action && (
          <span className="absolute inset-y-0 right-1 flex items-center opacity-0 transition-opacity focus-within:opacity-100 group-focus-within:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100">
            {action}
          </span>
        )}
      </div>
    );
  };

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
          {row(n, depth)}
          {isFolder && (
            <AnimatePresence initial={false}>
              {isOpen && (
                <motion.ul
                  role="group"
                  variants={collapse}
                  initial="initial"
                  animate="animate"
                  exit="exit"
                  className="space-y-0.5 overflow-hidden"
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

  const rootDrop = dropTarget === '' && rootLabel == null;

  return (
    <ul
      role="tree"
      className={cn('space-y-0.5 rounded-md', rootDrop && 'ring-1 ring-inset ring-primary/50', className)}
      {...dnd('')}
      onDragLeave={
        onDropFiles
          ? (e) => {
              if (!e.currentTarget.contains(e.relatedTarget as globalThis.Node | null)) endDrag();
            }
          : undefined
      }
    >
      {rootLabel != null ? (
        <li role="treeitem" aria-expanded aria-selected={false}>
          {row(tree, 0, true)}
          <ul role="group" className="space-y-0.5">
            {render(tree, 1)}
          </ul>
        </li>
      ) : (
        render(tree, 0)
      )}
    </ul>
  );
}
