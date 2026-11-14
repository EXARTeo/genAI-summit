/**
 * File chips (port of magenticx's composer attachment chips in `ChatInputBar.tsx` and the file tiles
 * in `message_parts/MessageAttachments.tsx`), one component for chat, system folders and audits.
 *
 * - `composer`: a file waiting to be sent. An image is its 56 px thumbnail, any other file a small
 *   accent tile + name + type and size; a round remove button sits on the corner, the read/upload
 *   progress runs along the bottom, a failed file turns red with the reason.
 * - `message`: a sent or generated file, a 40 px accent tile + name + type · size. Clicking opens it;
 *   with a pointer, Preview / Download (and a ⋯ menu for extra actions such as "Save to <system>
 *   folder") float over it on hover like magenticx; on touch screens the ⋯ menu is always shown.
 * - `row`: a compact list row (an audit's files read, a folder listing).
 *
 * Data in, callbacks out: nothing here knows where the bytes come from.
 */
import {
  AlertCircle,
  Download,
  Eye,
  File as FileIcon,
  FileCode2,
  FileImage,
  FileJson,
  FileSpreadsheet,
  FileText,
  MoreHorizontal,
  X,
  type LucideIcon,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { classifyFile, fileSubtitle, type FileMeta } from '@/shared/lib/files';
import { cn } from '@/shared/lib/utils';
import { DropdownMenu, type DropdownItem } from './dropdown-menu';
import { Tooltip } from './tooltip';

/** An extra action on a file (menus, preview header). */
export interface FileAction {
  label: string;
  icon?: ReactNode;
  onSelect: () => void;
  disabled?: boolean;
}

/** The icon for a file's kind. */
export function fileKindIcon(meta: FileMeta): LucideIcon {
  switch (classifyFile(meta).kind) {
    case 'image':
      return FileImage;
    case 'csv':
      return FileSpreadsheet;
    case 'json':
      return FileJson;
    case 'code':
      return FileCode2;
    case 'unsupported':
      return FileIcon;
    default:
      return FileText;
  }
}

export interface FileChipProps extends FileMeta {
  variant?: 'composer' | 'message' | 'row';
  /** Shown instead of the name (an artifact's title). */
  title?: string | null;
  /** Replaces the "PDF · 12 KB" line. */
  subtitle?: ReactNode;
  /** Image thumbnail (composer image chips). */
  thumbnail?: string | null;
  icon?: LucideIcon;
  /** Read / upload progress 0..1; below 1 shows a bar and a busy state. */
  progress?: number;
  error?: string | null;
  /** Click / Enter: open the preview or the lightbox. */
  onOpen?: () => void;
  onDownload?: () => void;
  onRemove?: () => void;
  /** Extra menu actions (message and row variants). */
  actions?: FileAction[];
  /** Mono name (paths). */
  mono?: boolean;
  /** Trailing content of a row (a version). */
  trailing?: ReactNode;
  className?: string;
}

const ROUND =
  'grid size-8 place-items-center rounded-full border border-border/50 bg-background/95 text-text shadow-pop transition-transform hover:scale-105 hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 [&_svg]:size-4';

function menuItems(onOpen?: () => void, onDownload?: () => void, actions: FileAction[] = []): DropdownItem[] {
  const base: DropdownItem[] = [
    ...(onOpen ? [{ label: 'Preview', icon: <Eye />, onSelect: onOpen }] : []),
    ...(onDownload ? [{ label: 'Download', icon: <Download />, onSelect: onDownload }] : []),
  ];
  const extra: DropdownItem[] = actions.map((a) => ({
    label: a.label,
    icon: a.icon,
    onSelect: a.onSelect,
    disabled: a.disabled,
  }));
  return base.length && extra.length ? [...base, { type: 'separator' }, ...extra] : [...base, ...extra];
}

function ProgressBar({ progress }: { progress: number }) {
  return (
    <span
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(progress * 100)}
      aria-label="Reading the file"
      className="absolute inset-x-0 bottom-0 h-0.5 bg-primary/15"
    >
      <span
        className="block h-full bg-primary transition-[width] duration-150 motion-reduce:transition-none"
        style={{ width: `${Math.max(4, Math.round(progress * 100))}%` }}
      />
    </span>
  );
}

