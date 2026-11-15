/**
 * One tool step in the chain of thought (magenticx `CoTBlock` `TimelineToolItem` +
 * `ToolCallViews.tsx` + `SourceCards.tsx`): an icon on the guide line, the step's title built
 * from its arguments ("Read selection_rates.csv"), a short meta note, its duration and its
 * approval state; it opens onto PARAMETERS and RESULT panes. A shell call reads as a terminal,
 * a search step that returned sources shows them as link chips. The approval lifecycle lives on
 * the step: amber while it needs a human, green once approved, red if rejected.
 */
import {
  BookOpen,
  Bot,
  Check,
  Clock,
  FolderOpen,
  Pencil,
  Scale,
  Search,
  ShieldQuestion,
  ShieldX,
  SquareTerminal,
  Wrench,
  XCircle,
  Boxes,
  ClipboardList,
  FilePlus,
  FileText,
  Image as ImageIcon,
  Play,
  type LucideIcon,
} from 'lucide-react';
import { useMemo, useState, type ReactNode } from 'react';
import { cn } from '@/shared/lib/utils';
import type { Source, ToolStep } from '../../lib/timeline';
import {
  asToolArgs,
  isQuietTool,
  isShellTool,
  parseCommandOutput,
  parseToolArgs,
  toolDurationLabel,
  toolImages,
  toolMeta,
  toolSummary,
  toolTitle,
  toolTitleHint,
} from '../../lib/toolPresentation';
import { CoTStep, Collapse } from './CoTStep';

/** What a settled call did, where we have a glyph for it (a column of wrenches is unscannable). */
const TOOL_ICONS: Record<string, LucideIcon> = {
  read_file: BookOpen,
  read_system_file: BookOpen,
  ls: FolderOpen,
  glob: Search,
  grep: Search,
  write_file: Pencil,
  edit_file: Pencil,
  write_finding_note: Pencil,
  execute: SquareTerminal,
  shell: SquareTerminal,
  search_regulation: Scale,
  lookup_provision: Scale,
  list_systems: Boxes,
  list_audits: ClipboardList,
  list_system_files: FolderOpen,
  read_audit: ClipboardList,
  read_audit_artifact: FileText,
  propose_system_note: FilePlus,
  start_audit: Play,
  view_image: ImageIcon,
  task: Bot,
};

const PulsingClock = ({ className }: { className?: string }) => (
  <Clock className={cn('animate-pulse', className)} />
);
const PulsingShield = ({ className }: { className?: string }) => (
  <ShieldQuestion className={cn('animate-pulse', className)} />
);

/** The uppercase label over a pane (PARAMETERS, RESULT, ARGS, RESPONSE). */
export function PaneLabel({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <h4 className={cn('text-2xs font-medium uppercase tracking-wide text-muted', className)}>{children}</h4>
  );
}

/** A bordered monospace pane; `text-text` resets an amber/red step row's tint. */
export function MonoPane({ text, className }: { text: string; className?: string }) {
  return (
    <pre
      className={cn(
        'max-h-72 min-w-0 overflow-auto overscroll-contain whitespace-pre-wrap break-words rounded-md border border-border bg-surface-sunken/60 px-3 py-2.5 font-mono text-xs leading-relaxed text-text [overflow-wrap:anywhere]',
        className,
      )}
    >
      {text}
    </pre>
  );
}

/** JSON args / results pretty-printed; anything else as it came. */
export function prettyPayload(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') {
    try {
      return JSON.stringify(JSON.parse(value), null, 2);
    } catch {
      return value;
    }
  }
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

/** A shell call as a terminal: the command behind a `$`, the output, the exit code. */
function Terminal({ command, output, exitCode }: { command?: string; output?: string; exitCode?: number }) {
  return (
    <div className="min-w-0 overflow-hidden rounded-md border border-border bg-surface-sunken font-mono text-xs leading-5 text-text">
      {command !== undefined && (
        <pre className="m-0 flex gap-2 whitespace-pre-wrap break-words px-3 py-2.5">
          <span aria-hidden className="shrink-0 select-none text-success">
            $
          </span>
          <code className="min-w-0 flex-1">{command}</code>
        </pre>
      )}
      {output !== undefined && (
        <pre className="m-0 max-h-72 overflow-auto whitespace-pre-wrap break-words px-3 py-2.5">
          {output.trim() || <span className="italic text-muted">(no output)</span>}
        </pre>
      )}
      {exitCode !== undefined && (
        <div className="flex items-center justify-end gap-1.5 border-t border-border px-3 py-1 text-2xs text-muted">
          <span
            aria-hidden
            className={cn('size-1.5 rounded-full', exitCode === 0 ? 'bg-success' : 'bg-danger')}
          />
          exit {exitCode}
        </div>
      )}
    </div>
  );
}