function RemoveButton({ name, onRemove }: { name: string; onRemove: () => void }) {
  return (
    <button
      type="button"
      onClick={onRemove}
      aria-label={`Remove ${name}`}
      className="absolute right-1.5 top-1.5 z-10 grid size-5 place-items-center rounded-full bg-background/90 text-danger shadow-sm ring-1 ring-border/70 transition-colors hover:text-danger/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
    >
      <X className="pointer-events-none size-3" strokeWidth={2.5} />
    </button>
  );
}

export function FileChip({
  variant = 'message',
  name,
  mime,
  size,
  title,
  subtitle,
  thumbnail,
  icon,
  progress,
  error,
  onOpen,
  onDownload,
  onRemove,
  actions,
  mono,
  trailing,
  className,
}: FileChipProps) {
  const Icon = icon ?? fileKindIcon({ name, mime });
  const label = title || name;
  const busy = typeof progress === 'number' && progress < 1 && !error;
  const sub = error ? error : (subtitle ?? fileSubtitle({ name, mime, size }));
  const openable = Boolean(onOpen) && !busy && !error;

  if (variant === 'composer') {
    const isThumb = Boolean(thumbnail) && !error;
    const chip = (
      <div
        data-file-chip
        aria-busy={busy || undefined}
        className={cn(
          'relative shrink-0 overflow-hidden rounded-2xl border bg-surface-sunken/70 text-text shadow-card',
          error ? 'border-danger/50' : 'border-border',
          isThumb
            ? 'flex items-center p-1.5'
            : 'flex max-w-[14rem] items-center gap-2.5 py-2 pl-2.5 pr-7 md:max-w-[16rem]',
          className,
        )}
      >
        {isThumb ? (
          <button
            type="button"
            onClick={onOpen}
            disabled={!openable}
            aria-label={`View ${name}`}
            className="block cursor-zoom-in rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-default"
          >
            <img
              src={thumbnail ?? ''}
              alt={name}
              className={cn('size-14 rounded-xl object-cover', busy && 'opacity-60')}
            />
          </button>
        ) : (
          <button
            type="button"
            onClick={onOpen}
            disabled={!openable}
            aria-label={`Preview ${name}`}
            className="flex min-w-0 items-center gap-2.5 rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-default"
          >
            <span
              className={cn(
                'grid size-8 shrink-0 place-items-center rounded-lg',
                error ? 'bg-danger/10 text-danger' : 'bg-primary/10 text-primary',
              )}
            >
              {error ? <AlertCircle className="size-4" /> : <Icon className="size-4" />}
            </span>
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium">{label}</span>
              <span className={cn('block truncate text-2xs', error ? 'text-danger' : 'text-muted')}>
                {busy ? `Reading… ${Math.round((progress ?? 0) * 100)}%` : sub}
              </span>
            </span>
          </button>
        )}
        {onRemove && <RemoveButton name={name} onRemove={onRemove} />}
        {busy && <ProgressBar progress={progress ?? 0} />}
      </div>
    );
    return error ? <Tooltip content={error}>{chip}</Tooltip> : chip;
  }

  const items = menuItems(onOpen, onDownload, actions);
  const activate = () => (onOpen ? onOpen() : onDownload?.());

  if (variant === 'row') {
    const clickable = Boolean(onOpen || onDownload);
    const body = (
      <>
        <span className="grid size-6 shrink-0 place-items-center rounded-md bg-primary/10 text-primary">
          <Icon className="size-3.5" aria-hidden />
        </span>
        <span className={cn('min-w-0 flex-1 truncate', mono && 'font-mono')}>{label}</span>
        {trailing != null && <span className="shrink-0 text-muted">{trailing}</span>}
      </>
    );
    return (
      <div
        data-file-chip
        className={cn(
          'group/file flex min-w-0 items-center gap-1 rounded-lg text-xs',
          clickable && 'transition-colors hover:bg-hover',
          className,
        )}
      >
        {clickable ? (
          <button
            type="button"
            onClick={activate}
            aria-label={`${onOpen ? 'Preview' : 'Download'} ${name}`}
            className="flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1.5 py-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60"
          >
            {body}
          </button>
        ) : (
          <span className="flex min-w-0 flex-1 items-center gap-2 px-1.5 py-1">{body}</span>
        )}
        {(actions?.length ?? 0) > 0 && (
          <DropdownMenu
            items={items}
            trigger={
              <button
                type="button"
                aria-label={`Actions for ${name}`}
                className="mr-1 grid size-6 place-items-center rounded-md text-muted opacity-0 transition-opacity hover:bg-hover hover:text-text focus-visible:opacity-100 group-hover/file:opacity-100 data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100"
              >
                <MoreHorizontal className="size-3.5" />
              </button>
            }
          />
        )}
      </div>
    );
  }

  // message
  return (
    <div
      data-file-chip
      className={cn(
        'group/file relative w-64 rounded-2xl border border-border/50 bg-surface-sunken/30 text-xs transition-[background-color,box-shadow] duration-200 hover:bg-surface-sunken/60 hover:shadow-card md:w-80',
        className,
      )}
    >
      <button
        type="button"
        onClick={activate}
        disabled={!onOpen && !onDownload}
        aria-label={`${onOpen ? 'Preview' : 'Download'} ${label}`}
        className="flex w-full min-w-0 items-center gap-3 rounded-2xl px-3 py-3 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/60 disabled:cursor-default [@media(hover:none)]:pr-11"
      >
        <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-primary/90 text-primary-foreground">
          <Icon className="size-4" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-text/90">{label}</span>
          <span className="block truncate text-muted/80">{sub}</span>
        </span>
      </button>

      {/* Pointer: magenticx's hover actions over the tile. */}
      {items.length > 0 && (
        <div
          onClick={(e) => e.target === e.currentTarget && activate()}
          className="pointer-events-none absolute inset-0 hidden cursor-pointer items-center justify-center gap-2 opacity-0 transition-opacity duration-200 group-focus-within/file:pointer-events-auto group-focus-within/file:opacity-100 group-hover/file:pointer-events-auto group-hover/file:opacity-100 has-[[data-state=open]]:pointer-events-auto has-[[data-state=open]]:opacity-100 [@media(hover:hover)]:flex"
        >
          {onOpen && (
            <Tooltip content="Preview">
              <button
                type="button"
                aria-label={`Preview ${label}`}
                className={cn(ROUND, 'text-primary')}
                onClick={onOpen}
              >
                <Eye />
              </button>
            </Tooltip>
          )}
          {onDownload && (
            <Tooltip content="Download">
              <button type="button" aria-label={`Download ${label}`} className={ROUND} onClick={onDownload}>
                <Download />
              </button>
            </Tooltip>
          )}
          {(actions?.length ?? 0) > 0 && (
            <DropdownMenu
              items={actions!.map((a) => ({
                label: a.label,
                icon: a.icon,
                onSelect: a.onSelect,
                disabled: a.disabled,
              }))}
              trigger={
                <button type="button" aria-label={`More actions for ${label}`} className={ROUND}>
                  <MoreHorizontal />
                </button>
              }
            />
          )}
        </div>
      )}

      {/* Touch: no hover, so every action sits in an always-visible ⋯ menu. */}
      {items.length > 0 && (
        <div className="absolute right-2 top-1/2 -translate-y-1/2 [@media(hover:hover)]:hidden">
          <DropdownMenu
            items={items}
            trigger={
              <button
                type="button"
                aria-label={`Actions for ${label}`}
                className="grid size-8 place-items-center rounded-full text-muted hover:bg-hover hover:text-text"
              >
                <MoreHorizontal className="size-4" />
              </button>
            }
          />
        </div>
      )}
    </div>
  );
}