export function SourceChips({ sources }: { sources: Source[] }) {
  const pages = sources.filter((s) => /^https?:\/\//i.test(s.url));
  if (!pages.length) return null;
  return (
    <ul aria-label="Sources" className="flex flex-wrap gap-1.5">
      {pages.map((s) => {
        let host = s.url;
        try {
          host = new URL(s.url).hostname.replace(/^www\./, '');
        } catch {
          /* keep the url */
        }
        const label = s.title || host;
        return (
          <li key={s.id} className="min-w-0 max-w-full">
            <a
              href={s.url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              title={s.title ? `${s.title} — ${host}` : host}
              className="inline-flex h-7 max-w-full items-center gap-1.5 rounded-full border border-border/60 bg-surface-sunken/40 px-2.5 text-xs text-text transition-colors hover:bg-surface-sunken focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <span
                aria-hidden
                className="grid size-3.5 shrink-0 place-items-center rounded-full bg-primary/10 text-[9px] font-semibold uppercase text-primary"
              >
                {host.charAt(0)}
              </span>
              <span className="min-w-0 max-w-[14rem] truncate">{label}</span>
            </a>
          </li>
        );
      })}
    </ul>
  );
}

function ArgsView({ tool, args }: { tool: ToolStep; args: unknown }) {
  const a = asToolArgs(args);
  if (args === null || args === undefined) return null;
  if (a && isShellTool(tool.name) && typeof a.command === 'string') return <Terminal command={a.command} />;
  if (a && tool.name === 'task' && typeof a.description === 'string')
    return <MonoPane text={a.description} className="font-sans" />;
  const text = prettyPayload(args);
  if (!text || text === '{}') return null;
  return (
    <div className="space-y-2">
      <PaneLabel>Parameters</PaneLabel>
      <MonoPane text={text} />
    </div>
  );
}

function ResultView({ tool }: { tool: ToolStep }) {
  const failed = tool.state === 'output-error';
  if (tool.result === undefined) return null;
  if (isShellTool(tool.name) && !failed) {
    const out = parseCommandOutput(tool.result);
    if (out) return <Terminal output={out.output} exitCode={out.exitCode} />;
  }
  return (
    <div className="space-y-2">
      <PaneLabel className={failed ? 'text-danger' : undefined}>{failed ? 'Error' : 'Result'}</PaneLabel>
      <MonoPane
        text={prettyPayload(tool.result) || '(empty)'}
        className={failed ? 'border-danger/30 bg-danger/5 text-danger' : undefined}
      />
      {tool.resultTruncated && (
        <p className="text-2xs italic text-muted">
          Result truncated for display — the agent saw the full output.
        </p>
      )}
    </div>
  );
}

export function ToolCallView({ tool, isLast = false }: { tool: ToolStep; isLast?: boolean }) {
  const [open, setOpen] = useState(false);
  const args = useMemo(() => parseToolArgs(tool.argsText), [tool.argsText]);
  const title = toolTitle(tool.name, args);
  const hint = toolTitleHint(tool.name, args);
  const failed = tool.state === 'output-error';
  const meta = failed ? undefined : toolMeta(tool.name, tool.result, tool.sources?.length);
  const duration = toolDurationLabel(tool.startedAt, tool.endedAt);
  const face = tool.approval?.status ?? null;
  const icon =
    face === 'pending'
      ? PulsingShield
      : face === 'rejected'
        ? ShieldX
        : failed
          ? XCircle
          : tool.state === 'output-available'
            ? (TOOL_ICONS[tool.name] ?? Wrench)
            : PulsingClock;

  // Read / list / search tools: a one-line summary, no Parameters / Result panes.
  if (isQuietTool(tool.name) && !failed && !face) {
    const summary = toolSummary(tool.name, tool.result);
    const images = toolImages(tool.result);
    return (
      <CoTStep
        icon={icon}
        hideConnector={isLast}
        label={
          <span className="flex max-w-full items-center gap-2">
            <span className="truncate font-medium" title={hint}>
              {title}
            </span>
            {duration && <span className="num shrink-0 text-xs text-muted">{duration}</span>}
          </span>
        }
      >
        {summary && <p className="text-xs text-muted">{summary}</p>}
        {images.length > 0 && (
          <div className="flex flex-wrap gap-2 pt-1">
            {images.map((img, i) => (
              <img
                key={i}
                src={img.src}
                alt={img.alt}
                className="max-h-56 max-w-full rounded-lg border border-border/60 object-contain"
              />
            ))}
          </div>
        )}
      </CoTStep>
    );
  }

  return (
    <CoTStep
      icon={icon}
      hideConnector={isLast}
      className={cn(
        failed && 'text-danger',
        face === 'pending' && 'text-warning',
        face === 'rejected' && 'text-danger',
      )}
      label={
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          aria-label={`Toggle ${title} details`}
          className="flex max-w-full items-center gap-2 rounded-sm text-left transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <span className="truncate font-medium" title={hint}>
            {title}
          </span>
          {meta && <span className="shrink-0 text-xs text-muted">{meta}</span>}
          {duration && <span className="num shrink-0 text-xs text-muted">{duration}</span>}
          {face === 'pending' ? (
            <span className="shrink-0 text-xs font-medium text-warning">Needs approval</span>
          ) : face === 'approved' ? (
            <span className="flex shrink-0 items-center gap-1 text-xs font-medium text-success">
              <Check className="size-3" /> Approved
            </span>
          ) : face === 'rejected' ? (
            <span className="shrink-0 text-xs font-medium text-danger">Rejected</span>
          ) : null}
        </button>
      }
    >
      {tool.sources?.length && !failed ? <SourceChips sources={tool.sources} /> : null}
      <Collapse open={open}>
        <div className="space-y-3 pb-0.5">
          <ArgsView tool={tool} args={args} />
          {face === 'pending' && (
            <div className="rounded-md border border-warning/25 bg-warning/5 px-3 py-2 text-xs text-warning">
              Waiting for your approval — respond in the bar below.
            </div>
          )}
          {face === 'rejected' && (
            <div className="rounded-md border border-danger/25 bg-danger/5 px-3 py-2 text-xs text-danger">
              Rejected by you{tool.approval?.reason ? ` — ${tool.approval.reason}` : ''}. The tool never ran.
            </div>
          )}
          {tool.sources?.length && !failed ? null : <ResultView tool={tool} />}
        </div>
      </Collapse>
    </CoTStep>
  );
}
